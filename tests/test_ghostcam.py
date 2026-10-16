"""Ghost camera: a view over the stage that never becomes part of it."""

from __future__ import annotations

import math

import numpy as np
import pytest

from trickroom.ghostcam import (
    ATTACHED,
    FREE,
    MAX_PITCH,
    CameraCommand,
    GhostCamera,
    basis,
    clamp_pitch,
    dolly_zoom,
    framing_distance,
    perspective,
    project_to_screen,
    view_matrix,
    wrap_yaw,
)
from trickroom.room import camera_room, room_background


def test_default_basis_looks_down_positive_z():
    forward, right, up = basis(0.0, 0.0)
    assert np.allclose(forward, (0, 0, 1))
    assert np.allclose(right, (1, 0, 0))
    assert np.allclose(up, (0, 1, 0))


@pytest.mark.parametrize("yaw", [-170.0, -90.0, 0.0, 45.0, 90.0, 179.0])
@pytest.mark.parametrize("pitch", [-89.0, -30.0, 0.0, 30.0, 89.0])
def test_basis_stays_orthonormal(yaw, pitch):
    forward, right, up = basis(yaw, pitch)
    for vector in (forward, right, up):
        assert np.linalg.norm(vector) == pytest.approx(1.0)
    assert np.dot(forward, right) == pytest.approx(0.0, abs=1e-9)
    assert np.dot(forward, up) == pytest.approx(0.0, abs=1e-9)
    assert np.dot(right, up) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("pitch,expected", [(120.0, 89.0), (-120.0, -89.0), (45.0, 45.0)])
def test_pitch_is_clamped_short_of_the_pole(pitch, expected):
    assert clamp_pitch(pitch) == pytest.approx(expected)


def test_pitch_clamp_keeps_yaw_recoverable():
    forward, _, _ = basis(30.0, MAX_PITCH)
    horizontal = math.hypot(forward[0], forward[2])
    assert horizontal > 0.017
    assert math.degrees(math.atan2(forward[0], forward[2])) == pytest.approx(30.0)


@pytest.mark.parametrize("yaw,expected", [(190.0, -170.0), (-190.0, 170.0), (540.0, -180.0)])
def test_yaw_wraps_to_shortest_arc_range(yaw, expected):
    """The range is half open, so the turning point reports -180, not +180."""
    assert wrap_yaw(yaw) == pytest.approx(expected)


def test_view_matrix_puts_the_camera_at_the_origin():
    camera = GhostCamera(position=(1.0, 2.0, 3.0))
    point = np.array((1.0, 2.0, 3.0, 1.0))
    assert np.allclose((camera.view() @ point)[:3], (0, 0, 0), atol=1e-9)


def test_view_matrix_puts_a_forward_point_on_the_view_axis():
    camera = GhostCamera(position=(0.0, 0.0, 0.0), yaw=0.0, pitch=0.0)
    seen = camera.view() @ np.array((0.0, 0.0, 5.0, 1.0))
    assert seen[2] == pytest.approx(5.0)
    assert seen[0] == pytest.approx(0.0, abs=1e-9)
    assert seen[1] == pytest.approx(0.0, abs=1e-9)


def test_view_rotation_is_orthonormal():
    matrix = view_matrix((2.0, 1.0, -4.0), 35.0, -20.0)
    rotation = matrix[:3, :3]
    assert np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-9)


def test_projection_maps_the_near_and_far_planes():
    matrix = perspective(60.0, 16 / 9, 0.1, 100.0)
    for depth, expected in ((0.1, -1.0), (100.0, 1.0)):
        clip = matrix @ np.array((0.0, 0.0, depth, 1.0))
        assert clip[2] / clip[3] == pytest.approx(expected)


def test_projection_narrows_horizontally_with_aspect():
    wide = perspective(60.0, 16 / 9, 0.1, 100.0)
    square = perspective(60.0, 1.0, 0.1, 100.0)
    assert wide[0, 0] < square[0, 0]
    assert wide[1, 1] == pytest.approx(square[1, 1])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fov_y": 10.0},
        {"fov_y": 170.0},
        {"aspect": 0.0},
        {"near": 0.0},
        {"near": 50.0},
    ],
)
def test_projection_rejects_unusable_parameters(kwargs):
    args = {"fov_y": 60.0, "aspect": 1.5, "near": 0.1, "far": 10.0} | kwargs
    with pytest.raises(ValueError):
        perspective(**args)


def test_framing_distance_matches_the_apparent_size_relation():
    distance = framing_distance(1.8, 60.0, 0.7)
    fraction = 1.8 / (2.0 * distance * math.tan(math.radians(60.0) / 2.0))
    assert fraction == pytest.approx(0.7)


def test_wider_field_of_view_needs_a_closer_camera():
    assert framing_distance(1.8, 90.0) < framing_distance(1.8, 40.0)


def test_dolly_zoom_holds_subject_size_constant():
    """Moving closer needs a wider angle to keep the subject the same size."""
    near_fov = dolly_zoom(4.0, 50.0, 2.0)
    before = 1.8 / (2.0 * 4.0 * math.tan(math.radians(50.0) / 2.0))
    after = 1.8 / (2.0 * 2.0 * math.tan(math.radians(near_fov) / 2.0))
    assert after == pytest.approx(before)
    assert near_fov > 50.0


