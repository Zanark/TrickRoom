import hashlib

import numpy as np

from trickroom.assets.types import Material, Texture
from trickroom.raster import TexturedBatch, draw_textured


def quad(texture=None, material=None):
    triangles = np.array(
        (((8, 8, 0), (8, 56, 0), (56, 56, 0)), ((8, 8, 0), (56, 56, 0), (56, 8, 0))), float
    )
    uv = np.array((((0, 0), (0, 1), (1, 1)), ((0, 0), (1, 1), (1, 0))), float)
    normals = np.tile((0, 0, 1), (2, 3, 1))
    return TexturedBatch(
        triangles,
        normals,
        uv,
        np.ones((2, 3, 4)),
        material or Material("Unlit", unlit=True, double_sided=True),
        texture,
    )


def test_texture_uv_origin_and_srgb_are_preserved():
    rgba = np.array(
        (((255, 0, 0, 255), (0, 255, 0, 255)), ((0, 0, 255, 255), (128, 128, 128, 255))), np.uint8
    )
    texture = Texture(rgba, hashlib.sha256(rgba.tobytes()).hexdigest(), 9728, 9728, 33071, 33071)
    image = np.full((64, 64, 3), 17, np.uint8)
    draw_textured(image, [quad(texture)])
    assert tuple(image[16, 16]) == (0, 0, 255)
    assert tuple(image[16, 48]) == (0, 255, 0)
    assert tuple(image[48, 16]) == (255, 0, 0)
    assert np.max(abs(image[48, 48].astype(int) - 128)) <= 1


def test_alpha_mask_discards_pixels_without_writing_depth_or_camera_data():
    rgba = np.array(
        (((255, 0, 0, 0), (0, 255, 0, 255)), ((0, 0, 255, 255), (255, 255, 255, 255))), np.uint8
    )
    texture = Texture(rgba, hashlib.sha256(rgba.tobytes()).hexdigest(), 9728, 9728, 33071, 33071)
    material = Material(
        "Cutout", alpha_mode="MASK", alpha_cutoff=0.5, unlit=True, double_sided=True
    )
    image = np.full((64, 64, 3), 31, np.uint8)
    draw_textured(image, [quad(texture, material)])
    assert tuple(image[16, 16]) == (31, 31, 31)
    assert tuple(image[16, 48]) == (0, 255, 0)


def test_opaque_material_ignores_texture_alpha():
    texture = Texture(np.array([[[255, 0, 0, 0]]], np.uint8), "opaque-red", 9728, 9728)
    image = np.zeros((64, 64, 3), np.uint8)
    draw_textured(image, [quad(texture)])
    assert tuple(image[32, 32]) == (0, 0, 255)
