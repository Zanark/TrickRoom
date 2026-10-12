"""A bounded, self-contained GLB 2.0 importer for TrickRoom's humanoid profile."""

from __future__ import annotations

import hashlib
import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from trickroom.assets.math3d import compose, decompose, transform_points
from trickroom.assets.profile import (
    LIMITS,
    OPTIONAL_BONES,
    PARENTS,
    AssetError,
    RigProfile,
)
from trickroom.assets.types import Asset, Channel, Clip, Material, Node, Primitive, Skin, Texture

COMPONENTS = {
    5120: np.dtype("i1"),
    5121: np.dtype("u1"),
    5122: np.dtype("<i2"),
    5123: np.dtype("<u2"),
    5125: np.dtype("<u4"),
    5126: np.dtype("<f4"),
}
WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def integer(value, label, minimum=0, maximum=10_000_000):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise AssetError("INTEGER", f"{label} must be an integer in [{minimum}, {maximum}].")
    return value


def vector(value, count, label):
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise AssetError("VECTOR", f"{label} must contain {count} numbers.")
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as error:
        raise AssetError("VECTOR", f"{label} contains a non-numeric value.") from error
    if not np.isfinite(result).all() or np.max(np.abs(result), initial=0) > 1e6:
        raise AssetError("FINITE", f"{label} must contain finite, bounded values.")
    return result


def table(document, name, maximum=10000):
    result = document.get(name, [])
    if (
        not isinstance(result, list)
        or len(result) > maximum
        or any(not isinstance(item, dict) for item in result)
    ):
        raise AssetError("TABLE", f"{name} must be an array of at most {maximum} objects.")
    return result


def reference(index, items, label):
    return integer(index, label, maximum=len(items) - 1)


def frozen(array, dtype=None):
    result = np.asarray(array, dtype=dtype)
    result.flags.writeable = False
    return result


def _invalid_constant(_value):
    raise AssetError("JSON_NUMBER", "Non-finite JSON numbers are not supported.")


def read_glb(path: Path):
    if path.suffix.lower() != ".glb":
        raise AssetError(
            "FORMAT", "Export glTF 2.0 in Binary (.glb) form; .blend/.fbx are not runtime files."
        )
    if not path.is_file() or not 20 <= path.stat().st_size <= LIMITS["file_bytes"]:
        raise AssetError("FILE_SIZE", "GLB is missing, too short, or exceeds 64 MiB.")
    raw = path.read_bytes()
    if not 20 <= len(raw) <= LIMITS["file_bytes"]:
        raise AssetError("FILE_SIZE", "GLB changed size while loading or exceeds the file budget.")
    magic, version, length = struct.unpack_from("<4sII", raw)
    if magic != b"glTF" or version != 2 or length != len(raw):
        raise AssetError("HEADER", "GLB header/version/declared length is invalid.")
    chunks = []
    offset = 12
    while offset < len(raw):
        if offset + 8 > len(raw):
            raise AssetError("CHUNK", "Truncated GLB chunk header.")
        size, kind = struct.unpack_from("<II", raw, offset)
        offset += 8
        if size % 4 or offset + size > len(raw):
            raise AssetError("CHUNK", "GLB chunk length/alignment is invalid.")
        chunks.append((kind, raw[offset : offset + size]))
        offset += size
    if not chunks or chunks[0][0] != 0x4E4F534A or len(chunks[0][1]) > LIMITS["json_bytes"]:
        raise AssetError("JSON_CHUNK", "GLB must start with a JSON chunk no larger than 4 MiB.")
    if len(chunks) != 2 or chunks[1][0] != 0x004E4942:
        raise AssetError("BIN_CHUNK", "Use one JSON chunk and one embedded BIN chunk.")
    try:
        document = json.loads(chunks[0][1].decode("utf-8"), parse_constant=_invalid_constant)
    except (UnicodeError, ValueError) as error:
        raise AssetError("JSON", "GLB JSON could not be decoded.") from error
    if not isinstance(document, dict) or document.get("asset", {}).get("version") != "2.0":
        raise AssetError("VERSION", "Only glTF asset version 2.0 is supported.")
    buffers = table(document, "buffers", 1)
    if len(buffers) != 1 or "uri" in buffers[0]:
        raise AssetError(
            "EXTERNAL_RESOURCE", "GLB must embed its buffer; no URLs or external files."
        )
    size = integer(buffers[0].get("byteLength"), "buffer.byteLength")
    if not size <= len(chunks[1][1]) <= size + 3:
        raise AssetError("BUFFER_SIZE", "Embedded buffer length does not match its declaration.")
    return document, chunks[1][1][:size], hashlib.sha256(raw).hexdigest()


