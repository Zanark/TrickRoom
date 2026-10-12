"""Bounded real-Tk UI checks. Captures only this application's own synthetic window."""

from __future__ import annotations

import argparse
import json
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import ImageTk
from ui_capture import capture_own_window

from trickroom.models import default_model_directory
from trickroom.raster import close_renderer
from trickroom.studio import Studio


def check(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    studio = Studio(root, default_model_directory(), demo=True)
    errors = []

    def callback_error(kind, value, traceback):
        errors.append(f"{kind.__name__}: {value}")

    root.report_callback_exception = callback_error
    replay = destination / "synthetic-input.avi"

    def pump(seconds: float) -> None:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            root.update()
            time.sleep(0.01)
        assert not errors, errors

    try:
        root.attributes("-topmost", True)
        pump(0.8)
        initial_geometry = root.geometry()
        assert studio.runtime is None and studio.demo
        assert studio._photo is not None
        assert studio.preview.winfo_width() >= 320
        assert "DEMO" in studio.mode_label.get()
        assert str(studio.video_button["state"]) == "normal"
        assert str(studio.replay_button["state"]) == "disabled"
        assert not studio.outline.get() and not studio.skeleton.get()
        root.attributes("-topmost", False)
        root.lift()
        pump(0.2)
        screenshot_captured = capture_own_window(root, destination / "studio-demo.png")
        assert list(studio.sections) == [
            "01 / INPUT",
            "02 / BLENDER MODEL",
            "03 / RIG MOTION",
            "04 / FACE RESPONSE",
            "05 / PRESENTATION",
            "06 / PRIVATE DEBUG WINDOWS",
            "07 / TRACKING INPUT",
        ]
        assert [section.expanded for section in studio.sections.values()] == [
            True,
            False,
            False,
            False,
            False,
            False,
            False,
        ]
        initial_panel_height = studio.controls_canvas.bbox("all")[3]
        source_widget = studio.source_entry
        studio.rotation.set("left")
        studio.face_gains["jaw_open"].set(1.7)
        studio.expand_sections_button.invoke()
        pump(0.1)
        expanded_panel_height = studio.controls_canvas.bbox("all")[3]
        assert all(section.body.winfo_ismapped() for section in studio.sections.values())
        assert initial_panel_height < expanded_panel_height * 0.6
        studio.controls_canvas.yview_moveto(1)
        studio.collapse_sections_button.invoke()
        pump(0.1)
        collapsed_panel_height = studio.controls_canvas.bbox("all")[3]
        assert collapsed_panel_height < expanded_panel_height * 0.25
        assert collapsed_panel_height <= studio.controls_canvas.winfo_height()
        assert studio.controls_canvas.yview()[0] == 0
        assert not any(section.body.winfo_ismapped() for section in studio.sections.values())
        first_header = studio.sections["01 / INPUT"].header
        next_header = studio.sections["02 / BLENDER MODEL"].header
        assert str(first_header.tk.call("tk_focusNext", str(first_header))) == str(next_header)
        assert studio.source_entry is source_widget
        assert studio.rotation.get() == "left" and studio.face_gains["jaw_open"].get() == 1.7
        face_section = studio.sections["04 / FACE RESPONSE"]
        face_section.header.invoke()
        pump(0.1)
        assert face_section.body.winfo_ismapped()
        assert sum(section.expanded for section in studio.sections.values()) == 1
        face_section.header.focus_force()
        face_section.header.event_generate("<KeyPress-Return>")
        pump(0.1)
        assert not face_section.expanded
        face_section.header.event_generate("<KeyPress-space>")
        face_section.header.event_generate("<KeyRelease-space>")
        pump(0.1)
        assert face_section.expanded
        studio.sections["01 / INPUT"].set_expanded(True)
        studio.source_entry.focus_set()
        pump(0.05)
        studio.sections["01 / INPUT"].set_expanded(False)
        assert root.focus_get() == studio.sections["01 / INPUT"].header
        studio.collapse_sections_button.invoke()
        root.geometry("1020x720")
        pump(0.15)
        assert studio.controls_canvas.bbox("all")[3] <= studio.controls_canvas.winfo_height()
        collapsed_screenshot_captured = capture_own_window(
            root, destination / "studio-collapsed.png"
        )
        for section in studio.sections.values():
            section.header.invoke()
            pump(0.02)
            assert section.body.winfo_ismapped()
        studio.debug_options["skeleton"].set(True)
        studio.toggle_debug("skeleton")
        debug_window = studio._debug_windows["skeleton"][0]
        studio.set_sections_expanded(False)
        pump(0.05)
        assert studio.debug_options["skeleton"].get() and debug_window.winfo_exists()
        studio.debug_options["skeleton"].set(False)
        studio.toggle_debug("skeleton")
        studio.sections["01 / INPUT"].set_expanded(True)
        studio.rotation.set("none")
        studio.face_gains["jaw_open"].set(1)
        root.geometry(initial_geometry)
        pump(0.1)
        studio.grid.set(False)
        pump(0.15)
        plain = ImageTk.getimage(studio._photo)
        assert plain.getpixel((5, plain.height // 2))[:3] == (10, 18, 28)
        studio.grid.set(True)
        pump(0.15)
        room = ImageTk.getimage(studio._photo)
        assert room.getpixel((5, room.height // 2))[:3] != (10, 18, 28)
        studio.crop_demo.set(True)
        pump(0.25)
        assert "PARTIAL BODY" in studio.body_info.get()
        studio.mirror.set(False)
        studio.outline.set(True)
        studio.skeleton.set(True)
        studio.detail.set(False)
        pump(0.2)
        studio.open_output()
        pump(0.4)
        assert studio._output_window.winfo_exists()
        assert studio._output_photo is not None
        studio._output_window.destroy()
        studio.source.set("not-a-camera")
        studio.connect()
        pump(0.1)
        assert studio.runtime is None
        assert "Source is not" in studio.message.get()
        studio.source.set("")
        studio.disconnect()
        pump(0.15)
        assert not studio.demo
        studio.start_demo()
        pump(0.2)
        assert studio.demo
        writer = cv2.VideoWriter(
            str(replay),
            cv2.VideoWriter_fourcc(*"MJPG"),
            15,
            (320, 240),
        )
        assert writer.isOpened()
        for _ in range(24):
            writer.write(np.full((240, 320, 3), (24, 35, 45), np.uint8))
        writer.release()
        with patch("trickroom.studio.filedialog.askopenfilename", return_value=str(replay)):
            studio.video_button.invoke()
        first_runtime = studio.runtime
        assert first_runtime.camera.source.kind == "file"
        assert not studio.demo
        assert str(studio.video_button["state"]) == "disabled"
        assert str(studio.replay_button["state"]) == "disabled"
        studio.collapse_sections_button.invoke()
        assert studio.runtime is first_runtime and studio.runtime.alive
        assert not studio.debug_options["input"].get()
        deadline = time.perf_counter() + 8
        saw_replay_label = studio.mode_label.get().startswith("VIDEO REPLAY")
        while time.perf_counter() < deadline and studio.runtime.status.state != "ENDED":
            pump(0.1)
            saw_replay_label |= studio.mode_label.get().startswith("VIDEO REPLAY")
            assert studio.runtime.status.state != "ERROR", studio.runtime.status.message
        pump(0.25)
        assert studio.runtime.status.state == "ENDED"
        assert studio.runtime.status.frames >= 5
        assert studio.runtime.status.face_frames == studio.runtime.status.body_frames == 0
        assert studio.mode_label.get() == "REPLAY ENDED"
        assert saw_replay_label and studio.runtime.input_preview is None
        cleanup_deadline = time.perf_counter() + 4
        while time.perf_counter() < cleanup_deadline and (
            studio.runtime.alive or str(studio.connect_button["state"]) != "normal"
        ):
            pump(0.1)
        assert not studio.runtime.alive, "Replay worker failed to finish model cleanup."
        assert str(studio.connect_button["state"]) == "normal"
        assert str(studio.replay_button["state"]) == "normal"
        studio.replay_button.invoke()
        assert studio.runtime is not first_runtime and not studio.demo
        assert studio.runtime.camera.source.kind == "file"
        deadline = time.perf_counter() + 8
        while studio.runtime.status.frames < 3 and time.perf_counter() < deadline:
            pump(0.1)
            assert studio.runtime.status.state != "ERROR", studio.runtime.status.message
        assert studio.runtime.status.frames >= 3
        assert studio.runtime.input_preview is None
        studio.disconnect()
        pump(0.15)
        studio.close()
        root.update()
    finally:
        studio.render_worker.close()
        studio.render_worker.join(6)
        assert not studio.render_worker.alive
        if studio.runtime is not None:
            studio.runtime.stop()
            studio.runtime.join()
        replay.unlink(missing_ok=True)
        close_renderer()
        try:
            root.destroy()
        except tk.TclError:
            pass
    report = {
        "checks": [
            "native-window-render",
            "demo-labelled-no-camera",
            "cropped-body-status",
            "presentation-controls",
            "reference-avatar-defaults-and-optional-diagnostics",
            "perspective-room-toggle",
            "clean-output-window",
            "invalid-source-no-camera",
            "disconnect",
            "restart-demo",
            "actual-model-synthetic-replay-and-eof-controls",
            "recorded-video-picker-and-labelled-test-view",
            "replay-last-video-with-new-worker",
            "all-seven-sections-collapse-independently",
            "bulk-collapse-and-minimum-window-scroll-bounds",
            "section-keyboard-and-focus-behavior",
            "collapsed-controls-preserve-values-and-active-replay",
            "folding-debug-controls-keeps-open-windows",
            "close",
        ],
        "callback_errors": errors,
        "passed": True,
        "owner_camera_opened": False,
        "screenshot_captured": screenshot_captured,
        "collapsed_screenshot_captured": collapsed_screenshot_captured,
        "panel_heights": {
            "initial": initial_panel_height,
            "all_expanded": expanded_panel_height,
            "all_collapsed": collapsed_panel_height,
        },
        "user_approval_claimed": False,
    }
    (destination / "studio-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/ui-check"))
    check(parser.parse_args().output)
