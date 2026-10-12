"""Exercise private debug windows with authored synthetic frames; never open a camera."""

from __future__ import annotations

import faulthandler
import json
import threading
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import ImageTk

from trickroom.camera import CapturedFrame, Source
from trickroom.demo import demo_observation
from trickroom.models import default_model_directory
from trickroom.raster import close_renderer
from trickroom.runtime import Runtime, RuntimeStatus
from trickroom.state import Point
from trickroom.studio import Studio


def check():
    faulthandler.dump_traceback_later(45, exit=True)
    output = Path(".local/debug-views")
    output.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    studio = Studio(root, default_model_directory(), demo=True)
    errors = []
    root.report_callback_exception = lambda kind, value, tb: errors.append(
        f"{kind.__name__}: {value}"
    )
    runtime = Runtime(Source("device", 0), default_model_directory())
    pixels = np.zeros((180, 320, 3), np.uint8)
    pixels[:, :160] = (25, 55, 195)
    pixels[:, 160:] = (195, 55, 25)
    points = tuple(
        Point(0.5 + 0.11 * np.cos(i * 0.37), 0.20 + 0.14 * np.sin(i * 0.37)) for i in range(478)
    )
    sequence = 0
    emit = False
    producer_stop = threading.Event()
    studio.runtime, studio.demo = runtime, False

    def publish_observations():
        nonlocal sequence
        while not producer_stop.wait(1 / 30):
            if emit:
                sequence += 1
                now = time.perf_counter()
                state = demo_observation(0, now)
                state = replace(
                    state, sequence=sequence, face=replace(state.face, landmarks=points)
                )
                runtime._publish(
                    state, CapturedFrame(sequence, now, pixels), RuntimeStatus("RUNNING")
                )

    def pump(duration=0.15, publish=True):
        nonlocal emit
        emit = publish
        until = time.perf_counter() + duration
        while time.perf_counter() < until:
            root.update()
            time.sleep(0.015)
        assert not errors, errors

    producer = threading.Thread(target=publish_observations, name="authored-input", daemon=True)
    producer.start()
    try:
        assert not any(v.get() for v in studio.debug_options.values())
        assert runtime.input_preview is None and not runtime.camera.alive
        pump()
        for name in studio.debug_options:
            studio.debug_options[name].set(True)
            studio.toggle_debug(name)
        pump(0.4)
        assert len(studio._debug_windows) == 3
        assert runtime.input_preview is not None and not runtime.camera.alive
        for name, photo in studio._debug_photos.items():
            image = ImageTk.getimage(photo)
            image.save(output / f"synthetic-{name}.png")
            if name != "input":
                array = np.array(image)
                assert np.mean(np.all(array[:, :, :3] == 0, axis=2)) > 0.5
        raw_window = studio._debug_windows["input"][0]
        root.tk.call(raw_window.protocol("WM_DELETE_WINDOW"))
        assert not studio.debug_options["input"].get()
        assert runtime.input_preview is None and "input" not in studio._debug_photos
        studio.debug_options["input"].set(True)
        studio.toggle_debug("input")
        pump()
        assert runtime.input_preview is not None
        studio.open_output()
        pump(0.3)
        assert studio._output_photo is not None
        studio._output_window.destroy()
        studio.disconnect()
        pump(0.2, publish=False)
        assert runtime.input_preview is None
        assert studio.runtime is None
        for name in tuple(studio._debug_windows):
            studio.debug_options[name].set(False)
            studio.toggle_debug(name)
        assert studio._debug_windows == {} and studio._debug_photos == {}
        studio.close()
    finally:
        studio.render_worker.close()
        studio.render_worker.join(6)
        assert not studio.render_worker.alive
        producer_stop.set()
        producer.join(1)
        runtime.stop()
        close_renderer()
        try:
            root.destroy()
        except tk.TclError:
            pass
        faulthandler.cancel_dump_traceback_later()
        assert not producer.is_alive()
    report = {
        "passed": True,
        "evidence_class": "native UI driven by authored synthetic input and landmarks",
        "owner_camera_opened": False,
        "checks": [
            "defaults-off",
            "three-separate-windows",
            "opt-in-raw-retention",
            "black-skeleton-and-face",
            "close-disables-raw",
            "reopen",
            "clean-output-coexists",
            "disconnect-clears",
            "all-windows-close",
        ],
        "callback_errors": errors,
    }
    (output / "debug-ui-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    check()