class Accessors:
    def __init__(self, document, binary):
        self.views = table(document, "bufferViews")
        self.accessors = table(document, "accessors")
        self.binary = binary
        self.cache = {}
        self.bytes = 0
        for view in self.views:
            if view.get("buffer", 0) != 0 or view.get("extensions"):
                raise AssetError(
                    "BUFFER_VIEW", "Only uncompressed embedded buffer views are supported."
                )
            start = integer(view.get("byteOffset", 0), "bufferView.byteOffset")
            size = integer(view.get("byteLength"), "bufferView.byteLength")
            if start + size > len(binary):
                raise AssetError("BUFFER_BOUNDS", "A buffer view exceeds the embedded buffer.")

    def view_bytes(self, index):
        view = self.views[reference(index, self.views, "bufferView")]
        offset = view.get("byteOffset", 0)
        return self.binary[offset : offset + view["byteLength"]]

    def _values(self, view_index, byte_offset, count, width, dtype, *, sparse=False):
        view = self.views[reference(view_index, self.views, "bufferView")]
        offset = integer(byte_offset, "accessor.byteOffset")
        item_size = width * dtype.itemsize
        stride = integer(
            view.get("byteStride", item_size), "byteStride", minimum=item_size, maximum=252
        )
        if sparse and "byteStride" in view:
            raise AssetError("SPARSE_STRIDE", "Sparse index/value views must be tightly packed.")
        if stride % dtype.itemsize or offset % dtype.itemsize:
            raise AssetError("ALIGNMENT", "Accessor component alignment is invalid.")
        needed = offset + (count - 1) * stride + item_size if count else offset
        if needed > view["byteLength"]:
            raise AssetError("ACCESSOR_BOUNDS", "Accessor data exceeds its buffer view.")
        return np.ndarray(
            (count, width),
            dtype=dtype,
            buffer=self.binary,
            offset=view.get("byteOffset", 0) + offset,
            strides=(stride, dtype.itemsize),
        )

    def read(self, index, kind=None, components=None, *, integer_data=False):
        index = reference(index, self.accessors, "accessor")
        accessor = self.accessors[index]
        if integer_data and accessor.get("normalized", False):
            raise AssetError(
                "INTEGER_NORMALIZED", "Joint and index accessors must not be normalized."
            )
        if kind is not None and accessor.get("type") != kind:
            raise AssetError("ACCESSOR_TYPE", f"Expected {kind} accessor.")
        component = accessor.get("componentType")
        if component not in COMPONENTS or (components is not None and component not in components):
            raise AssetError("COMPONENT_TYPE", "Accessor component type is not supported here.")
        if index in self.cache:
            return self.cache[index]
        dtype = COMPONENTS[component]
        width = WIDTHS.get(accessor.get("type"))
        if width is None or accessor.get("extensions"):
            raise AssetError(
                "ACCESSOR_TYPE", "Only scalar, vector and float MAT4 accessors are supported."
            )
        if width == 16 and component != 5126:
            raise AssetError("MATRIX_COMPONENT", "Inverse bind matrices must use float components.")
        count = integer(accessor.get("count"), "accessor.count", minimum=1, maximum=4_000_000)
        byte_count = count * width * 8
        if self.bytes + byte_count > LIMITS["decoded_array_bytes"]:
            raise AssetError("ARRAY_BUDGET", "Decoded accessor data exceeds the 128 MiB budget.")
        if "bufferView" in accessor:
            values = self._values(
                accessor["bufferView"], accessor.get("byteOffset", 0), count, width, dtype
            ).copy()
        else:
            if accessor.get("byteOffset", 0):
                raise AssetError(
                    "ACCESSOR_OFFSET", "An accessor without a view cannot have an offset."
                )
            values = np.zeros((count, width), dtype=dtype)
        if "sparse" in accessor:
            sparse = accessor["sparse"]
            sparse_count = integer(sparse.get("count"), "sparse.count", minimum=1, maximum=count)
            indices_spec, values_spec = sparse["indices"], sparse["values"]
            index_type = indices_spec.get("componentType")
            if index_type not in (5121, 5123, 5125):
                raise AssetError("SPARSE_INDEX", "Sparse indices must be unsigned integers.")
            indices = self._values(
                indices_spec["bufferView"],
                indices_spec.get("byteOffset", 0),
                sparse_count,
                1,
                COMPONENTS[index_type],
                sparse=True,
            ).ravel()
            if np.any(indices >= count) or np.any(np.diff(indices.astype(np.int64)) <= 0):
                raise AssetError(
                    "SPARSE_INDEX", "Sparse indices must be sorted, unique and in bounds."
                )
            values[indices] = self._values(
                values_spec["bufferView"],
                values_spec.get("byteOffset", 0),
                sparse_count,
                width,
                dtype,
                sparse=True,
            )
        if accessor.get("normalized", False):
            if component == 5126 or component == 5125:
                raise AssetError("NORMALIZED", "This component type cannot be normalized.")
            maximum = np.iinfo(dtype).max
            values = np.maximum(values.astype(float) / maximum, -1)
        if not np.isfinite(values).all() or np.max(np.abs(values), initial=0) > 1e9:
            raise AssetError("FINITE", "Accessor contains non-finite or excessive values.")
        self.bytes += byte_count
        self.cache[index] = frozen(values)
        return self.cache[index]


