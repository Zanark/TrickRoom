"""Depth-tested offscreen drawing of synthetic triangle data only."""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from trickroom.assets.types import Material, Texture

_VERTEX_SHADER = """
#version 330
uniform vec2 size;
uniform vec2 depth_bounds;
in vec3 position;
in vec3 tint;
flat out vec3 face_tint;
void main() {
    float depth = (position.z - depth_bounds.x) / (depth_bounds.y - depth_bounds.x);
    gl_Position = vec4(position.x / size.x * 2.0 - 1.0,
                       1.0 - position.y / size.y * 2.0, 1.0 - depth * 2.0, 1.0);
    face_tint = tint;
}
"""

_FRAGMENT_SHADER = """
#version 330
flat in vec3 face_tint;
out vec4 fragment;
void main() { fragment = vec4(face_tint, 1.0); }
"""

_LOCAL = threading.local()

_MODEL_VERTEX = """
#version 330
uniform vec2 size;
uniform vec2 depth_bounds;
in vec3 position;
in vec3 normal;
in vec2 uv;
in vec4 vertex_color;
out vec3 surface_normal;
out vec2 texture_uv;
out vec4 surface_color;
void main() {
    float depth = (position.z - depth_bounds.x) / (depth_bounds.y - depth_bounds.x);
    gl_Position = vec4(position.x / size.x * 2.0 - 1.0,
                       1.0 - position.y / size.y * 2.0, 1.0 - depth * 2.0, 1.0);
    surface_normal = normal;
    texture_uv = uv;
    surface_color = vertex_color;
}
"""

_MODEL_FRAGMENT = """
#version 330
uniform sampler2D base_texture;
uniform bool has_texture;
uniform bool unlit;
uniform bool double_sided;
uniform bool alpha_mask;
uniform float alpha_cutoff;
uniform vec4 base_factor;
uniform ivec2 mirror_wrap;
in vec3 surface_normal;
in vec2 texture_uv;
in vec4 surface_color;
out vec4 fragment;
vec3 to_linear(vec3 c) {
    return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c));
}
vec3 to_srgb(vec3 c) {
    c = max(c, vec3(0));
    return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055,
               step(vec3(0.0031308), c));
}
void main() {
    if (!double_sided && !gl_FrontFacing) discard;
    vec2 coord = texture_uv;
    if (mirror_wrap.x == 1) coord.x = 1.0 - abs(mod(coord.x, 2.0) - 1.0);
    if (mirror_wrap.y == 1) coord.y = 1.0 - abs(mod(coord.y, 2.0) - 1.0);
    vec4 texel = has_texture ? texture(base_texture, coord) : vec4(1);
    vec4 base = vec4(to_linear(texel.rgb), texel.a) * base_factor * surface_color;
    if (alpha_mask && base.a < alpha_cutoff) discard;
    vec3 n = normalize(surface_normal);
    if (double_sided && !gl_FrontFacing) n = -n;
    float light = unlit ? 1.0 :
        floor((0.62 + 0.38 * max(0.0, dot(n, normalize(vec3(-0.35, -0.5, 0.8))))) * 16.0) / 16.0;
    fragment = vec4(to_srgb(base.rgb * light), 1.0);
}
"""


@dataclass(frozen=True)
class TexturedBatch:
    triangles: np.ndarray
    normals: np.ndarray
    uv: np.ndarray
    colors: np.ndarray
    material: Material
    texture: Texture | None = None


