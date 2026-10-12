from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from trickroom.camera import CaptureStatus
from trickroom.demo import demo_observation
from trickroom.render import Renderer, StageOptions
from trickroom.runtime import RuntimeStatus
from trickroom.studio import Studio


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


@pytest.fixture
def studio(monkeypatch, tmp_path):
    app = Studio.__new__(Studio)
    app._closing = app._disconnecting = app._model_pending = False
    app.runtime = None
    app._test_video = None
    app.root = Mock()
    app.renderer = Mock()
    app.renderer.imported = None
    app._model_report = None
    app._render_command = lambda action: action()
    app.source = Variable("")
    app.username = Variable("unused-test-user")
    app.password = Variable("unused-test-password")
    app.rotation = Variable("none")
    app.smoothing = Variable(True)
    app.crop_demo = Variable(True)
    app.models = tmp_path
    app.tracking_size = 768
    app.model_mode = Variable("live")
    app.mode_label = Variable("DEMO / no camera access")
    app.message = Variable("Ready")
    app.debug_options = {"input": Variable(False)}
    app.demo = True
    for name in ("connect_button", "demo_button", "video_button", "replay_button"):
        setattr(app, name, Mock())

    def runtime(source, *_args, start_position=0.0, paused=False):
        worker = Mock()
        worker.camera = SimpleNamespace(source=source, status=CaptureStatus("STREAMING"))
        worker.status = RuntimeStatus("RUNNING")
        worker.alive = False
        worker.start.side_effect = lambda: setattr(worker, "alive", True)
        return worker

    monkeypatch.setattr("trickroom.studio.Runtime", runtime)
    return app


def video(tmp_path):
    path = tmp_path / "movement recording.mp4"
    path.write_bytes(b"placeholder; decoding is covered by the native replay check")
    return path


def test_picker_routes_local_video_through_tracking_not_scripted_demo(
    studio, monkeypatch, tmp_path
):
    path = video(tmp_path)
    dialog = Mock(return_value=str(path))
    monkeypatch.setattr("trickroom.studio.filedialog.askopenfilename", dialog)
    studio.choose_test_video()
    assert studio.runtime.camera.source.kind == "file"
    assert studio.runtime.camera.source.location == str(path.resolve())
    assert studio.runtime.camera.source.username == studio.runtime.camera.source.password == ""
    assert studio._test_video == path.resolve()
    assert not studio.demo and studio.crop_demo.get()
    studio.renderer.reset_motion.assert_called_once()
    studio.runtime.enable_input_preview.assert_called_once_with(False)
    assert studio.mode_label.get() == "VIDEO REPLAY / LOADING"
    assert str(path) not in studio.message.get()
    studio.video_button.configure.assert_called_with(state="disabled")
    studio.replay_button.configure.assert_called_with(state="disabled")


def test_picker_cancel_does_not_change_source_or_avatar(studio, monkeypatch):
    studio.source.set("unchanged private input")
    monkeypatch.setattr("trickroom.studio.filedialog.askopenfilename", lambda **_: "")
    studio.choose_test_video()
    assert studio.source.get() == "unchanged private input"
    assert studio.runtime is None and studio.demo
    studio.renderer.reset_motion.assert_not_called()


@pytest.mark.parametrize("busy", ("closing", "disconnecting", "running"))
def test_video_action_never_interrupts_an_active_source(studio, monkeypatch, tmp_path, busy):
    if busy == "running":
        studio.runtime = Mock(alive=True)
    else:
        setattr(studio, "_" + busy, True)
    dialog = Mock()
    monkeypatch.setattr("trickroom.studio.filedialog.askopenfilename", dialog)
    studio.choose_test_video()
    studio.play_test_video(video(tmp_path))
    dialog.assert_not_called()
    studio.renderer.reset_motion.assert_not_called()
    assert studio._test_video is None and studio.source.get() == ""
    if studio.runtime is not None:
        studio.runtime.stop.assert_not_called()