def _nodes(document):
    raw_nodes = table(document, "nodes", LIMITS["nodes"])
    if not raw_nodes:
        raise AssetError("NO_NODES", "No model nodes were exported.")
    parents = [-1] * len(raw_nodes)
    for index, raw in enumerate(raw_nodes):
        children = raw.get("children", [])
        if not isinstance(children, list):
            raise AssetError("CHILDREN", "Node children must be an array.")
        for child in children:
            child = reference(child, raw_nodes, "child")
            if parents[child] >= 0 or child == index:
                raise AssetError("HIERARCHY", "Nodes must form a tree, without duplicate parents.")
            parents[child] = index
    scenes = table(document, "scenes")
    scene = scenes[reference(document.get("scene", 0), scenes, "scene")]
    roots = scene.get("nodes", [])
    order, active, visiting = [], set(), set()

    def walk(index, depth=0):
        reference(index, raw_nodes, "scene node")
        if index in visiting or depth > 64:
            raise AssetError("HIERARCHY", "Node hierarchy is cyclic or deeper than 64.")
        if index in active:
            raise AssetError("HIERARCHY", "Node occurs more than once in the scene.")
        visiting.add(index)
        order.append(index)
        for child in raw_nodes[index].get("children", []):
            walk(child, depth + 1)
        visiting.remove(index)
        active.add(index)

    for root in roots:
        reference(root, raw_nodes, "scene root")
        if parents[root] != -1:
            raise AssetError("SCENE_ROOT", "Scene roots cannot have parents.")
        walk(root)
    if len(active) != len(raw_nodes):
        raise AssetError(
            "INACTIVE_NODES",
            "Export only the character scene; inactive/cyclic nodes are unsupported.",
        )
    nodes = []
    for index, raw in enumerate(raw_nodes):
        if raw.get("extensions"):
            raise AssetError("NODE_EXTENSION", "Remove node extensions such as lights/instancing.")
        name = raw.get("name", f"node_{index}")
        if not isinstance(name, str) or len(name) > 128 or any(ord(c) < 32 for c in name):
            raise AssetError(
                "NODE_NAME", "Node names must be printable strings under 129 characters."
            )
        if "matrix" in raw:
            if any(key in raw for key in ("translation", "rotation", "scale")):
                raise AssetError("NODE_TRANSFORM", "A node cannot contain both matrix and TRS.")
            matrix = vector(raw["matrix"], 16, "node.matrix").reshape(4, 4).T
            translation, rotation, scale = decompose(matrix)
        else:
            translation = vector(raw.get("translation", [0, 0, 0]), 3, "node.translation")
            rotation = vector(raw.get("rotation", [0, 0, 0, 1]), 4, "node.rotation")
            scale = vector(raw.get("scale", [1, 1, 1]), 3, "node.scale")
            if not 0.999 <= np.linalg.norm(rotation) <= 1.001:
                raise AssetError("QUATERNION", "Node rotations must be unit quaternions.")
        if np.any(scale <= 0) or not np.allclose(scale, scale[0], rtol=1e-4, atol=1e-6):
            raise AssetError(
                "SCALE", "Apply negative/nonuniform object and bone scales before export."
            )
        weights = np.asarray(raw["weights"], float) if "weights" in raw else None
        nodes.append(
            Node(
                name,
                parents[index],
                frozen(translation),
                frozen(rotation),
                frozen(scale),
                raw.get("mesh"),
                raw.get("skin"),
                weights,
            )
        )
    globals_ = np.tile(np.eye(4), (len(nodes), 1, 1))
    for index in order:
        node = nodes[index]
        local = compose(node.translation, node.rotation, node.scale)
        globals_[index] = globals_[node.parent] @ local if node.parent >= 0 else local
    return tuple(nodes), tuple(order), frozen(globals_)