def test_dolly_zoom_narrows_when_pulling_back():
    far_fov = dolly_zoom(2.0, 80.0, 4.0)
    assert far_fov < 80.0
    before = 1.8 / (2.0 * 2.0 * math.tan(math.radians(80.0) / 2.0))
    after = 1.8 / (2.0 * 4.0 * math.tan(math.radians(far_fov) / 2.0))
    assert after == pytest.approx(before)


def test_movement_is_frame_rate_independent():
    def travel(step, steps):
        camera = GhostCamera(position=(0.0, 1.0, 0.0))
        for _ in range(steps):
            camera.update(CameraCommand(forward=1.0), step)
        return camera.position[2]

    coarse = travel(1 / 15, 15)
    fine = travel(1 / 120, 120)
    # Analytic integration makes this exact, not merely close.
    assert coarse == pytest.approx(fine, rel=1e-9)


def test_mouse_look_does_not_scale_with_frame_time():
    slow, fast = GhostCamera(), GhostCamera()
    slow.update(CameraCommand(yaw_delta=100.0), 1 / 15)
    fast.update(CameraCommand(yaw_delta=100.0), 1 / 240)
    assert slow.yaw == pytest.approx(fast.yaw)


def test_a_long_frame_does_not_reverse_velocity():
    camera = GhostCamera()
    camera.update(CameraCommand(forward=1.0), 0.5)
    assert camera.velocity[2] > 0
    assert np.linalg.norm(camera.velocity) <= camera.speed + 1e-9


def test_speed_is_capped_and_diagonals_keep_their_direction():
    camera = GhostCamera()
    for _ in range(400):
        camera.update(CameraCommand(forward=1.0, side=1.0), 1 / 60)
    assert np.linalg.norm(camera.velocity) <= camera.speed + 1e-6
    assert camera.velocity[0] == pytest.approx(camera.velocity[2], rel=1e-6)


def test_slow_modifier_halves_speed_for_precision():
    full, slow = GhostCamera(), GhostCamera()
    for _ in range(400):
        full.update(CameraCommand(forward=1.0), 1 / 60)
        slow.update(CameraCommand(forward=1.0, slow=True), 1 / 60)
    assert np.linalg.norm(slow.velocity) == pytest.approx(
        np.linalg.norm(full.velocity) / 2, rel=1e-3
    )


def test_vertical_input_is_world_up_not_view_relative():
    camera = GhostCamera(position=(0.0, 1.0, 0.0), pitch=-45.0)
    for _ in range(200):
        camera.update(CameraCommand(up=1.0), 1 / 60)
    assert camera.position[1] > 1.0
    assert camera.position[0] == pytest.approx(0.0, abs=1e-9)
    assert camera.position[2] == pytest.approx(0.0, abs=1e-9)


def test_flying_forward_while_pitched_changes_height():
    camera = GhostCamera(position=(0.0, 2.0, 0.0), pitch=-30.0)
    for _ in range(120):
        camera.update(CameraCommand(forward=1.0), 1 / 60)
    assert camera.position[1] < 2.0
    assert camera.position[2] > 0.0


def test_ghost_movement_ignores_gravity_and_geometry():
    camera = GhostCamera(position=(0.0, 1.5, 0.0))
    for _ in range(300):
        camera.update(CameraCommand(), 1 / 60)
    assert camera.position[1] == pytest.approx(1.5)


def test_attached_mode_does_not_fly():
    camera = GhostCamera(position=(0.0, 1.5, 0.0))
    camera.set_mode(ATTACHED)
    camera.update(CameraCommand(forward=1.0), 1 / 60)
    assert camera.position[2] == pytest.approx(0.0)
    assert camera.mode == ATTACHED


def test_attached_mode_still_allows_looking():
    camera = GhostCamera()
    camera.set_mode(ATTACHED)
    camera.update(CameraCommand(yaw_delta=50.0), 1 / 60)
    assert camera.yaw != pytest.approx(0.0)


def test_aim_at_points_the_camera_at_a_target():
    camera = GhostCamera(position=(0.0, 1.6, 0.0))
    camera.aim_at((2.0, 1.6, 2.0))
    assert camera.yaw == pytest.approx(45.0)
    assert camera.pitch == pytest.approx(0.0, abs=1e-9)


def test_aim_at_with_distance_pulls_back_to_frame_the_subject():
    camera = GhostCamera(position=(0.0, 1.6, 0.0), yaw=0.0)
    camera.aim_at((0.0, 1.6, 5.0), distance=3.0)
    assert camera.position[2] == pytest.approx(2.0)
    assert camera.yaw == pytest.approx(0.0)


def test_go_to_and_pose_round_trip_a_stored_shot():
    camera = GhostCamera()
    camera.go_to((1.0, 2.0, -3.0), 200.0, 120.0)
    pose = camera.pose()
    assert pose["position"] == [1.0, 2.0, -3.0]
    assert pose["yaw"] == pytest.approx(-160.0)
    assert pose["pitch"] == pytest.approx(89.0)
    assert pose["mode"] == FREE


