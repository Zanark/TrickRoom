import argparse
import hashlib
import json
import time
from pathlib import Path

import pytest

from trickroom.camera import CaptureStatus, Source
from trickroom.cli import main, positive_seconds
from trickroom.models import Model, ensure_models, verify
from trickroom.runtime import Runtime, RuntimeStatus, _Snapshot


def slow_start_worker(connection, stop, preview_enabled, *args):
    time.sleep(0.08)
    connection.send(_Snapshot(RuntimeStatus("STOPPED"), CaptureStatus(), None, finished=True))
    connection.close()


def test_verify_models_does_not_silently_accept_tampering(tmp_path):
    path = tmp_path / "fixture.task"
    path.write_bytes(b"fixture")
    model = Model(
        path.name, "https://example.invalid/model", hashlib.sha256(b"fixture").hexdigest()
    )
    verify(path, model)
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Checksum"):
        verify(path, model)
    with pytest.raises(FileNotFoundError, match="download-models"):
        verify(tmp_path / "missing.task", model)


def test_normal_run_never_downloads_missing_models(tmp_path):
    with pytest.raises(FileNotFoundError):
        ensure_models(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_headless_requires_explicit_demo_or_source(monkeypatch):
    monkeypatch.delenv("TRICKROOM_CAMERA_URL", raising=False)
    assert main(["--headless", "--seconds", "0.1"]) == 2


def test_demo_exercises_renderer_and_writes_safe_aggregate_report(tmp_path, monkeypatch):
    monkeypatch.delenv("TRICKROOM_CAMERA_URL", raising=False)
    report, image = tmp_path / "report.json", tmp_path / "stage.png"
    assert (
        main(
            [
                "--demo",
                "--headless",
                "--seconds",
                "0.15",
                "--report",
                str(report),
                "--snapshot",
                str(image),
            ]
        )
        == 0
    )
    data = json.loads(report.read_text())
    assert data["mode"] == "synthetic-demo"
    assert data["rendered_frames"] > 0
    assert data["inference"] is None and data["capture"] is None
    assert data["raw_pixels_saved"] is False
    assert data["end_to_end_latency_measured"] is False
    assert image.is_file()


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "0", "999999"])
def test_bounded_duration_rejects_unbounded_values(value):
    with pytest.raises(argparse.ArgumentTypeError):
        positive_seconds(value)


def test_runtime_reports_missing_models_without_starting_camera(tmp_path):
    runtime = Runtime(Source("device", 999), tmp_path)
    runtime.start()
    runtime.join(3)
    assert runtime.status.state == "ERROR"
    assert "Missing" in runtime.status.message
    assert runtime.camera.status.frames == 0
    assert not runtime.alive


def test_early_shutdown_cannot_open_camera_after_models_load(monkeypatch):
    monkeypatch.setattr("trickroom.runtime._tracking_worker", slow_start_worker)
    runtime = Runtime(Source("device", 999), Path("."))
    runtime.start()
    runtime.stop()
    runtime.join(2)
    assert runtime.status.state == "STOPPED"
    assert runtime.camera.status.frames == 0
    assert not runtime.alive


def test_powershell_text_copies_match():
    root = Path(__file__).resolve().parents[1]
    for name in ("Setup-TrickRoom", "Start-TrickRoom"):
        assert (root / f"{name}.ps1").read_bytes() == (root / f"{name}.txt").read_bytes()


def test_keyboard_interrupt_cleans_up_desktop_runtime(monkeypatch):
    calls = []

    class Variable:
        def set(self, _value):
            pass

    class FakeRuntime:
        alive = False

        def stop(self):
            calls.append("stop")

        def join(self):
            calls.append("join")

    class FakeRoot:
        def mainloop(self):
            raise KeyboardInterrupt

        def destroy(self):
            calls.append("destroy")

    class FakeStudio:
        def __init__(self, *_args, **_kwargs):
            self.runtime = FakeRuntime()
            self.exit_code = 0
            self.username = self.password = self.crop_demo = Variable()

    monkeypatch.setattr("tkinter.Tk", FakeRoot)
    monkeypatch.setattr("trickroom.studio.Studio", FakeStudio)
    assert main(["--demo"]) == 130
    assert calls == ["stop", "join", "destroy"]


def test_studio_initialization_failure_destroys_the_window(monkeypatch):
    calls = []

    class FakeRoot:
        def destroy(self):
            calls.append("destroy")

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("OpenGL 3.3 unavailable")

    monkeypatch.setattr("tkinter.Tk", FakeRoot)
    monkeypatch.setattr("trickroom.studio.Studio", unavailable)
    assert main(["--demo"]) == 2
    assert calls == ["destroy"]