def test_pending_model_blocks_video_without_changing_preview(studio, tmp_path):
    studio._model_pending = True
    studio.play_test_video(video(tmp_path))
    assert studio.runtime is None and studio.demo
    assert "model loading" in studio.message.get()


@pytest.mark.parametrize("selection", ("missing.mp4", "0", "https://example.invalid/video"))
def test_video_action_rejects_missing_files_and_non_file_sources(studio, selection):
    studio.play_test_video(Path(selection))
    assert studio.runtime is None and studio.demo
    assert "existing readable video file" in studio.message.get()
    studio.renderer.reset_motion.assert_not_called()


def test_video_test_keeps_imported_avatar_but_exits_authored_clip_mode(studio, tmp_path):
    model = studio.renderer.imported = Mock()
    studio._model_report = {}
    studio.model_mode.set("ConformanceWave")
    studio.play_test_video(video(tmp_path))
    assert studio.renderer.imported is model
    assert studio.model_mode.get() == "live"
    assert model.set_mode.call_args.args[0] == "live"


def test_replay_remembers_file_only_in_session_and_creates_new_runtime(studio, tmp_path):
    path = video(tmp_path)
    studio.play_test_video(path)
    first = studio.runtime
    first.alive = False
    studio._connection_buttons(True)
    studio.replay_button.configure.assert_called_with(state="normal")
    studio.source.set("do not reconnect this input")
    studio.replay_test_video()
    assert studio.runtime is not first
    assert studio.runtime.camera.source.location == str(path.resolve())
    assert not studio.demo
    assert path.read_bytes().startswith(b"placeholder")


def test_replay_handles_deleted_recording_without_guessing_another_source(studio, tmp_path):
    path = video(tmp_path)
    studio.play_test_video(path)
    first = studio.runtime
    first.alive = False
    path.unlink()
    studio.replay_test_video()
    assert studio.runtime is first
    assert "could not start" in studio.message.get()


def test_replay_without_a_selected_file_is_explicit(studio):
    studio.replay_test_video()
    assert studio.runtime is None
    assert "Choose a recording" in studio.message.get()
    studio._connection_buttons(True)
    studio.replay_button.configure.assert_called_with(state="disabled")


def test_generic_file_connect_is_also_available_for_replay(studio, tmp_path):
    path = video(tmp_path)
    studio.source.set(str(path))
    studio.connect()
    assert studio._test_video == path.resolve()
    assert studio.mode_label.get() == "VIDEO REPLAY / LOADING"


def test_video_worker_start_failure_is_visible_and_retryable(studio, monkeypatch, tmp_path):
    worker = Mock(alive=False)
    worker.start.side_effect = OSError("startup failed")
    worker.status = RuntimeStatus("ERROR", "Could not start the tracking worker.")
    monkeypatch.setattr("trickroom.studio.Runtime", Mock(return_value=worker))
    studio.play_test_video(video(tmp_path))
    assert studio.mode_label.get() == "ERROR / SYNTHETIC OUTPUT ONLY"
    assert studio.message.get() == worker.status.message
    studio.video_button.configure.assert_called_with(state="normal")
    studio.replay_button.configure.assert_called_with(state="normal")


def test_replay_labels_are_distinct_from_live_camera_and_demo(monkeypatch):
    labels = []
    monkeypatch.setattr(
        "trickroom.render._text", lambda image, label, *a, **k: labels.append(label)
    )
    renderer = Renderer()
    state = demo_observation(0, 10)
    renderer.render(state, now=10, replay=True)
    assert "VIDEO REPLAY" in labels and "FACE / REPLAY" in labels
    assert "DEMO / NOT CAMERA" not in labels and "FACE LIVE" not in labels
    labels.clear()
    renderer.render(state, now=10, replay=True, options=StageOptions(hud=False, head_detail=False))
    assert "VIDEO REPLAY - NOT LIVE CAMERA" in labels
