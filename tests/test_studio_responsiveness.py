from concurrent.futures import Future
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from glb_helpers import FIXTURE

from trickroom.assets.gltf import load_asset
from trickroom.assets.retarget import AvatarInstance
from trickroom.camera import CaptureStatus, Source
from trickroom.demo import demo_observation
from trickroom.runtime import RuntimeStatus
from trickroom.studio import Studio


def scheduler(monkeypatch):
    app = Studio.__new__(Studio)
    app.root = Mock()
    app._closing = False
    app._view_due = dict.fromkeys(("preview", "output", "skeleton", "face", "input"), 0.0)
    app._output_window = Mock()
    app._output_window.winfo_exists.return_value = True
    app._debug_windows = {"skeleton": (Mock(), Mock())}
    app.rig_motion = Mock()
    app.rig_motion.get.return_value = True
    app.renderer = Mock()
    app.render_worker = Mock()
    app.render_worker.status.imported = True
    app._draw_pending = None
    app._render_commands = []
    app._displayed = {}
    clock = [100.0]
    monkeypatch.setattr("trickroom.studio.time.perf_counter", lambda: clock[0])

    def expensive(*_args):
        clock[0] += 0.08

    app._draw_avatar = Mock(side_effect=expensive)
    app._draw_debug = Mock(side_effect=expensive)
    return app, clock


def test_scheduler_renders_one_view_then_yields_even_when_drawing_overruns(monkeypatch):
    app, clock = scheduler(monkeypatch)
    for count in range(1, 4):
        app._render_tick()
        assert app._draw_avatar.call_count + app._draw_debug.call_count == count
        app.root.after.assert_called_with(8, app._render_tick)
        clock[0] += 0.008
    assert {item.args[0] for item in app._draw_avatar.call_args_list} == {"preview", "output"}
    app._draw_debug.assert_called_once()


def test_scheduler_excludes_closed_views_and_waits_for_next_due_view(monkeypatch):
    app, _clock = scheduler(monkeypatch)
    app._output_window.winfo_exists.return_value = False
    app._debug_windows.clear()
    app._view_due["preview"] = 100.25
    app._render_tick()
    app._draw_avatar.assert_not_called()
    app._draw_debug.assert_not_called()
    app.root.after.assert_called_once_with(250, app._render_tick)


def test_closing_stops_the_draw_scheduler(monkeypatch):
    app, _clock = scheduler(monkeypatch)
    app._closing = True
    app._render_tick()
    app.root.after.assert_not_called()
    app._draw_avatar.assert_not_called()
    app._draw_debug.assert_not_called()


def test_control_tick_does_not_render_any_view(monkeypatch):
    app, _clock = scheduler(monkeypatch)
    app._poll_model = Mock()
    app._disconnecting = False
    app._last_telemetry = 0
    app._update_playback = Mock()
    app._observation = Mock(return_value=None)
    app._update_telemetry = Mock()
    app._tick()
    app._update_playback.assert_called_once()
    app._update_telemetry.assert_called_once_with(None, 100)
    app.root.after.assert_called_once_with(16, app._tick)
    app._draw_avatar.assert_not_called()
    app._draw_debug.assert_not_called()


def test_control_failure_cannot_be_dropped_between_readiness_checks(monkeypatch):
    app, _clock = scheduler(monkeypatch)
    app._poll_model = Mock()
    app._disconnecting = False
    app._last_telemetry = 0
    app._update_playback = Mock()
    app._observation = Mock(return_value=None)
    app._update_telemetry = Mock()
    app._graphics_failed = Mock()
    future = Mock()
    future.done.side_effect = (False, True)
    future.result.side_effect = RuntimeError("queued control failed")
    app._render_commands = [future]
    app._tick()
    assert app._render_commands == [future]
    app._tick()
    app._graphics_failed.assert_called_once()


def test_each_draw_reads_current_input_and_never_uses_disconnecting_observations():
    app = Studio.__new__(Studio)
    app.demo = app._disconnecting = False
    app.runtime = SimpleNamespace(observation=object())
    assert app._observation(10) is app.runtime.observation
    app.runtime.observation = object()
    assert app._observation(10.1) is app.runtime.observation
    app._disconnecting = True
    assert app._observation(10.2) is None
    app.runtime = None
    assert app._observation(10.3) is None


def test_close_cancels_the_owned_render_callback_once(monkeypatch):
    app, _clock = scheduler(monkeypatch)
    app._render_tick_id = "render-after"
    app._clear_debug_frames = Mock()
    app.runtime = None
    app.close()
    app.close()
    app.root.after_cancel.assert_called_once_with("render-after")
    assert app._closing and app._render_tick_id is None
    app.render_worker.close.assert_called_once()