class DepthRenderer:
    def __init__(self) -> None:
        import moderngl

        try:
            self.context = moderngl.create_standalone_context(require=330)
        except Exception as error:
            raise RuntimeError(
                "The reference avatar requires an OpenGL 3.3 context. "
                "Check the graphics driver; no camera pixels can be displayed."
            ) from error
        try:
            self.program = self.context.program(
                vertex_shader=_VERTEX_SHADER,
                fragment_shader=_FRAGMENT_SHADER,
            )
            self.buffer = self.context.buffer(reserve=1024 * 1024)
            self.array = self.context.vertex_array(
                self.program,
                [(self.buffer, "3f 3f", "position", "tint")],
            )
            self.model_program = self.context.program(
                vertex_shader=_MODEL_VERTEX,
                fragment_shader=_MODEL_FRAGMENT,
            )
            self.model_buffer = self.context.buffer(reserve=1024 * 1024)
            self.model_array = self.context.vertex_array(
                self.model_program,
                [(self.model_buffer, "3f 3f 2f 4f", "position", "normal", "uv", "vertex_color")],
            )
        except Exception:
            self.context.release()
            raise
        self.targets = OrderedDict()
        self.textures = OrderedDict()
        self.context.enable(moderngl.DEPTH_TEST)
        self.context.depth_func = "<="
        self.mode = moderngl.TRIANGLES

    def close(self) -> None:
        for framebuffer, texture, depth in self.targets.values():
            framebuffer.release()
            texture.release()
            depth.release()
        self.targets.clear()
        self.array.release()
        self.buffer.release()
        self.program.release()
        self.clear_textures()
        self.model_array.release()
        self.model_buffer.release()
        self.model_program.release()
        self.context.release()

    def clear_textures(self) -> None:
        for texture in self.textures.values():
            texture.release()
        self.textures.clear()

    def _target(self, image):
        height, width = image.shape[:2]
        key = (width, height)
        if key not in self.targets:
            texture = self.context.texture(key, components=4)
            depth = self.context.depth_renderbuffer(key)
            target = self.context.framebuffer([texture], depth)
            self.targets[key] = (target, texture, depth)
            if len(self.targets) > 4:
                _, old = self.targets.popitem(last=False)
                for resource in old:
                    resource.release()
        self.targets.move_to_end(key)
        target = self.targets[key][0]
        target.use()
        self.context.viewport = (0, 0, width, height)
        target.clear(0, 0, 0, 0, depth=1)
        return target, key

    @staticmethod
    def _composite(target, image):
        height, width = image.shape[:2]
        rgba = np.frombuffer(target.read(components=4, alignment=1), np.uint8).reshape(
            height,
            width,
            4,
        )[::-1]
        cv2.copyTo(np.ascontiguousarray(rgba[:, :, 2::-1]), rgba[:, :, 3].copy(), image)

    def draw(
        self,
        image: NDArray[np.uint8],
        triangles: NDArray[np.float64],
        colors: NDArray[np.uint8],
    ) -> None:
        if len(triangles) == 0:
            return
        target, key = self._target(image)
        values = np.empty((len(triangles), 3, 6), np.float32)
        values[:, :, :3] = triangles
        values[:, :, 3:] = colors[:, None, ::-1] / 255.0
        payload = values.tobytes()
        if len(payload) > self.buffer.size:
            self.buffer.orphan(len(payload))
        self.buffer.write(payload)
        self.program["size"].value = key
        z = triangles[:, :, 2]
        self.program["depth_bounds"].value = (float(z.min() - 1), float(z.max() + 1))
        self.array.render(mode=self.mode, vertices=len(triangles) * 3)
        self._composite(target, image)

    def draw_textured(self, image, batches: list[TexturedBatch]) -> None:
        batches = [batch for batch in batches if len(batch.triangles)]
        if not batches:
            return
        target, key = self._target(image)
        program = self.model_program
        program["size"].value = key
        program["depth_bounds"].value = (
            min(float(b.triangles[:, :, 2].min()) for b in batches) - 1,
            max(float(b.triangles[:, :, 2].max()) for b in batches) + 1,
        )
        program["base_texture"].value = 0
        for batch in batches:
            material = batch.material
            program["base_factor"].value = material.factor
            program["unlit"].value = material.unlit
            program["double_sided"].value = material.double_sided
            program["alpha_mask"].value = material.alpha_mode == "MASK"
            program["alpha_cutoff"].value = material.alpha_cutoff
            program["has_texture"].value = batch.texture is not None
            if batch.texture is not None:
                source = batch.texture
                texture_key = (
                    source.digest,
                    source.min_filter,
                    source.mag_filter,
                    source.wrap_s,
                    source.wrap_t,
                )
                if texture_key not in self.textures:
                    height, width = source.rgba.shape[:2]
                    texture = self.context.texture((width, height), 4, source.rgba.tobytes())
                    if source.min_filter >= 9984:
                        texture.build_mipmaps()
                    texture.filter = (source.min_filter, source.mag_filter)
                    texture.repeat_x = source.wrap_s == 10497
                    texture.repeat_y = source.wrap_t == 10497
                    self.textures[texture_key] = texture
                    if len(self.textures) > 8:
                        _, old = self.textures.popitem(last=False)
                        old.release()
                self.textures.move_to_end(texture_key)
                self.textures[texture_key].use(0)
                program["mirror_wrap"].value = (
                    int(source.wrap_s == 33648),
                    int(source.wrap_t == 33648),
                )
            else:
                program["mirror_wrap"].value = (0, 0)
            values = np.concatenate(
                (batch.triangles, batch.normals, batch.uv, batch.colors), axis=2
            ).astype(np.float32)
            payload = values.tobytes()
            if len(payload) > self.model_buffer.size:
                self.model_buffer.orphan(len(payload))
            self.model_buffer.write(payload)
            self.model_array.render(mode=self.mode, vertices=len(batch.triangles) * 3)
        self._composite(target, image)


def draw_depth(image, triangles, colors) -> None:
    renderer = getattr(_LOCAL, "renderer", None)
    if renderer is None:
        renderer = _LOCAL.renderer = DepthRenderer()
    renderer.draw(image, triangles, colors)


def draw_textured(image, batches: list[TexturedBatch]) -> None:
    renderer = getattr(_LOCAL, "renderer", None)
    if renderer is None:
        renderer = _LOCAL.renderer = DepthRenderer()
    renderer.draw_textured(image, batches)


def clear_model_textures() -> None:
    renderer = getattr(_LOCAL, "renderer", None)
    if renderer is not None:
        renderer.clear_textures()


def renderer_info() -> dict[str, str]:
    renderer = getattr(_LOCAL, "renderer", None)
    if renderer is None:
        return {"status": "not-initialized"}
    info = renderer.context.info
    return {name: str(info[name]) for name in ("GL_VENDOR", "GL_RENDERER", "GL_VERSION")}


def close_renderer() -> None:
    renderer = getattr(_LOCAL, "renderer", None)
    if renderer is not None:
        renderer.close()
        del _LOCAL.renderer
