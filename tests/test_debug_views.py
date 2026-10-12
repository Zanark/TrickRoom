import subprocess
import sys
import time
from dataclasses import replace

import numpy as np

from trickroom.camera import CapturedFrame, Source
from trickroom.debug_views import face_connections, face_mesh, raw_input, skeleton
from trickroom.demo import demo_observation
from trickroom.models import default_model_directory
from trickroom.render import Renderer, StageOptions
from trickroom.runtime import Runtime, RuntimeStatus
from trickroom.state import Point


def face_state():
    state = demo_observation(0, 10)
    points = tuple(
        Point(0.5 + 0.10 * np.cos(i * 0.57), 0.2 + 0.15 * np.sin(i * 0.57)) for i in range(478)
    )
    return replace(state, face=replace(state.face, landmarks=points))


def test_raw_preview_retention_is_opt_in_copied_and_cleared():
    runtime = Runtime(Source("device", 0), default_model_directory())
    pixels = np.full((20, 30, 3), 47, np.uint8)
    now = time.perf_counter()
    frame = CapturedFrame(1, now, pixels)
    state = demo_observation(0, now)
    runtime._publish(state, frame, RuntimeStatus("RUNNING"))
    assert runtime.input_preview is None
    runtime.enable_input_preview(True)
    runtime._publish(state, frame, RuntimeStatus("RUNNING"))
    observed, retained = runtime.debug_snapshot
    assert observed is state and retained.sequence == frame.sequence
    assert retained.image is not pixels and not retained.image.flags.writeable
    pixels[:] = 99
    assert np.all(retained.image == 47)
    runtime.enable_input_preview(False)
    assert runtime.input_preview is None
    runtime.enable_input_preview(True)
    runtime._publish(state, frame, RuntimeStatus("RUNNING"))
    runtime.stop()
    assert runtime.input_preview is None and runtime.debug_snapshot == (None, None)


def test_stale_raw_copy_is_released_even_without_another_frame(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("trickroom.runtime.time.perf_counter", lambda: clock[0])
    runtime = Runtime(Source("device", 0), default_model_directory())
    runtime.enable_input_preview(True)
    runtime._publish(
        demo_observation(0, 10),
        CapturedFrame(1, 10, np.zeros((20, 30, 3), np.uint8)),
        RuntimeStatus("RUNNING"),
    )
    assert runtime.input_preview is not None
    clock[0] = 10.7
    assert runtime.debug_snapshot[1] is None
    assert runtime._input_preview is None


def test_raw_debug_preserves_unmirrored_pixels_without_mutating_input():
    pixels = np.zeros((100, 200, 3), np.uint8)
    pixels[:, :100] = (20, 40, 200)
    pixels[:, 100:] = (200, 40, 20)
    copy = pixels.copy()
    frame = CapturedFrame(1, 10, pixels)
    output = raw_input(frame, (640, 480), 10)
    assert tuple(output[240, 120]) == (20, 40, 200)
    assert tuple(output[240, 520]) == (200, 40, 20)
    assert np.array_equal(pixels, copy)
    stale = raw_input(frame, (640, 480), 11)
    assert not np.any(np.all(stale == (20, 40, 200), axis=2))


def test_skeleton_is_points_and_lines_on_black_not_a_rendered_avatar():
    state = demo_observation(0, 10)
    output = skeleton(state, (640, 480), 10)
    assert np.mean(np.all(output == 0, axis=2)) > 0.93
    assert np.count_nonzero(output) > 500
    expired = skeleton(state, (640, 480), 11)
    assert np.array_equal(expired, skeleton(None, (640, 480), 11))


def test_face_uses_real_mesh_connection_indices_and_preserves_black_background():
    edges, contours, irises = face_connections()
    assert len(edges) > 1000 and len(contours) > 100 and len(irises) == 8
    assert max(max(pair) for pair in (*edges, *contours, *irises)) < 478
    output = face_mesh(face_state(), (640, 480), 10)
    assert output.shape == (480, 640, 3)
    assert np.all(output[50:100, :20] == 0)
    assert np.count_nonzero(output[100:400, 100:540]) > 1000


def test_synthetic_demo_face_does_not_fake_detected_face_points():
    state = demo_observation(0, 10)
    assert not state.face.landmarks
    assert np.array_equal(face_mesh(state, (640, 480), 10), face_mesh(None, (640, 480), 10))


def test_debug_rendering_cannot_change_clean_avatar_output():
    renderer = Renderer()
    state = face_state()
    options = StageOptions(head_detail=False, hud=False)
    before = renderer.render(state, now=10, options=options)
    raw_input(CapturedFrame(1, 10, np.full((40, 60, 3), 213, np.uint8)), (640, 480), 10)
    skeleton(state, (640, 480), 10)
    face_mesh(state, (640, 480), 10)
    after = renderer.render(state, now=10, options=options)
    assert np.array_equal(before, after)


def test_face_debug_does_not_import_native_mediapipe_in_the_owner_process():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from trickroom.debug_views import face_connections; "
            "assert len(face_connections()[0]) > 1000; assert 'mediapipe' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
