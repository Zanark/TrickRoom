import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, call

import numpy as np
import pytest

from trickroom import debug_views
from trickroom.camera import CaptureStatus, Source
from trickroom.demo import demo_observation
from trickroom.render import Renderer, StageOptions
from trickroom.runtime import RuntimeStatus
from trickroom.studio import Studio, format_replay_time


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


@pytest.fixture
def studio():
    app = Studio.__new__(Studio)
    app._closing = app._disconnecting = app.demo = False
    app._timeline_visible = app._scrubbing = False
    app._playback_config = None
    app._pending_seek = app._requested_paused = None
    app.playback_position = Variable(0.0)
    app.playback_time = Variable("")
    app.playback_bar, app.playback_button, app.playback_slider = Mock(), Mock(), Mock()
    app.playback_slider.instate.return_value = False
    app.renderer = Mock()
    app._render_command = lambda action: action()
    app.render_worker = Mock()
    app.renderer.face_response.collecting = None
    app._debug_photos = {"old": Mock()}
    app._debug_windows = {"skeleton": (Mock(), Mock())}
    app.message = Variable("")
    app.runtime = Mock(
        alive=True,
        status=RuntimeStatus("RUNNING"),
        camera=SimpleNamespace(
            source=Source("file", "synthetic.avi"),
            status=CaptureStatus("STREAMING", duration_seconds=73.44, position_seconds=10),
        ),
        observation=replace(demo_observation(0, 10), media_time=9.5),
    )
    return app


@pytest.mark.parametrize(
    "seconds,label",
    [(0, "00:00"), (73.44, "01:13"), (3661, "1:01:01"), (-1, "--:--"), (float("nan"), "--:--")],
)
def test_media_time_formatting(seconds, label):
    assert format_replay_time(seconds) == label


def test_timeline_shows_observed_position_and_never_fights_mouse_scrubbing(studio):
    studio._update_playback()
    studio.playback_bar.grid.assert_called_once()
    assert studio.playback_position.get() == 9.5
    assert studio.playback_time.get() == "00:09 / 01:13"
    studio.playback_slider.get.return_value = 32.5
    assert studio._drag_playback(SimpleNamespace(x=100, y=10)) == "break"
    studio._update_playback()
    assert studio.playback_position.get() == 32.5
    assert studio.playback_time.get() == "00:32 / 01:13"
    studio.runtime.seek.assert_not_called()
    studio._commit_seek()
    studio.runtime.seek.assert_called_once_with(32.5)
    studio.renderer.reset_motion.assert_called_once_with(preserve_face_calibration=True)
    assert studio._debug_photos == {}
    studio._debug_windows["skeleton"][1].configure.assert_called_once_with(image="")
    studio._commit_seek()
    studio.runtime.seek.assert_called_once()


@pytest.mark.parametrize("mode", ["demo", "live", "disconnected", "stopping"])
def test_timeline_is_hidden_outside_recorded_playback(studio, mode):
    studio._update_playback()
    if mode == "demo":
        studio.demo = True
    elif mode == "live":
        studio.runtime.camera.source = Source("device", 0)
    elif mode == "disconnected":
        studio.runtime = None
    else:
        studio._disconnecting = True
    studio._update_playback()
    assert not studio._timeline_visible
    studio.playback_bar.grid_remove.assert_called_once()


@pytest.mark.parametrize("key,position", [("Left", 0), ("Right", 1.5), ("Home", 0), ("End", 73.44)])
def test_keyboard_seeks_commit_on_release_and_clamp_to_duration(studio, key, position):
    studio.playback_position.set(0.5)
    studio._step_playback(SimpleNamespace(keysym=key))
    assert studio.playback_position.get() == position
    studio.runtime.seek.assert_not_called()
    studio._commit_seek()
    studio.runtime.seek.assert_called_once_with(position)


def test_focus_loss_cancels_an_uncommitted_scrub(studio):
    studio._step_playback(SimpleNamespace(keysym="Right"))
    studio._cancel_scrub()
    studio._commit_seek()
    studio.runtime.seek.assert_not_called()
    studio._update_playback()
    assert studio.playback_position.get() == 9.5


def test_playback_poll_does_not_reconfigure_unchanged_widgets_while_dragging(studio):
    studio._update_playback()
    studio.playback_slider.get.return_value = 32.5
    studio._drag_playback(SimpleNamespace(x=100, y=10))
    studio._drag_playback(SimpleNamespace(x=110, y=10))
    studio._update_playback()
    studio._update_playback()
    studio.playback_button.configure.assert_called_once()
    studio.playback_slider.configure.assert_called_once()
    studio.playback_slider.state.assert_called_once()
    studio.playback_slider.focus_set.assert_called_once()
    studio.runtime.seek.assert_not_called()