def test_reset_returns_to_the_starting_shot():
    camera = GhostCamera(position=(0.0, 1.65, -2.0), yaw=10.0)
    camera.update(CameraCommand(forward=1.0, yaw_delta=300.0), 0.2)
    camera.set_mode(ATTACHED)
    camera.reset()
    assert camera.position[2] == pytest.approx(-2.0)
    assert camera.yaw == pytest.approx(10.0)
    assert camera.mode == FREE
    assert np.allclose(camera.velocity, 0)


@pytest.mark.parametrize("mode", ["noclip", "", "FREE", None])
def test_unknown_modes_are_rejected(mode):
    with pytest.raises(ValueError):
        GhostCamera().set_mode(mode)


@pytest.mark.parametrize(
    "kwargs", [{"forward": 2.0}, {"side": -3.0}, {"up": float("nan")}, {"yaw_delta": float("inf")}]
)
def test_commands_reject_unusable_axes(kwargs):
    with pytest.raises(ValueError):
        CameraCommand(**kwargs)


@pytest.mark.parametrize("dt", [-1.0, float("nan")])
def test_update_rejects_unusable_frame_times(dt):
    with pytest.raises(ValueError):
        GhostCamera().update(CameraCommand(), dt)


def test_zero_frame_time_is_a_no_op():
    camera = GhostCamera()
    camera.update(CameraCommand(forward=1.0), 0.0)
    assert np.allclose(camera.velocity, 0)


def test_projection_centres_a_point_straight_ahead():
    camera = GhostCamera(position=(0.0, 1.0, 0.0))
    screen, valid = project_to_screen([(0.0, 1.0, 4.0)], camera, 640, 480)
    assert valid[0]
    assert screen[0, 0] == pytest.approx(320.0)
    assert screen[0, 1] == pytest.approx(240.0)
    assert screen[0, 2] == pytest.approx(4.0)


def test_projection_reports_points_behind_the_camera_as_invalid():
    camera = GhostCamera(position=(0.0, 1.0, 0.0))
    _, valid = project_to_screen([(0.0, 1.0, -4.0), (0.0, 1.0, 4.0)], camera, 640, 480)
    assert not valid[0]
    assert valid[1]


def test_projection_shrinks_with_distance():
    camera = GhostCamera(position=(0.0, 1.0, 0.0))
    near, _ = project_to_screen([(0.5, 1.0, 2.0)], camera, 640, 480)
    far, _ = project_to_screen([(0.5, 1.0, 8.0)], camera, 640, 480)
    assert abs(near[0, 0] - 320.0) > abs(far[0, 0] - 320.0) * 3.5


def test_projection_puts_higher_world_points_higher_on_screen():
    camera = GhostCamera(position=(0.0, 1.0, 0.0))
    screen, _ = project_to_screen([(0.0, 2.0, 4.0), (0.0, 0.0, 4.0)], camera, 640, 480)
    assert screen[0, 1] < screen[1, 1]


def test_turning_the_camera_moves_a_fixed_point_the_other_way():
    point = [(0.0, 1.0, 4.0)]
    straight, _ = project_to_screen(point, GhostCamera(position=(0.0, 1.0, 0.0)), 640, 480)
    turned, _ = project_to_screen(point, GhostCamera(position=(0.0, 1.0, 0.0), yaw=20.0), 640, 480)
    assert turned[0, 0] < straight[0, 0]


def test_projection_rejects_an_unusable_viewport():
    with pytest.raises(ValueError):
        project_to_screen([(0.0, 0.0, 1.0)], GhostCamera(), 0, 480)


def test_camera_never_touches_observations():
    """The camera is a view. It holds no pose data and no tracking state."""
    camera = GhostCamera()
    attributes = set(vars(camera))
    assert not attributes & {"state", "observation", "joints", "asset", "runtime"}


def test_moving_the_camera_changes_the_room():
    front = camera_room(GhostCamera(position=(0.0, 1.65, 0.0)), 320, 240)
    offset = camera_room(GhostCamera(position=(2.0, 1.65, 0.0), yaw=-25.0), 320, 240)
    assert not np.array_equal(front.pixels, offset.pixels)
    assert front.pixels.any() and offset.pixels.any()


def test_camera_room_leaves_the_fixed_stage_untouched():
    """The original stage projection must keep working for the normal view."""
    before = room_background(320, 240).pixels.copy()
    camera_room(GhostCamera(position=(1.0, 2.0, 1.0), yaw=40.0), 320, 240)
    assert np.array_equal(room_background(320, 240).pixels, before)


def test_camera_room_pixels_are_read_only():
    room = camera_room(GhostCamera(), 320, 240)
    assert not room.pixels.flags.writeable
    assert not room.floor_mask.flags.writeable


def test_camera_room_survives_looking_away_from_the_room():
    """Most of the room falls behind the camera; it must not raise."""
    room = camera_room(GhostCamera(position=(0.0, 1.65, 7.0), yaw=180.0), 320, 240)
    assert room.pixels.shape == (240, 320, 3)