def _textures(document, reader):
    images = table(document, "images", LIMITS["textures"])
    decoded, total_pixels = [], 0
    for item in images:
        if "uri" in item or item.get("mimeType") not in ("image/png", "image/jpeg"):
            raise AssetError(
                "IMAGE", "Embed PNG/JPEG images in the GLB; external/data URLs are not loaded."
            )
        data = reader.view_bytes(item.get("bufferView"))
        try:
            with Image.open(io.BytesIO(data)) as image:
                w, h = image.size
                total_pixels += w * h
                if (
                    max(w, h) > LIMITS["image_dimension"]
                    or total_pixels > LIMITS["decoded_image_pixels"]
                ):
                    raise AssetError(
                        "IMAGE_BUDGET", "Images exceed 4096 pixels/side or 8M total pixels."
                    )
                if image.format not in ("PNG", "JPEG"):
                    raise AssetError("IMAGE_FORMAT", "Embedded images must decode as PNG/JPEG.")
                decoded.append(frozen(np.asarray(image.convert("RGBA"), np.uint8).copy()))
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise AssetError(
                "IMAGE_DECODE", "An embedded image could not be decoded safely."
            ) from error
    samplers = table(document, "samplers", 64)
    textures = []
    for item in table(document, "textures", LIMITS["textures"]):
        if item.get("extensions"):
            raise AssetError(
                "TEXTURE_EXTENSION",
                "Use embedded ordinary PNG/JPEG textures, not compressed textures.",
            )
        rgba = decoded[reference(item.get("source"), decoded, "texture.source")]
        sampler = (
            samplers[reference(item["sampler"], samplers, "sampler")] if "sampler" in item else {}
        )
        minimum, magnification = sampler.get("minFilter", 9729), sampler.get("magFilter", 9729)
        s, t = sampler.get("wrapS", 10497), sampler.get("wrapT", 10497)
        if minimum not in (9728, 9729, 9984, 9985, 9986, 9987) or magnification not in (9728, 9729):
            raise AssetError("SAMPLER", "Invalid texture filtering mode.")
        if s not in (33071, 33648, 10497) or t not in (33071, 33648, 10497):
            raise AssetError("SAMPLER", "Invalid texture wrapping mode.")
        textures.append(
            Texture(rgba, hashlib.sha256(rgba.tobytes()).hexdigest(), minimum, magnification, s, t)
        )
    return tuple(textures)


def _materials(document, textures, warnings):
    materials = []
    for index, item in enumerate(table(document, "materials", 64)):
        pbr = item.get("pbrMetallicRoughness", {})
        extensions = item.get("extensions", {})
        if set(extensions) - {"KHR_materials_unlit"}:
            raise AssetError(
                "MATERIAL_EXTENSION",
                "Bake complex material effects into base color; only unlit extension is supported.",
            )
        if any(key in item for key in ("normalTexture", "occlusionTexture", "emissiveTexture")):
            raise AssetError(
                "MATERIAL_MAP", "Bake normal/AO/emission maps into base color for this runtime."
            )
        if "metallicRoughnessTexture" in pbr or np.any(
            vector(item.get("emissiveFactor", [0, 0, 0]), 3, "emissive")
        ):
            raise AssetError(
                "MATERIAL_PBR",
                "Separate PBR/emission maps are unsupported; bake a base-color texture.",
            )
        factor = vector(pbr.get("baseColorFactor", [1, 1, 1, 1]), 4, "baseColorFactor")
        if np.any(factor < 0) or np.any(factor > 1):
            raise AssetError("BASE_COLOR", "Base color factors must be in [0,1].")
        info = pbr.get("baseColorTexture")
        texture = None
        if info is not None:
            if info.get("texCoord", 0) != 0 or info.get("extensions"):
                raise AssetError(
                    "UV_SET", "Use TEXCOORD_0 and bake Mapping-node transforms into UVs."
                )
            texture = reference(info.get("index"), textures, "baseColorTexture")
        mode = item.get("alphaMode", "OPAQUE")
        if mode not in ("OPAQUE", "MASK"):
            raise AssetError(
                "ALPHA_BLEND",
                "Use OPAQUE or MASK. Layered alpha BLEND/transmission is not supported.",
            )
        cutoff = float(item.get("alphaCutoff", 0.5))
        if not np.isfinite(cutoff) or not 0 <= cutoff <= 1:
            raise AssetError("ALPHA_CUTOFF", "Alpha cutoff must be finite and in [0,1].")
        unlit = "KHR_materials_unlit" in extensions
        if not unlit and pbr.get("metallicFactor", 1) != 0:
            warnings.append(
                f"Material {index}: PS1 diffuse lighting, not metallic/PBR reflections."
            )
        materials.append(
            Material(
                str(item.get("name", f"Material{index}"))[:128],
                tuple(factor),
                texture,
                mode,
                cutoff,
                bool(item.get("doubleSided", False)),
                unlit,
            )
        )
    materials.append(Material("Default"))
    return tuple(materials)


