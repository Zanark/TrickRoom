from dataclasses import replace

import numpy as np
import pytest

from trickroom.avatar import (
    PALETTE,
    HeadPlacement,
    character_mesh,
    garment,
    hair_geometry,
    head_geometry,
    headphones_geometry,
    posed_head,
)
from trickroom.demo import demo_observation
from trickroom.raster import DepthRenderer, close_renderer, draw_depth
from trickroom.render import Renderer, StageOptions, Viewport, _head_anchor


def positions(state):
    return {
        i: np.array((p.x * 900, p.y * 1200, -p.z * 900))
        for i, p in enumerate(state.joints)
        if p.usable()
    }


def test_reference_palette_is_clothing_not_debug_colors():
    assert max(PALETTE["hoodie"]) < 70
    assert PALETTE["cargo"][1] > PALETTE["cargo"][2] > PALETTE["cargo"][0]
    assert PALETTE["skin"][2] > PALETTE["skin"][0]
    assert min(PALETTE["headphones"]) > 120
    assert not StageOptions().outline and not StageOptions().skeleton


@pytest.mark.parametrize(
    "name",
    [
        "torso",
        "upper_sleeve",
        "lower_sleeve",
        "left_thigh",
        "right_thigh",
        "trouser_shin",
        "waist",
        "hand",
        "neck",
        "shoe",
    ],
)
def test_reference_parts_have_finite_three_dimensional_geometry(name):
    mesh = garment(name)
    assert len(mesh.triangles) > 10
    assert np.isfinite(mesh.vertices).all()
    assert mesh.triangles.min() >= 0 and mesh.triangles.max() < len(mesh.vertices)
    assert mesh.colors.dtype == np.uint8
    assert all(np.ptp(mesh.vertices, axis=0) > 0)
    assert garment(name) is mesh


def test_hood_and_cargo_details_are_not_front_only_painted_labels():
    torso = garment("torso")
    assert torso.vertices[:, 2].min() < -0.4
    assert torso.vertices[:, 2].max() > 0.27
    left, right = garment("left_thigh"), garment("right_thigh")
    assert left.vertices[:, 0].max() > 0.28
    assert right.vertices[:, 0].min() < -0.28
    assert left.vertices[:, 2].max() > 0.25


def test_hair_and_headphones_surround_the_head_in_depth():
    hair = hair_geometry()
    headphones = headphones_geometry()
    assert hair.vertices[:, 2].min() < -0.5 and hair.vertices[:, 2].max() > 0.6
    assert headphones.vertices[:, 0].min() < -0.9
    assert headphones.vertices[:, 0].max() > 0.9
    assert headphones.vertices[:, 1].min() < -0.9


def test_character_geometry_budget_and_missing_limb_gates():
    state = demo_observation(0, 10)
    placement = HeadPlacement((450, 240, 0), 190, 240, state.face)
    full = character_mesh(positions(state), placement, 234)
    cropped = character_mesh(positions(demo_observation(0, 10, cropped=True)), placement, 234)
    assert 2000 < len(full.triangles) < 8000
    assert len(cropped.triangles) < len(full.triangles) - 500
    assert len(character_mesh({}, None, 234).triangles) == 0
    with pytest.raises(ValueError, match="Unknown avatar part"):
        garment("unapproved_character")


def test_pose_only_head_does_not_shrink_to_the_old_mannequin():
    state = demo_observation(0, 10)
    view = Viewport(0, 0, 900, 1200)
    tracked = _head_anchor(state, view)
    fallback = _head_anchor(replace(state, face=None), view)
    assert 0.8 < fallback[1] / tracked[1] < 1.25
    assert 0.8 < fallback[2] / tracked[2] < 1.25
    assert np.linalg.norm(np.array(fallback[0]) - tracked[0]) < tracked[2] * 0.2


def test_cached_geometry_is_not_modified_by_pose_or_expressions():
    mesh = head_geometry()
    vertices, colors = mesh.vertices.copy(), mesh.colors.copy()
    state = demo_observation(1.5, 10)
    posed_head(HeadPlacement((100, 120, 20), 90, 110, state.face))
    Renderer().render(state, now=10)
    assert np.array_equal(mesh.vertices, vertices)
    assert np.array_equal(mesh.colors, colors)


def test_per_pixel_depth_handles_intersections_regardless_of_draw_order():
    triangles = np.array(
        (
            ((4, 4, 10), (60, 4, -10), (32, 60, 0)),
            ((4, 4, 0), (60, 4, 0), (32, 60, 0)),
        ),
        float,
    )
    colors = np.array(((0, 0, 220), (220, 0, 0)), np.uint8)
    for order in ([0, 1], [1, 0]):
        image = np.full((64, 64, 3), 17, np.uint8)
        draw_depth(image, triangles[order], colors[order])
        assert tuple(image[12, 12]) == (0, 0, 220)
        assert tuple(image[12, 51]) == (220, 0, 0)
        assert tuple(image[0, 0]) == (17, 17, 17)


def test_depth_target_cache_is_bounded_and_releases():
    close_renderer()
    renderer = DepthRenderer()
    try:
        triangles = np.array((((2, 2, 0), (22, 2, 0), (12, 22, 0)),), float)
        colors = np.array(((10, 80, 140),), np.uint8)
        for size in range(64, 70):
            renderer.draw(np.zeros((size, size, 3), np.uint8), triangles, colors)
        assert len(renderer.targets) == 4
    finally:
        renderer.close()


def test_missing_opengl_is_an_explicit_failure(monkeypatch):
    close_renderer()

    def unavailable(**_kwargs):
        raise OSError("Fixture graphics failure")

    monkeypatch.setattr("moderngl.create_standalone_context", unavailable)
    with pytest.raises(RuntimeError, match="OpenGL 3.3"):
        DepthRenderer()
