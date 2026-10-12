"""Bounded motion-control UI checks with authored observations, not a physical camera."""

import faulthandler
import json
import math
import sys
import threading
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path

from trickroom.camera import CaptureStatus, Source
from trickroom.demo import demo_observation
from trickroom.models import default_model_directory
from trickroom.raster import close_renderer
from trickroom.runtime import Runtime, RuntimeStatus
from trickroom.state import Expression, Point
from trickroom.studio import Studio


def check():
    faulthandler.dump_traceback_later(60, exit=True)
    root = tk.Tk()
    studio = Studio(root, default_model_directory(), demo=True)
    root.geometry("1020x720")
    errors = []
    root.report_callback_exception = lambda kind, value, tb: errors.append(
        f"{kind.__name__}: {value}"
    )
    runtime = Runtime(Source("device", 999), default_model_directory())
    expression = Expression(jaw_open=0.1, smile=0.02)
    emit = False
    sequence = 0
    producer_stop = threading.Event()
    points = tuple(Point(0.5 + 0.06 * math.cos(i), 0.2 + 0.09 * math.sin(i)) for i in range(478))

    def publish_observations():
        nonlocal sequence
        while not producer_stop.wait(1 / 30):
            if emit:
                sequence += 1
                now = time.perf_counter()
                state = demo_observation(0, now)
                state = replace(
                    state,
                    sequence=sequence,
                    face=replace(
                        state.face,
                        expression=expression,
                        landmarks=points,
                    ),
                )
                runtime._publish(state, None, RuntimeStatus("RUNNING", frames=sequence))

    def pump(seconds):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            root.update()
            time.sleep(0.01)
        assert not errors, errors

    producer = threading.Thread(target=publish_observations, name="authored-input", daemon=True)
    producer.start()
    try:
        pump(0.3)
        studio.calibrate_face("neutral")
        assert "not demo" in studio.message.get()
        studio.load_model(Path("examples/blender/TrickRoom-Conformance.glb"))
        deadline = time.perf_counter() + 10
        while studio._model_pending and time.perf_counter() < deadline:
            pump(0.1)
        assert studio.renderer.imported is not None
        pump(0.3)
        assert studio.renderer.imported.motion.options.space == "world"
        studio.rig_space.set("image")
        pump(0.1)
        assert studio.renderer.imported.motion.options.space == "image"
        studio.rig_motion.set(False)
        pump(0.1)
        assert studio.render_worker.status.frame.evaluation.tracking_states is None
        studio.rig_motion.set(True)
        studio.rig_space.set("world")
        studio.relax_missing.set(True)
        pump(0.2)
        studio.crop_demo.set(True)
        pump(0.6)
        assert "PARTIAL BODY" in studio.body_info.get()
        assert (
            studio.render_worker.status.frame.evaluation.tracking_states["lower_leg_left"] == "REST"
        )
        studio.demo = False
        studio.runtime = runtime
        stale = demo_observation(0, time.perf_counter() - 1)
        runtime._publish(stale, None, RuntimeStatus("RUNNING"))
        pump(0.1)
        assert studio.render_worker.status.frame is None
        assert not studio.renderer.imported.motion.history
        runtime._capture_status = CaptureStatus("STREAMING", size=(900, 1200))
        emit = True
        pump(0.1)
        studio.calibrate_face("neutral")
        pump(0.15)
        deadline = time.perf_counter() + 3
        while (
            studio.renderer.face_response.collecting is not None and time.perf_counter() < deadline
        ):
            pump(0.1)
        assert studio.renderer.face_response.calibrated, {
            "response": studio.renderer.face_response.message,
            "collecting": studio.renderer.face_response.collecting,
            "samples": len(studio.renderer.face_response.samples),
            "ui": studio.message.get(),
            "render_hz": studio._render_fps,
        }
        assert studio.face_shaping.get()
        expression = Expression(blink_left=1, blink_right=1, jaw_open=0.8, smile=0.8)
        studio.calibrate_face("range")
        pump(0.15)
        deadline = time.perf_counter() + 5
        while (
            studio.renderer.face_response.collecting is not None and time.perf_counter() < deadline
        ):
            pump(0.1)
        assert "Range captured" in studio.renderer.face_response.message
        assert runtime.observation.face.expression == expression
        studio.clear_face_calibration()
        pump(0.1)
        assert not studio.renderer.face_response.calibrated and not studio.face_shaping.get()
        studio.open_output()
        for name in ("skeleton", "face"):
            studio.debug_options[name].set(True)
            studio.toggle_debug(name)
        pump(0.3)
        assert studio._output_photo is not None
        assert runtime.input_preview is None and not runtime.camera.alive
        assert "mediapipe" not in sys.modules
        emit = False
        studio.close()
        pump(0.05)
    finally:
        studio.render_worker.close()
        studio.render_worker.join(6)
        assert not studio.render_worker.alive
        producer_stop.set()
        producer.join(1)
        runtime.stop()
        runtime.join()
        close_renderer()
        try:
            root.destroy()
        except tk.TclError:
            pass
        faulthandler.cancel_dump_traceback_later()
        assert not producer.is_alive()
    report = {
        "passed": True,
        "evidence_class": "native controls driven by authored observations; no camera",
        "window_size": [1020, 720],
        "checks": [
            "demo-calibration-rejected",
            "world-image-and-legacy-controls",
            "opt-in-rest-distinct-from-measured-partial-status",
            "stale-clears-history",
            "neutral-and-range-controls",
            "raw-expression-unchanged",
            "calibration-clear",
            "clean-output-and-debug-coexist",
            "no-owner-side-native-sdk-import",
            "close",
        ],
        "callback_errors": errors,
        "owner_camera_opened": False,
        "personal_calibration_saved": False,
    }
    output = Path(".local/motion-upgrade")
    output.mkdir(parents=True, exist_ok=True)
    (output / "motion-studio.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    check()