def _skins(document, reader, nodes):
    skins = []
    for raw in table(document, "skins", 16):
        joints = raw.get("joints", [])
        if not isinstance(joints, list) or not 1 <= len(joints) <= LIMITS["joints_per_skin"]:
            raise AssetError("JOINT_COUNT", "A skin must have 1-128 joints.")
        joints = tuple(reference(i, nodes, "skin.joint") for i in joints)
        if len(set(joints)) != len(joints):
            raise AssetError("DUPLICATE_JOINT", "Skin joints must be unique.")
        if "inverseBindMatrices" not in raw:
            raise AssetError("BIND_MATRICES", "Export inverse bind matrices with the armature.")
        matrices = reader.read(raw["inverseBindMatrices"], "MAT4", (5126,))
        if len(matrices) != len(joints):
            raise AssetError("BIND_COUNT", "One inverse bind matrix is required per joint.")
        matrices = matrices.reshape(-1, 4, 4).transpose(0, 2, 1)
        if not np.allclose(matrices[:, 3], (0, 0, 0, 1), atol=1e-5) or np.any(
            np.abs(np.linalg.det(matrices[:, :3, :3])) < 1e-10
        ):
            raise AssetError(
                "BIND_MATRIX", "Inverse bind matrices must be invertible affine matrices."
            )
        skins.append(Skin(joints, frozen(matrices)))
    return tuple(skins)


