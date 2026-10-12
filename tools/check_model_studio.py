"""Actual Tk import/switch/clip/error checks using only the original technical Blender fixture."""

import faulthandler
import json
import time
import tkinter as tk
from pathlib import Path

from ui_capture import capture_own_window

from trickroom.models import default_model_directory
from trickroom.raster import close_renderer
from trickroom.studio import Studio


def check():
    faulthandler.dump_traceback_later(40, exit=True)
    destination = Path(".local/blender-ui")
    destination.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    studio = Studio(root, default_model_directory(), demo=True)
    errors = []
    root.report_callback_exception = lambda kind, value, tb: errors.append(
        f"{kind.__name__}: {value}"
    )

    def pump(duration=0.1):
        end = time.perf_counter() + duration
        while time.perf_counter() < end:
            root.update()
            time.sleep(0.01)
        assert not errors, errors

    def until(predicate, timeout=10):
        end = time.perf_counter() + timeout
        while time.perf_counter() < end and not predicate():
            pump()
        assert predicate(), studio.model_info.get()

    try:
        pump(0.5)
        assert studio.renderer.imported is None
        fixture = Path("examples/blender/TrickRoom-Conformance.glb")
        studio.load_model(fixture)
        until(lambda: not studio._model_pending and studio.renderer.imported is not None)
        original = studio.renderer.imported
        assert studio._model_report["skins"] == 1
        studio.model_mode.set("ConformanceWave")
        studio.change_model_mode()
        pump(0.5)
        assert studio.render_worker.status.frame is not None
        assert "MODEL PREVIEW" in studio.mode_label.get()
        studio.model_mode.set("live")
        studio.change_model_mode()
        pump(0.25)
        studio.recalibrate_model()
        pump(0.2)
        assert studio.renderer.imported.calibrated_scale is not None
        studio.sections["01 / INPUT"].set_expanded(False)
        studio.sections["02 / BLENDER MODEL"].set_expanded(True)
        studio.sections["03 / RIG MOTION"].set_expanded(True)
        root.attributes("-topmost", True)
        pump(0.15)
        screenshot_captured = capture_own_window(root, destination / "imported-model-studio.png")
        root.attributes("-topmost", False)
        bad = destination / "invalid.glb"
        bad.write_bytes(b"not a model")
        studio.load_model(bad)
        until(lambda: not studio._model_pending)
        assert studio.renderer.imported is original
        assert "Import rejected" in studio.model_info.get()
        bad.unlink()
        studio.open_output()
        pump(0.3)
        assert studio._output_photo is not None
        studio._output_window.destroy()
        studio.use_builtin()
        pump(0.2)
        assert studio.renderer.imported is None
        studio.load_model(fixture)
        studio.close()
        deadline = time.perf_counter() + 8
        while time.perf_counter() < deadline:
            try:
                root.update()
                if not root.winfo_exists():
                    break
            except tk.TclError:
                break
            time.sleep(0.02)
        assert studio._model_thread is None or not studio._model_thread.is_alive()
    finally:
        studio.render_worker.close()
        studio.render_worker.join(6)
        assert not studio.render_worker.alive
        if studio.runtime:
            studio.runtime.stop()
            studio.runtime.join()
        close_renderer()
        try:
            root.destroy()
        except tk.TclError:
            pass
        faulthandler.cancel_dump_traceback_later()
    report = {
        "passed": True,
        "checks": [
            "asynchronous-import",
            "rig-report",
            "clip-preview",
            "live-return",
            "recalibration",
            "rejected-import-retains-model",
            "clean-output",
            "built-in-return",
            "close-during-import",
        ],
        "callback_errors": errors,
        "owner_camera_opened": False,
        "screenshot_captured": screenshot_captured,
    }
    (destination / "model-studio-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    check()
