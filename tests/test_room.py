from dataclasses import replace

import numpy as np
import pytest

from trickroom.avatar import Footprint, character_mesh
from trickroom.demo import demo_observation
from trickroom.render import Renderer, StageOptions
from trickroom.room import RoomProjection, draw_foot_shadows, room_background


@pytest.mark.parametrize("x,y", [(-3, 0), (3, 3.6), (-1.2, 3.6), (1.2, 0)])
def test_depth_grid_lines_converge_to_one_vanishing_point(x, y):
    camera = RoomProjection.for_stage(640, 480, True)
    points = camera.project(((x, y, 2), (x, y, 7)))
    cross = np.linalg.det(
        np.array(
            (
                (*points[0], 1),
                (*points[1], 1),
                (*camera.center, 1),
            )
        )
    )
    assert abs(cross) < 1e-8
    assert np.linalg.norm(points[1] - camera.center) < np.linalg.norm(points[0] - camera.center)


def test_equal_world_distances_foreshorten_consistently():
    camera = RoomProjection.for_stage(640, 480, True)
    near = camera.project(((-0.3, 0, 3), (0.3, 0, 3)))
    far = camera.project(((-0.3, 0, 6), (0.3, 0, 6)))
    assert np.linalg.norm(near[1] - near[0]) == pytest.approx(
        np.linalg.norm(far[1] - far[0]) * 2,
    )
    rows = camera.project(((0, 0, 3), (0, 0, 4), (0, 0, 5), (0, 0, 6)))[:, 1]
    assert rows[0] - rows[1] > rows[1] - rows[2] > rows[2] - rows[3] > 0


def test_floor_inverse_matches_the_pinhole_projection():
    camera = RoomProjection.for_stage(640, 480, False)
    world = np.array((0.45, 0, 4))
    pixel = camera.project((world,))[0]
    assert camera.floor_point(tuple(pixel)) == pytest.approx(world)
    assert camera.floor_point((camera.center[0], camera.center[1] - 1)) is None
    assert camera.floor_point((camera.center[0], 0)) is None
    assert camera.floor_point((camera.width + 1, camera.height - 10)) is None
    assert camera.floor_point((float("nan"), 400)) is None


@pytest.mark.parametrize("points", [((0, 0, 0),), ((0, 0, -1),), ((float("inf"), 0, 1),)])
def test_invalid_projection_is_explicit(points):
    with pytest.raises(ValueError):
        RoomProjection.for_stage(640, 480, True).project(points)


@pytest.mark.parametrize("size", [(640, 480), (640, 853), (1280, 240)])
def test_five_surface_background_fits_stage_and_keeps_cache_immutable(size):
    width, height = size
    room = room_background(width, height, True)
    assert room.pixels.shape == (height, width, 3)
    assert room.floor_mask.shape == (height, width)
    assert not room.pixels.flags.writeable and not room.floor_mask.flags.writeable
    assert not np.any(room.floor_mask[: room.projection.top])
    assert not np.any(room.floor_mask[room.projection.bottom :])
    camera = room.projection
    back_floor_y = camera.project(((0, 0, camera.back),))[0, 1]
    back_width = min(width, camera.focal * camera.half_width * 2 / camera.back)
    minimum_floor_area = back_width * max(0, camera.bottom - np.ceil(back_floor_y) - 2)
    assert np.count_nonzero(room.floor_mask) >= minimum_floor_area
    assert room.floor_mask[camera.bottom - 1, width // 2] == 255
    assert len(np.unique(room.pixels.reshape(-1, 3), axis=0)) > 30
    assert room_background(width, height, True) is room


def test_background_cache_is_bounded():
    for width in range(320, 326):
        room_background(width, 240, False)
    assert room_background.cache_info().currsize == 4


def test_room_uses_dark_green_panels_and_vivid_green_wireframe():
    room = room_background(640, 480, False)
    pixels = room.pixels.astype(int)
    green, red, blue = pixels[:, :, 1], pixels[:, :, 2], pixels[:, :, 0]
    lines = (green > 80) & (green > red * 2) & (green > blue * 1.5)
    assert lines.sum() > 1000
    assert np.median(green) < 45 and np.median(red) < 25 and np.median(blue) < 35
    assert np.median(green) > np.median(red)


def test_new_theme_has_no_calibration_cross_in_tile_centers():
    room = room_background(640, 480, False)
    x, y = np.rint(room.projection.project(((-2.7, 0.3, room.projection.back),))[0]).astype(int)
    assert room.pixels[y - 1 : y + 2, x - 1 : x + 2, 1].max() < 60


def test_shadow_is_confined_to_floor_and_can_only_darken():
    room = room_background(640, 480, True)
    image = room.pixels.copy()
    feet = [Footprint((300, 410), 30), Footprint((330, 410), 30)]
    assert draw_foot_shadows(image, room, feet) == 2
    changed = np.any(image != room.pixels, axis=2)
    assert changed.sum() > 100
    assert not np.any(changed & (room.floor_mask == 0))
    assert np.all(image.astype(int) <= room.pixels.astype(int))
    assert np.array_equal(room.pixels, room_background(640, 480, True).pixels)
    reverse = room.pixels.copy()
    draw_foot_shadows(reverse, room, feet[::-1])
    assert np.array_equal(image, reverse)


def test_unavailable_or_nonfloor_feet_never_make_a_shadow():
    room = room_background(640, 480, True)
    image = room.pixels.copy()
    assert draw_foot_shadows(image, room, []) == 0
    assert draw_foot_shadows(image, room, [Footprint((320, 120), 30)]) == 0
    assert draw_foot_shadows(image, room, [Footprint((320, 400), float("nan"))]) == 0
    assert np.array_equal(image, room.pixels)


def test_footprint_collection_uses_only_actual_eligible_shoe_geometry():
    state = demo_observation(0, 10)
    positions = {
        i: np.array((p.x * 400, p.y * 480, -p.z * 400))
        for i, p in enumerate(state.joints)
        if p.usable()
    }
    footprints = []
    plain = character_mesh(positions, None, 104)
    collected = character_mesh(positions, None, 104, footprints=footprints)
    assert len(footprints) == 2
    assert all(f.width > 5 and np.isfinite(f.center).all() for f in footprints)
    assert np.array_equal(plain.vertices, collected.vertices)
    del positions[31]
    one = []
    character_mesh(positions, None, 104, footprints=one)
    assert len(one) == 1
    del positions[28]
    none = []
    character_mesh(positions, None, 104, footprints=none)
    assert none == []


def test_room_and_shadows_preserve_presentation_mirroring():
    renderer = Renderer()
    state = demo_observation(0.3, 10)
    options = StageOptions(mirror=False, hud=False, head_detail=False)
    normal = renderer.render(state, (640, 480), now=10, options=options)
    mirrored = renderer.render(state, (640, 480), now=10, options=replace(options, mirror=True))
    assert np.array_equal(normal[:, ::-1], mirrored)
    plain = renderer.render(state, (640, 480), now=10, options=replace(options, grid=False))
    assert np.count_nonzero(np.any(plain != normal, axis=2)) > 100_000