def _primitives(document, reader, nodes, skins, materials):
    meshes = table(document, "meshes", 128)
    primitives = []
    total_vertices = total_triangles = total_bytes = 0
    for node_index, node in enumerate(nodes):
        if node.mesh is None:
            continue
        mesh = meshes[reference(node.mesh, meshes, "node.mesh")]
        if node.skin is not None:
            reference(node.skin, skins, "node.skin")
        names = mesh.get("extras", {}).get("targetNames", [])
        for raw in table(mesh, "primitives", LIMITS["primitives"]):
            if (
                len(primitives) >= LIMITS["primitives"]
                or raw.get("mode", 4) != 4
                or raw.get("extensions")
            ):
                raise AssetError(
                    "PRIMITIVE", "Export at most 64 uncompressed TRIANGLES primitives."
                )
            attrs = raw.get("attributes", {})
            if "JOINTS_1" in attrs or "WEIGHTS_1" in attrs:
                raise AssetError("INFLUENCES", "Limit total vertex influences to four in Blender.")
            positions = reader.read(attrs.get("POSITION"), "VEC3", (5126,)).astype(float)
            n = len(positions)
            indices = (
                reader.read(raw["indices"], "SCALAR", (5121, 5123, 5125), integer_data=True).ravel()
                if "indices" in raw
                else np.arange(n)
            )
            if len(indices) % 3 or np.any(indices >= n):
                raise AssetError(
                    "INDICES", "Triangle indices must be in range and divisible by three."
                )
            indices = indices.reshape(-1, 3).astype(np.int32)
            total_vertices += n
            total_triangles += len(indices)
            if total_vertices > LIMITS["vertices"] or total_triangles > LIMITS["triangles"]:
                raise AssetError(
                    "GEOMETRY_BUDGET", "Model exceeds 80000 vertices or 100000 triangles."
                )
            normals = (
                reader.read(attrs["NORMAL"], "VEC3", (5126,)).astype(float)
                if "NORMAL" in attrs
                else None
            )
            uv = (
                reader.read(attrs["TEXCOORD_0"], "VEC2", (5121, 5123, 5126)).astype(float)
                if "TEXCOORD_0" in attrs
                else np.zeros((n, 2))
            )
            colors = np.ones((n, 4))
            if "COLOR_0" in attrs:
                c = reader.read(attrs["COLOR_0"], components=(5121, 5123, 5126)).astype(float)
                if c.shape not in ((n, 3), (n, 4)) or np.any(c < 0) or np.any(c > 1):
                    raise AssetError(
                        "VERTEX_COLOR", "Vertex colors must be normalized RGB/RGBA in [0,1]."
                    )
                colors[:, : c.shape[1]] = c
            material = (
                reference(raw["material"], materials[:-1], "material")
                if "material" in raw
                else len(materials) - 1
            )
            if materials[material].texture is not None and "TEXCOORD_0" not in attrs:
                raise AssetError("MISSING_UV", "A textured primitive must export TEXCOORD_0.")
            if len(uv) != n or (
                normals is not None
                and (len(normals) != n or np.any(np.linalg.norm(normals, axis=1) < 1e-6))
            ):
                raise AssetError(
                    "ATTRIBUTE_COUNT", "Vertex attributes have incompatible counts/normals."
                )
            joints = weights = None
            if node.skin is not None:
                joints = reader.read(
                    attrs.get("JOINTS_0"), "VEC4", (5121, 5123), integer_data=True
                ).astype(np.int32)
                weights = reader.read(attrs.get("WEIGHTS_0"), "VEC4", (5121, 5123, 5126)).astype(
                    float
                )
                if (
                    len(joints) != n
                    or len(weights) != n
                    or np.any(joints >= len(skins[node.skin].joints))
                ):
                    raise AssetError(
                        "SKIN_ATTRIBUTES",
                        "Joint/weight arrays must match vertices and skin joints.",
                    )
                sums = weights.sum(axis=1)
                if np.any(weights < 0) or np.any(np.abs(sums - 1) > 0.015):
                    raise AssetError(
                        "WEIGHTS", "Normalize all vertex weights; no zero-weight vertices."
                    )
                weights /= sums[:, None]
            elif "JOINTS_0" in attrs or "WEIGHTS_0" in attrs:
                raise AssetError("MISSING_SKIN", "Weighted primitive has no skin reference.")
            targets = raw.get("targets", [])
            if not isinstance(targets, list) or len(targets) > LIMITS["morph_targets"]:
                raise AssetError("MORPH_COUNT", "A primitive can have at most 32 morph targets.")
            if targets and (
                not isinstance(names, list)
                or len(names) != len(targets)
                or len(set(names)) != len(names)
                or any(not isinstance(k, str) for k in names)
            ):
                raise AssetError(
                    "MORPH_NAMES", "Export unique shape-key targetNames in mesh extras."
                )
            if n * len(targets) * 3 * 8 * 2 > LIMITS["decoded_array_bytes"]:
                raise AssetError("MORPH_BUDGET", "Morph data exceeds the decoded array budget.")
            mp, mn = [], []
            for target in targets:
                if not isinstance(target, dict) or set(target) - {"POSITION", "NORMAL", "TANGENT"}:
                    raise AssetError(
                        "MORPH_ATTRIBUTES",
                        "Morph targets may contain position/normal/tangent deltas.",
                    )
                p = (
                    reader.read(target["POSITION"], "VEC3", (5126,)).astype(float)
                    if "POSITION" in target
                    else np.zeros((n, 3))
                )
                normal = (
                    reader.read(target["NORMAL"], "VEC3", (5126,)).astype(float)
                    if "NORMAL" in target
                    else np.zeros((n, 3))
                )
                if len(p) != n or len(normal) != n:
                    raise AssetError(
                        "MORPH_VERTICES", "Morph deltas must match the base vertex count."
                    )
                mp.append(p)
                mn.append(normal)
            default = (
                node.weights
                if node.weights is not None
                else np.asarray(
                    mesh.get("weights", [0] * len(targets)),
                    float,
                )
            )
            if (
                default.shape != (len(targets),)
                or not np.isfinite(default).all()
                or np.any(abs(default) > 1)
            ):
                raise AssetError(
                    "MORPH_WEIGHTS", "Default morph weights must match targets and lie in [-1,1]."
                )
            arrays = (
                positions,
                uv,
                colors,
                indices,
                np.asarray(mp).reshape(-1, n, 3),
                np.asarray(mn).reshape(-1, n, 3),
            )
            total_bytes += sum(a.nbytes for a in arrays)
            if total_bytes > LIMITS["decoded_array_bytes"]:
                raise AssetError("MODEL_MEMORY", "Decoded model arrays exceed 128 MiB.")
            primitives.append(
                Primitive(
                    node_index,
                    frozen(positions),
                    frozen(normals) if normals is not None else None,
                    frozen(uv),
                    frozen(colors),
                    frozen(indices),
                    material,
                    frozen(joints) if joints is not None else None,
                    frozen(weights) if weights is not None else None,
                    frozen(arrays[-2]),
                    frozen(arrays[-1]),
                    tuple(names) if targets else (),
                    frozen(default),
                )
            )
    if not primitives:
        raise AssetError("NO_GEOMETRY", "No renderable mesh primitives were exported.")
    return tuple(primitives)


