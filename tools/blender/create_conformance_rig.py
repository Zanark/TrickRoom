"""Run inside Blender: create an original technical fixture, not the final character."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from trickroom.assets.profile import RigProfile  # noqa: E402


def create(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.render.fps = 30
    scene.frame_start, scene.frame_end = 1, 31
    arm_data = bpy.data.armatures.new("TrickRoomHumanoid")
    rig = bpy.data.objects.new("TrickRoomRig", arm_data)
    scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    definitions = {
        "Hips": ((0, 0, 1.00), (0, 0, 1.12), None),
        "Spine": ((0, 0, 1.12), (0, 0, 1.32), "Hips"),
        "Chest": ((0, 0, 1.32), (0, 0, 1.57), "Spine"),
        "Neck": ((0, 0, 1.57), (0, 0, 1.70), "Chest"),
        "Head": ((0, 0, 1.70), (0, 0, 2.01), "Neck"),
    }
    for suffix, sign in (("L", 1), ("R", -1)):
        definitions.update(
            {
                f"Shoulder.{suffix}": ((sign * 0.07, 0, 1.47), (sign * 0.27, 0, 1.47), "Chest"),
                f"UpperArm.{suffix}": (
                    (sign * 0.27, 0, 1.47),
                    (sign * 0.60, 0, 1.47),
                    f"Shoulder.{suffix}",
                ),
                f"LowerArm.{suffix}": (
                    (sign * 0.60, 0, 1.47),
                    (sign * 0.88, 0, 1.47),
                    f"UpperArm.{suffix}",
                ),
                f"Hand.{suffix}": (
                    (sign * 0.88, 0, 1.47),
                    (sign * 1.04, 0, 1.47),
                    f"LowerArm.{suffix}",
                ),
                f"UpperLeg.{suffix}": ((sign * 0.13, 0, 1.00), (sign * 0.13, 0, 0.57), "Hips"),
                f"LowerLeg.{suffix}": (
                    (sign * 0.13, 0, 0.57),
                    (sign * 0.13, 0, 0.13),
                    f"UpperLeg.{suffix}",
                ),
                f"Foot.{suffix}": (
                    (sign * 0.13, 0, 0.13),
                    (sign * 0.13, -0.18, 0.05),
                    f"LowerLeg.{suffix}",
                ),
                f"Toes.{suffix}": (
                    (sign * 0.13, -0.18, 0.05),
                    (sign * 0.13, -0.29, 0.05),
                    f"Foot.{suffix}",
                ),
                f"Eye.{suffix}": (
                    (sign * 0.063, -0.145, 1.86),
                    (sign * 0.063, -0.18, 1.86),
                    "Head",
                ),
            }
        )
    for name, (head, tail, parent) in definitions.items():
        bone = arm_data.edit_bones.new(name)
        bone.head, bone.tail = head, tail
        if parent:
            bone.parent = arm_data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")

    def material(name, rgba):
        result = bpy.data.materials.new(name)
        result.diffuse_color = rgba
        result.use_nodes = True
        shader = result.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = rgba
        shader.inputs["Metallic"].default_value = 0
        shader.inputs["Roughness"].default_value = 1
        return result

    materials = [
        material("TechnicalTorso", (0.11, 0.50, 0.40, 1)),
        material("TechnicalLimbs", (0.25, 0.28, 0.55, 1)),
        material("TechnicalHead", (0.68, 0.42, 0.22, 1)),
        material("FacialInk", (0.013, 0.015, 0.02, 1)),
        material("TechnicalShoes", (0.65, 0.63, 0.57, 1)),
    ]
    atlas = bpy.data.images.new("TrickRoomChecker", 64, 64, alpha=True)
    pixels = []
    for y in range(64):
        for x in range(64):
            shade = 0.92 if (x // 8 + y // 8) % 2 else 0.68
            pixels.extend((shade, shade, shade, 1))
    atlas.pixels.foreach_set(pixels)
    atlas.pack()
    nodes = materials[0].node_tree.nodes
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = atlas
    tex.interpolation = "Closest"
    materials[0].node_tree.links.new(
        tex.outputs["Color"],
        nodes.get("Principled BSDF").inputs["Base Color"],
    )

    vertices, faces, material_ids, weights, tags = [], [], [], [], {}

    def point(xyz, influence, tag=None):
        index = len(vertices)
        vertices.append(xyz)
        weights.append(influence)
        if tag:
            tags.setdefault(tag, []).append(index)
        return index

    def face(indices, material_index):
        faces.append(indices)
        material_ids.append(material_index)

    def vertical(rings, material_index, influence_at, tag=None, center_x=0, center_y=0):
        previous = None
        first = None
        for z, rx, ry in rings:
            ring = [
                point(
                    (
                        center_x + math.cos(i * math.tau / 8) * rx,
                        center_y + math.sin(i * math.tau / 8) * ry,
                        z,
                    ),
                    influence_at(z),
                    tag,
                )
                for i in range(8)
            ]
            if previous is not None:
                for i in range(8):
                    face(
                        (previous[i], previous[(i + 1) % 8], ring[(i + 1) % 8], ring[i]),
                        material_index,
                    )
            else:
                first = ring
            previous = ring
        face(tuple(first[::-1]), material_index)
        face(tuple(previous), material_index)

    def blend_axis(value, centers):
        for index in range(len(centers) - 1):
            left, right = centers[index : index + 2]
            if left[0] <= value <= right[0]:
                factor = (value - left[0]) / (right[0] - left[0])
                return {left[1]: 1 - factor, right[1]: factor}
        return {centers[0 if value < centers[0][0] else -1][1]: 1}

    vertical(
        (
            (0.96, 0.18, 0.10),
            (1.09, 0.20, 0.11),
            (1.25, 0.22, 0.12),
            (1.42, 0.27, 0.12),
            (1.53, 0.24, 0.10),
        ),
        0,
        lambda z: blend_axis(z, ((1.0, "Hips"), (1.18, "Spine"), (1.40, "Chest"))),
    )
    vertical(((1.52, 0.055, 0.052), (1.72, 0.055, 0.052)), 2, lambda z: {"Neck": 1})
    vertical(
        ((1.69, 0.10, 0.09), (1.74, 0.145, 0.12), (1.93, 0.16, 0.145), (2.04, 0.11, 0.10)),
        2,
        lambda z: {"Head": 1},
        center_y=-0.015,
    )
    for suffix, sign in (("L", 1), ("R", -1)):
        previous = None
        for x in (0.25, 0.39, 0.53, 0.60, 0.69, 0.80, 0.90, 1.01):
            ring = [
                point(
                    (
                        sign * x,
                        math.cos(i * math.tau / 8) * 0.07,
                        1.47 + math.sin(i * math.tau / 8) * 0.07,
                    ),
                    blend_axis(
                        x,
                        (
                            (0.40, f"UpperArm.{suffix}"),
                            (0.71, f"LowerArm.{suffix}"),
                            (0.98, f"Hand.{suffix}"),
                        ),
                    ),
                )
                for i in range(8)
            ]
            if previous is not None:
                for i in range(8):
                    face((previous[i], previous[(i + 1) % 8], ring[(i + 1) % 8], ring[i]), 1)
            previous = ring
        vertical(
            (
                (0.13, 0.075, 0.075),
                (0.39, 0.09, 0.085),
                (0.57, 0.10, 0.09),
                (0.75, 0.10, 0.09),
                (1.01, 0.115, 0.10),
            ),
            1,
            lambda z, s=suffix: blend_axis(z, ((0.35, f"LowerLeg.{s}"), (0.77, f"UpperLeg.{s}"))),
            center_x=sign * 0.13,
        )
        vertical(
            ((0.01, 0.095, 0.19), (0.11, 0.09, 0.18)),
            4,
            lambda z, s=suffix: {f"Foot.{s}": 1},
            center_x=sign * 0.13,
            center_y=-0.10,
        )

    def feature(name, cx, cz, half_w, half_h):
        ids = [
            point((cx + dx, -0.169, cz + dz), {"Head": 1}, name)
            for dx, dz in (
                (-half_w, -half_h),
                (half_w, -half_h),
                (half_w, half_h),
                (-half_w, half_h),
            )
        ]
        face(tuple(ids), 3)

    feature("eye.L", 0.063, 1.866, 0.013, 0.028)
    feature("eye.R", -0.063, 1.866, 0.013, 0.028)
    feature("brow.L", 0.063, 1.922, 0.037, 0.004)
    feature("brow.R", -0.063, 1.922, 0.037, 0.004)
    feature("mouth", 0, 1.785, 0.047, 0.003)
    mesh = bpy.data.meshes.new("ConformanceBody")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("ConformanceBody", mesh)
    scene.collection.objects.link(obj)
    for mat in materials:
        mesh.materials.append(mat)
    for polygon, index in zip(mesh.polygons, material_ids, strict=True):
        polygon.material_index = index
        polygon.use_smooth = False
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            uv.data[loop_index].uv = (vertex.x + 0.5, (vertex.z - 0.9) * 1.4)
    for bone in definitions:
        group = obj.vertex_groups.new(name=bone)
        for i, influence in enumerate(weights):
            if influence.get(bone, 0) > 1e-6:
                group.add([i], influence[bone], "REPLACE")
    modifier = obj.modifiers.new("TrickRoomArmature", "ARMATURE")
    modifier.object = rig
    obj.parent = rig
    obj.shape_key_add(name="Basis")
    for logical, name in RigProfile().shapes.items():
        key = obj.shape_key_add(name=name)
        if logical.startswith("blink"):
            side = "L" if logical.endswith("left") else "R"
            for index in tags[f"eye.{side}"]:
                key.data[index].co.z = 1.866 + (vertices[index][2] - 1.866) * 0.08
        elif logical == "jaw_open":
            for index in tags["mouth"][:2]:
                key.data[index].co.z -= 0.055
        elif logical == "smile":
            for index in tags["mouth"]:
                key.data[index].co.x *= 1.45
                key.data[index].co.z += 0.011
        elif logical.startswith("brow_"):
            side = "L" if logical.endswith("left") else "R"
            delta = 0.024 if "_up_" in logical else -0.018
            for index in tags[f"brow.{side}"]:
                key.data[index].co.z += delta
        elif logical.startswith("look_"):
            for side in ("L", "R"):
                for index in tags[f"eye.{side}"]:
                    if logical in ("look_left", "look_right"):
                        key.data[index].co.x += 0.025 if logical == "look_left" else -0.025
                    else:
                        key.data[index].co.z += 0.017 if logical == "look_up" else -0.017
    for item in bpy.context.selected_objects:
        item.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    bone = rig.pose.bones["LowerArm.L"]
    bone.rotation_mode = "QUATERNION"
    for frame, angle in ((1, 0), (16, 1.0), (31, 0)):
        bone.rotation_quaternion = Quaternion((1, 0, 0), angle)
        bone.keyframe_insert("rotation_quaternion", frame=frame)
    rig.animation_data.action.name = "ConformanceWave"
    smile = obj.data.shape_keys.key_blocks["TR_Smile"]
    for frame, value in ((1, 0), (16, 1), (31, 0)):
        smile.value = value
        smile.keyframe_insert("value", frame=frame)
    obj.data.shape_keys.animation_data.action.name = "ConformanceFace"
    for name, peak in (("TR_Blink_L", 1.0), ("TR_Blink_R", 0.65), ("TR_Jaw_Open", 0.8)):
        key = obj.data.shape_keys.key_blocks[name]
        for frame, value in ((1, 0), (16, peak), (31, 0)):
            key.value = value
            key.keyframe_insert("value", frame=frame)
    scene.frame_set(1)
    for block in obj.data.shape_keys.key_blocks:
        block.value = 0
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    blend = output / "TrickRoom-Conformance.blend"
    glb = output / "TrickRoom-Conformance.glb"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.export_scene.gltf(
        filepath=str(glb),
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_animations=True,
        export_force_sampling=True,
        export_animation_mode="ACTIONS",
        export_anim_slide_to_zero=True,
        export_skins=True,
        export_influence_nb=4,
        export_all_influences=False,
        export_morph=True,
        export_morph_normal=True,
        export_extras=True,
        export_def_bones=False,
        export_leaf_bone=False,
        export_apply=False,
    )
    profile = output / "TrickRoom-Conformance.trickroom.json"
    profile.write_text(json.dumps(RigProfile().to_dict(), indent=2) + "\n", encoding="utf-8")
    for suffix in ("L", "R"):
        indices = tags[f"eye.{suffix}"]
        obj.vertex_groups["Head"].remove(indices)
        obj.vertex_groups[f"Eye.{suffix}"].add(indices, 1, "REPLACE")
    eyes_blend = output / "TrickRoom-EyeBones.blend"
    eyes_glb = output / "TrickRoom-EyeBones.glb"
    eyes_profile = output / "TrickRoom-EyeBones.trickroom.json"
    bpy.ops.wm.save_as_mainfile(filepath=str(eyes_blend))
    bpy.ops.export_scene.gltf(
        filepath=str(eyes_glb),
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_animations=False,
        export_skins=True,
        export_influence_nb=4,
        export_all_influences=False,
        export_morph=True,
        export_morph_normal=True,
        export_extras=True,
        export_def_bones=False,
        export_leaf_bone=False,
        export_apply=False,
    )
    eyes_profile.write_text(
        json.dumps(RigProfile(gaze_mode="bones").to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    receipt = {
        "blender": bpy.app.version_string,
        "purpose": "Original technical interoperability fixture, not final avatar artwork.",
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "bone_count": len(definitions),
        "required_shape_keys": list(RigProfile().shapes.values()),
        "files": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (blend, glb, profile, eyes_blend, eyes_glb, eyes_profile)
        },
    }
    (output / "conformance-build.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "examples" / "blender")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    create(args.output.resolve())