def pending_draw(monkeypatch, *, complete=True):
    app = Studio.__new__(Studio)
    app._closing = app._disconnecting = False
    app._render_epoch = 1
    app._displayed = {}
    app._debug_windows = {}
    app.preview = Mock()
    app.runtime = SimpleNamespace(
        camera=SimpleNamespace(
            source=Source("file", "fixture.avi"), status=CaptureStatus(generation=2)
        ),
        status=RuntimeStatus("RUNNING"),
    )
    state = replace(demo_observation(0, 100), generation=2, media_time=3)
    future = Future()
    if complete:
        future.set_result(object())
    app._draw_pending = (future, "preview", 1, app.runtime, 2, state, "RUNNING", 100, False)
    monkeypatch.setattr("trickroom.studio.time.perf_counter", lambda: 100.2)
    photo = Mock()
    monkeypatch.setattr("trickroom.studio.ImageTk.PhotoImage", photo)
    return app, state, future, photo


@pytest.mark.parametrize("change", ["epoch", "source", "seek", "error", "stale"])
def test_completed_old_render_never_reappears_after_revocation(monkeypatch, change):
    app, _state, _future, photo = pending_draw(monkeypatch)
    if change == "epoch":
        app._render_epoch += 1
    elif change == "source":
        app.runtime = None
    elif change == "seek":
        app.runtime.camera.status = CaptureStatus(generation=3)
    elif change == "error":
        app.runtime.status = RuntimeStatus("ERROR")
    else:
        monkeypatch.setattr("trickroom.studio.time.perf_counter", lambda: 101)
    assert app._publish_draw()
    photo.assert_not_called()


def test_inflight_render_does_not_suspend_displayed_frame_expiry(monkeypatch):
    app, state, future, _photo = pending_draw(monkeypatch, complete=False)
    app._displayed["preview"] = (app.runtime, 2, state, "RUNNING", False, 1)
    app._expire_displayed(101)
    app.preview.configure.assert_called_once_with(image="")
    assert not app._displayed and not future.done()


def test_only_explicitly_labelled_paused_replay_can_keep_an_old_display(monkeypatch):
    app, state, _future, _photo = pending_draw(monkeypatch)
    app.runtime.status = RuntimeStatus("PAUSED")
    app._displayed["preview"] = (app.runtime, 2, state, "PAUSED", False, 1)
    app._expire_displayed(101)
    app.preview.configure.assert_not_called()
    app.runtime.camera.source = Source("device", 0)
    app._expire_displayed(101)
    app.preview.configure.assert_called_once_with(image="")


def test_graphics_exception_and_timeout_enter_explicit_shutdown(monkeypatch):
    for error in (RuntimeError("draw failed"), None):
        app, _state, future, _photo = pending_draw(monkeypatch, complete=False)
        app._graphics_failed = Mock()
        if error is not None:
            future.set_exception(error)
        else:
            monkeypatch.setattr("trickroom.studio.time.perf_counter", lambda: 106)
        app._render_tick()
        app._graphics_failed.assert_called_once()


@pytest.mark.parametrize("kind", ["full", "cropped", "head-only", "no-face", "bind"])
def test_numeric_driver_masks_preserve_original_anatomical_visibility(kind):
    asset = load_asset(FIXTURE)
    instance = AvatarInstance(asset)
    state = demo_observation(0.7, 10, cropped=kind == "cropped")
    if kind == "head-only":
        state = replace(state, joints=(), world_joints=())
    elif kind == "no-face":
        state = replace(state, face=None)
    elif kind == "bind":
        instance.set_mode("bind", 10)
    evaluation = instance.evaluate(state, 10.04)
    for index, primitive in enumerate(asset.primitives):
        node = asset.nodes[primitive.node]
        if node.skin is None:
            roles = np.array([asset.driver_for_node[primitive.node]] * len(primitive.positions))
        else:
            skin = asset.skins[node.skin]
            dominant = primitive.joints[
                np.arange(len(primitive.positions)), np.argmax(primitive.weights, axis=1)
            ]
            roles = np.array([asset.driver_for_node[skin.joints[joint]] for joint in dominant])
        expected = np.isin(roles, list(evaluation.active))[primitive.indices].all(axis=1)
        assert np.array_equal(evaluation.visible[index], expected)
        head = instance.head_triangles(index)
        assert head is instance.head_triangles(index) and not head.flags.writeable
        assert np.array_equal(
            head,
            np.isin(roles, ("head", "eye_left", "eye_right"))[primitive.indices].all(axis=1),
        )
        for side in ("left", "right"):
            foot = instance.foot_vertices(index, side)
            assert foot is instance.foot_vertices(index, side) and not foot.flags.writeable
            assert np.array_equal(foot, np.isin(roles, (f"foot_{side}", f"toes_{side}")))