def _clips(document, reader, nodes, primitives):
    clips = []
    total_keys = total_bytes = 0
    for number, raw in enumerate(table(document, "animations", LIMITS["clips"])):
        samplers = table(raw, "samplers", 512)
        channels, seen = [], set()
        for channel in table(raw, "channels", 512):
            target = channel.get("target", {})
            node = reference(target.get("node"), nodes, "animation target")
            path = target.get("path")
            if path not in ("translation", "rotation", "scale", "weights") or (node, path) in seen:
                raise AssetError(
                    "ANIMATION_TARGET", "Only one TRS/weights channel per node/property is allowed."
                )
            seen.add((node, path))
            sampler = samplers[reference(channel.get("sampler"), samplers, "animation sampler")]
            interpolation = sampler.get("interpolation", "LINEAR")
            if interpolation not in ("LINEAR", "STEP"):
                raise AssetError(
                    "ANIMATION_INTERPOLATION",
                    "Bake/resample animation to LINEAR or STEP; CUBICSPLINE is unsupported.",
                )
            times = reader.read(sampler.get("input"), "SCALAR", (5126,)).ravel().astype(float)
            total_keys += len(times)
            if total_keys > LIMITS["animation_keys"]:
                raise AssetError(
                    "ANIMATION_BUDGET", "Combined animation channels exceed100000keys."
                )
            if (
                len(times) > LIMITS["animation_keys"]
                or times[0] < 0
                or times[-1] > 600
                or np.any(np.diff(times) <= 0)
            ):
                raise AssetError(
                    "ANIMATION_TIMES",
                    "Keys must increase, start at/after0 and end within600seconds.",
                )
            if path == "weights":
                matches = [p for p in primitives if p.node == node]
                width = len(matches[0].target_names) if matches else 0
                values = reader.read(sampler.get("output"), "SCALAR", (5126,))
                if width == 0 or values.size != len(times) * width:
                    raise AssetError(
                        "ANIMATION_WEIGHTS",
                        "Animated weights must match that node's morph targets.",
                    )
                values = values.reshape(len(times), width).astype(float)
            else:
                values = reader.read(
                    sampler.get("output"), "VEC4" if path == "rotation" else "VEC3", (5126,)
                ).astype(float)
                if len(values) != len(times):
                    raise AssetError(
                        "ANIMATION_VALUES", "Animation keys and values have different counts."
                    )
            if path == "rotation" and not np.allclose(
                np.linalg.norm(values, axis=1), 1, atol=0.001
            ):
                raise AssetError(
                    "ANIMATION_ROTATION", "Animated rotations must be unit quaternions."
                )
            if path == "scale" and (np.any(values <= 0) or not np.allclose(values, values[:, :1])):
                raise AssetError(
                    "ANIMATION_SCALE", "Animated scales must stay positive and uniform."
                )
            if path == "weights" and np.any(np.abs(values) > 1):
                raise AssetError(
                    "ANIMATION_WEIGHTS", "Animated morph weights must remain in [-1,1]."
                )
            total_bytes += times.nbytes + values.nbytes
            if total_bytes > LIMITS["decoded_array_bytes"]:
                raise AssetError("ANIMATION_MEMORY", "Decoded animation arrays exceed128MiB.")
            channels.append(Channel(node, path, interpolation, frozen(times), frozen(values)))
        if channels:
            name = str(raw.get("name", f"Clip{number}"))[:128]
            if name in ("live", "bind") or any(c.name == name for c in clips):
                raise AssetError("CLIP_NAME", "Animation clips require unique names.")
            clips.append(Clip(name, tuple(channels), max(c.times[-1] for c in channels)))
    return tuple(clips)


