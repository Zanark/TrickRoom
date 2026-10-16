"""Studio ghost-camera controls: WASD, mouse look and pointer capture."""

from __future__ import annotations

import pytest

from trickroom.ghostcam import GhostCamera
from trickroom.studio import Studio

tk = pytest.importorskip("tkinter")


class Flag:
    """Stands in for a Tk variable without needing a root window."""

    def __init__(self, value=False):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def rig(enabled=True, speed=2.5):
    studio = Studio.__new__(Studio)
    studio.ghost_camera = GhostCamera()
    studio.ghost_enabled = Flag(enabled)
    studio.ghost_speed = Flag(speed)
    studio.ghost_info = Flag("")
    studio._ghost_keys = set()
    studio._ghost_look = [0.0, 0.0]
    studio._ghost_pointer = None
    studio._ghost_captured = False
    studio._ghost_clock = None
    return studio


def fly(studio, seconds=1.0, step=1 / 60):
    now = 0.0
    studio._advance_ghost_camera(now)
    while now < seconds:
        now += step
        studio._advance_ghost_camera(now)
    return studio.ghost_camera


@pytest.mark.parametrize(
    "key,axis,sign",
    [("w", 2, 1), ("s", 2, -1), ("d", 0, 1), ("a", 0, -1), ("e", 1, 1), ("q", 1, -1)],
)
def test_each_movement_key_moves_the_expected_way(key, axis, sign):
    """Measured as displacement: the camera starts at eye height, not the origin."""
    studio = rig()
    start = studio.ghost_camera.position.copy()
    studio._ghost_keys = {key}
    camera = fly(studio, 0.5)
    moved = camera.position - start
    assert moved[axis] * sign > 0.05
    for other in {0, 1, 2} - {axis}:
        assert abs(moved[other]) < 1e-9


def test_space_and_control_also_change_height():
    start = GhostCamera().position[1]
    up = rig()
    up._ghost_keys = {"space"}
    assert fly(up, 0.5).position[1] > start + 0.05
    down = rig()
    down._ghost_keys = {"control_l"}
    assert fly(down, 0.5).position[1] < start - 0.05


def test_mouse_look_survives_a_zero_length_frame():
    """A pointer delta is a displacement; a stalled frame must not swallow it."""
    studio = rig()
    studio._ghost_captured = True
    studio._ghost_look = [120.0, 0.0]
    studio._advance_ghost_camera(0.0)
    assert studio.ghost_camera.yaw > 1.0


def test_opposite_keys_cancel():
    studio = rig()
    studio._ghost_keys = {"w", "s", "a", "d"}
    camera = fly(studio, 0.5)
    assert abs(camera.position[0]) < 1e-9
    assert abs(camera.position[2]) < 1e-9


def test_shift_is_precision_not_sprint():
    fast = rig()
    fast._ghost_keys = {"w"}
    slow = rig()
    slow._ghost_keys = {"w", "shift_l"}
    assert fly(slow, 1.0).position[2] < fly(fast, 1.0).position[2]


def test_mouse_look_turns_the_camera():
    studio = rig()
    studio._ghost_captured = True
    studio._ghost_look = [120.0, 0.0]
    camera = fly(studio, 1 / 60, 1 / 60)
    assert camera.yaw > 1.0


def test_mouse_deltas_are_consumed_once():
    studio = rig()
    studio._ghost_captured = True
    studio._ghost_look = [120.0, 0.0]
    studio._advance_ghost_camera(0.0)
    studio._advance_ghost_camera(1 / 60)
    first = studio.ghost_camera.yaw
    studio._advance_ghost_camera(2 / 60)
    assert studio.ghost_camera.yaw == pytest.approx(first)


def test_disabled_camera_ignores_input_entirely():
    studio = rig(enabled=False)
    studio._ghost_keys = {"w"}
    studio._ghost_look = [200.0, 0.0]
    camera = fly(studio, 1.0)
    assert camera.position[2] == pytest.approx(0.0)
    assert camera.yaw == pytest.approx(0.0)


def test_release_clears_held_input_so_the_camera_stops():
    studio = rig()
    studio._ghost_captured = True
    studio._ghost_keys = {"w"}
    studio._ghost_look = [50.0, 0.0]
    Studio.release_pointer(studio)
    assert studio._ghost_keys == set()
    assert studio._ghost_look == [0.0, 0.0]
    assert not studio._ghost_captured


def test_speed_control_scales_travel():
    slow = rig(speed=1.0)
    slow._ghost_keys = {"w"}
    fast = rig(speed=6.0)
    fast._ghost_keys = {"w"}
    assert fly(fast, 1.0).position[2] > fly(slow, 1.0).position[2] * 2


def test_pose_readout_reports_position_and_capture_state():
    studio = rig()
    studio._ghost_captured = True
    studio._ghost_keys = {"w"}
    fly(studio, 0.3)
    text = studio.ghost_info.get()
    assert "yaw" in text and "fov" in text
    assert "MOUSE CAPTURED" in text


def test_tick_step_is_inert_without_camera_state():
    """Harnesses build a Studio with only the fields they need."""
    bare = Studio.__new__(Studio)
    Studio._advance_ghost_camera(bare, 1.0)


def test_key_release_always_clears_even_when_disabled():
    studio = rig(enabled=False)
    studio._ghost_keys = {"w"}
    Studio._ghost_key_release(studio, type("E", (), {"keysym": "W"})())
    assert "w" not in studio._ghost_keys