def test_pause_intent_survives_delayed_acknowledgement_and_rapid_toggles(studio):
    studio.toggle_playback()
    studio._update_playback()
    studio.playback_button.configure.assert_called_with(text="Play", state="normal")
    studio.toggle_playback()
    assert studio.runtime.set_paused.call_args_list == [call(True), call(False)]


def test_seek_after_eof_restarts_the_same_recording_at_the_selected_position(studio):
    studio.runtime.alive = False
    studio.runtime.status = RuntimeStatus("ENDED")
    studio._start_source = Mock()
    studio.seek_playback(21)
    studio._start_source.assert_called_once_with(
        studio.runtime.camera.source,
        start_position=21,
        preserve_face_calibration=True,
    )


def test_seek_racing_eof_is_retried_after_owned_worker_cleanup(studio):
    studio._pending_seek = 12
    studio._requested_paused = True
    studio.runtime.observation = None
    studio.runtime.status = RuntimeStatus("ENDED")
    studio._start_source = Mock()
    studio._update_playback()
    studio._start_source.assert_not_called()
    studio.runtime.alive = False
    studio._update_playback()
    studio._start_source.assert_called_once_with(
        studio.runtime.camera.source,
        start_position=12,
        paused=True,
        preserve_face_calibration=True,
    )


def test_unknown_duration_disables_seeking_but_still_allows_pause(studio):
    studio.runtime.camera.status = CaptureStatus("STREAMING")
    studio._update_playback()
    studio.playback_slider.state.assert_called_with(["disabled"])
    studio.playback_button.configure.assert_called_with(text="Pause", state="normal")
    studio.seek_playback(0)
    studio.runtime.seek.assert_not_called()
    assert "timeline" in studio.message.get()


def test_failed_seek_is_reported_without_resetting_presentation(studio):
    studio.runtime.seek.side_effect = RuntimeError("The replay worker is not running.")
    studio.seek_playback(10)
    assert "not running" in studio.message.get()
    studio.renderer.reset_motion.assert_not_called()


def test_pause_cancels_only_an_in_progress_calibration(studio):
    studio.renderer.face_response.collecting = "neutral"
    studio.toggle_playback()
    studio.renderer.face_response.apply.assert_called_once()
    studio.renderer.face_response.reset.assert_not_called()
    assert "replay paused" in studio.renderer.face_response.message


def test_frozen_replay_is_labelled_without_rewriting_observations_or_exposing_controls(monkeypatch):
    state = replace(demo_observation(0, 10), media_time=2)
    original = state
    renderer = Renderer()
    renderer._body = Mock()
    labels = []
    monkeypatch.setattr(
        "trickroom.render._text", lambda image, label, *a, **k: labels.append(label)
    )
    options = StageOptions(grid=False, hud=False, head_detail=False)
    renderer.render(state, now=100, replay=True, connection="PAUSED", options=options)
    renderer._body.assert_called_once()
    assert state is original and state.age(100) == 90
    assert "PAUSED VIDEO REPLAY - NOT LIVE CAMERA" in labels
    assert not any(label in ("Play", "Pause", "00:02 / 00:10") for label in labels)
    for replay, connection in ((False, "PAUSED"), (True, "RUNNING"), (True, "ERROR")):
        renderer._body.reset_mock()
        renderer.render(state, now=100, replay=replay, connection=connection, options=options)
        renderer._body.assert_not_called()


def test_seek_generation_resets_temporal_response_but_preserves_completed_calibration():
    renderer = Renderer()
    renderer._body = Mock()
    response = renderer.face_response
    response.calibrated = True
    response.neutral[:] = 0.12
    response.high[:] = 0.85
    response.set_gain("jaw_open", 1.7)
    state = replace(demo_observation(0, 10), media_time=2)
    options = StageOptions(grid=False, hud=False, head_detail=False)
    renderer.render(state, now=10, replay=True, options=options)
    response.begin("range", 10)
    response.samples = [np.zeros(8)]
    renderer.render(
        replace(state, generation=1, captured_at=11, completed_at=11, media_time=1),
        now=11,
        replay=True,
        options=options,
    )
    assert response.calibrated and response.collecting is None and response.samples == []
    assert np.all(response.neutral == 0.12) and np.all(response.high == 0.85)
    assert response.gains[2] == 1.7


def test_black_diagnostic_freezes_only_labelled_recorded_samples(monkeypatch):
    labels = []
    monkeypatch.setattr(
        debug_views, "_label", lambda image, title, subtitle: labels.append(subtitle)
    )
    state = replace(demo_observation(0, time.perf_counter() - 10), media_time=2)
    paused = debug_views.skeleton(state, (640, 480), time.perf_counter(), paused=True)
    assert labels[-1].startswith("PAUSED REPLAY")
    stale = debug_views.skeleton(state, (640, 480), time.perf_counter())
    assert not np.array_equal(paused, stale)
    camera_state = replace(state, media_time=None)
    debug_views.skeleton(camera_state, (640, 480), time.perf_counter(), paused=True)
    assert not labels[-1].startswith("PAUSED REPLAY")