def _rig(profile, nodes, order, globals_, primitives, skins):
    names = {}
    for index, node in enumerate(nodes):
        names.setdefault(node.name, []).append(index)
    bones = {}
    for logical, name in profile.bones.items():
        matches = names.get(name, [])
        if len(matches) != 1:
            if (
                not matches
                and logical in OPTIONAL_BONES
                and not (profile.gaze_mode == "bones" and logical.startswith("eye_"))
            ):
                continue
            raise AssetError("RIG_BONE", f"Expected exactly one node named {name!r} for {logical}.")
        bones[logical] = matches[0]
    for logical, parent_name in PARENTS.items():
        if logical not in bones:
            continue
        ancestor = nodes[bones[logical]].parent
        while ancestor >= 0 and ancestor != bones[parent_name]:
            ancestor = nodes[ancestor].parent
        if ancestor < 0:
            raise AssetError("RIG_HIERARCHY", f"{logical} must descend from {parent_name}.")
        if (
            np.linalg.norm(globals_[bones[logical], :3, 3] - globals_[bones[parent_name], :3, 3])
            < 1e-5
        ):
            raise AssetError(
                "RIG_LENGTH", f"{logical} and {parent_name} cannot share a zero-length segment."
            )
    if globals_[bones["head"], 1, 3] <= globals_[bones["hips"], 1, 3]:
        raise AssetError("RIG_UP", "Export a Y-up upright character (Blender glTF +Y Up enabled).")
    if globals_[bones["upper_arm_left"], 0, 3] <= globals_[bones["upper_arm_right"], 0, 3]:
        raise AssetError("RIG_SIDES", "Face glTF+Z with anatomical left on+X; check mirror/axes.")
    nonzero_shapes = {
        name
        for p in primitives
        for i, name in enumerate(p.target_names)
        if np.any(np.abs(p.morph_positions[i]) > 1e-7)
    }
    for logical, name in profile.shapes.items():
        if profile.gaze_mode == "bones" and logical.startswith("look_"):
            continue
        if name not in nonzero_shapes:
            raise AssetError(
                "RIG_SHAPE", f"Required expression {logical} needs a nonzero shape key {name!r}."
            )
    reverse = {value: key for key, value in bones.items()}
    drivers = [None] * len(nodes)
    for index in order:
        drivers[index] = reverse.get(
            index, drivers[nodes[index].parent] if nodes[index].parent >= 0 else None
        )
    for primitive in primitives:
        if nodes[primitive.node].skin is None and drivers[primitive.node] is None:
            raise AssetError(
                "UNBOUND_MESH", "Every mesh must be skinned or descend from a mapped bone."
            )
        skin_id = nodes[primitive.node].skin
        if skin_id is not None:
            dominant = primitive.joints[
                np.arange(len(primitive.positions)), np.argmax(primitive.weights, axis=1)
            ]
            if any(drivers[skins[skin_id].joints[joint]] is None for joint in dominant):
                raise AssetError(
                    "UNDRIVEN_VERTEX", "Dominant weights must descend from a mapped humanoid bone."
                )
    if profile.gaze_mode == "bones":
        for side in ("eye_left", "eye_right"):
            influences = False
            for primitive in primitives:
                skin_id = nodes[primitive.node].skin
                if skin_id is None:
                    influences |= drivers[primitive.node] == side
                else:
                    skin = skins[skin_id]
                    slots = [i for i, joint in enumerate(skin.joints) if drivers[joint] == side]
                    influences |= bool(
                        np.any(np.isin(primitive.joints, slots) & (primitive.weights > 0.01))
                    )
            if not influences:
                raise AssetError(
                    "EYE_BINDING", f"{side} must actually influence visible eye geometry."
                )
    return bones, tuple(drivers)


def load_asset(path: Path, profile_path: Path | None = None) -> Asset:
    try:
        document, binary, digest = read_glb(path)
        required = document.get("extensionsRequired", [])
        if not isinstance(required, list) or set(required) - {"KHR_materials_unlit"}:
            raise AssetError(
                "REQUIRED_EXTENSION",
                "Required glTF extensions other than KHR_materials_unlit are unsupported.",
            )
        warnings = []
        if document.get("cameras"):
            warnings.append("Embedded cameras are ignored; TrickRoom owns the stage view.")
        profile = RigProfile.load(profile_path)
        reader = Accessors(document, binary)
        nodes, order, globals_ = _nodes(document)
        textures = _textures(document, reader)
        materials = _materials(document, textures, warnings)
        skins = _skins(document, reader, nodes)
        primitives = _primitives(document, reader, nodes, skins, materials)
        clips = _clips(document, reader, nodes, primitives)
        bones, drivers = _rig(profile, nodes, order, globals_, primitives, skins)
        asset = Asset(
            path.name,
            digest,
            nodes,
            order,
            globals_,
            skins,
            materials,
            textures,
            primitives,
            clips,
            profile,
            bones,
            drivers,
            tuple(warnings),
        )
        from trickroom.assets.animation import deform

        posed = deform(asset, globals_, {})
        for item in posed:
            primitive = item.source
            expected = primitive.positions.copy()
            if len(primitive.default_weights):
                expected += np.einsum(
                    "t,tvc->vc", primitive.default_weights, primitive.morph_positions
                )
            expected = transform_points(expected, globals_[primitive.node])
            if not np.allclose(expected, item.positions, atol=1e-4, rtol=1e-4):
                raise AssetError(
                    "BIND_REST_MISMATCH",
                    "Reset the armature to its bound rest pose before export; "
                    "inverse bind matrices do not match the default mesh pose.",
                )
        points = np.vstack([p.positions for p in posed])
        asset.bounds = frozen(np.array((points.min(axis=0), points.max(axis=0))))
        if not 0.1 <= asset.bounds[1, 1] - asset.bounds[0, 1] <= 10:
            raise AssetError(
                "RIG_UNITS", "Character height must be 0.1-10 scene meters; apply export units."
            )
        return asset
    except AssetError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        struct.error,
        OSError,
    ) as error:
        raise AssetError(
            "MALFORMED_ASSET", "Invalid GLB structure or data; inspect it in Blender and re-export."
        ) from error
