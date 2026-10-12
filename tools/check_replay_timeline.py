"""Native Studio transport checks; only generated input or an explicitly supplied recording."""

from __future__ import annotations

import argparse
import faulthandler
import hashlib
import json
import sys
import time
import tkinter as tk
from pathlib import Path

import cv2
import numpy as np
from PIL import ImageTk
from ui_capture import capture_own_window

from trickroom.models import default_model_directory
from trickroom.raster import close_renderer
from trickroom.render import StageOptions
from trickroom.studio import Studio


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(destination: Path, video: Path | None, avatar: Path | None) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    synthetic = destination / "timeline-fixture.avi"
    writer = cv2.VideoWriter(str(synthetic), cv2.VideoWriter_fourcc(*"MJPG"), 20, (320, 240))
    assert writer.isOpened()
    for index in range(240):
        writer.write(np.full((240, 320, 3), (index % 100, 32, 46), np.uint8))
    writer.release()
    original = {path: digest(path) for path in (video, avatar) if path is not None}
    if avatar is not None and avatar.with_suffix(".trickroom.json").is_file():
        profile = avatar.with_suffix(".trickroom.json")
        original[profile] = digest(profile)
    root = tk.Tk()
    studio = Studio(root, default_model_directory(), demo=True)
    errors, checks, positions, pids = [], [], [], []
    root.report_callback_exception = lambda kind, value, tb: errors.append(
        f"{kind.__name__}: {value}"
    )
    faulthandler.dump_traceback_later(180, exit=True)

    def pump(seconds=0.05):
        until = time.perf_counter() + seconds
        while time.perf_counter() < until:
            root.update()
            time.sleep(0.01)
        assert not errors, errors

    def wait(predicate, label, timeout=22):
        until = time.perf_counter() + timeout
        while not predicate() and time.perf_counter() < until:
            pump()
            if studio.runtime is not None:
                assert studio.runtime.status.state != "ERROR", studio.runtime.status.message
        assert predicate(), {
            "check": label,
            "runtime_state": studio.runtime.status.state if studio.runtime else None,
            "capture_state": studio.runtime.camera.status.state if studio.runtime else None,
            "capture_paused": studio.runtime.camera.status.paused if studio.runtime else None,
            "position": studio.runtime.camera.status.position_seconds if studio.runtime else None,
            "button_state": str(studio.playback_button["state"]),
            "button_text": str(studio.playback_button["text"]),
            "requested_paused": studio._requested_paused,
            "pending_seek": studio._pending_seek,
        }

    def pause():
        wait(
            lambda: (
                str(studio.playback_button["state"]) == "normal"
                and studio.runtime.status.state in ("RUNNING", "PAUSED")
            ),
            "Pause control did not become ready.",
        )
        if studio.runtime.status.state != "PAUSED":
            studio.playback_button.invoke()
        wait(lambda: studio.runtime.status.state == "PAUSED", "Pause was not acknowledged.")
        pump(0.15)
        assert studio.runtime.camera.status.paused

    def seek(seconds):
        generation = studio.runtime.camera.status.generation + 1
        studio.seek_playback(seconds)
        wait(
            lambda: (
                studio.runtime.observation is not None
                and studio.runtime.observation.generation == generation
            ),
            "The selected frame generation did not arrive.",
        )
        actual = studio.runtime.observation.media_time
        assert abs(actual - seconds) < 0.06, (seconds, actual)
        pump(0.08)
        if studio.renderer.imported is not None:
            wait(
                lambda: (
                    studio.render_worker.status.frame is not None
                    and studio.render_worker.status.frame.evaluation.placement is not None
                    and studio.render_worker.status.frame.evaluation.placement.generation
                    == generation
                ),
                "The selected generation did not reach avatar presentation.",
            )
        positions.append({"requested_seconds": seconds, "observed_seconds": actual})
        return studio.runtime.observation

    screenshots = {}
    supplied = None
    try:
        pump(0.4)
        assert not studio.playback_bar.winfo_ismapped()
        studio.play_test_video(synthetic)
        wait(
            lambda: studio.runtime.observation is not None and studio.playback_bar.winfo_ismapped(),
            "Recorded-video timeline did not become ready.",
        )
        runtime = studio.runtime
        pids.append(runtime.status.worker_pid)
        assert runtime.camera.status.duration_seconds == 12
        assert not studio.debug_options["input"].get() and runtime.input_preview is None
        pause()
        frozen, count = runtime.observation, runtime.status.frames
        pump(0.75)
        assert runtime.observation == frozen and runtime.status.frames == count
        assert "PAUSED" in studio.mode_label.get() and "PAUSED" in studio.body_info.get()
        checks.append("native-paused-heartbeat-without-new-observations")

        slider = studio.playback_slider
        x, y = round(slider.winfo_width() * 0.7), slider.winfo_height() // 2
        slider.event_generate("<ButtonPress-1>", x=x, y=y)
        target = studio.playback_position.get()
        pump(0.1)
        assert studio._scrubbing and studio.playback_position.get() == target
        x = round(slider.winfo_width() * 0.3)
        slider.event_generate("<B1-Motion>", x=x, y=y)
        target = studio.playback_position.get()
        generation = runtime.camera.status.generation + 1
        slider.event_generate("<ButtonRelease-1>", x=x, y=y)
        wait(
            lambda: (
                runtime.observation is not None and runtime.observation.generation == generation
            ),
            "Mouse release did not seek.",
        )
        assert abs(runtime.observation.media_time - target) < 0.06
        assert runtime.status.state == "PAUSED"
        checks.append("native-mouse-click-drag-release-and-thumb-isolation")

        slider.focus_force()
        pump()
        generation += 1
        old_position = runtime.observation.media_time
        slider.event_generate("<KeyPress-Right>")
        target = studio.playback_position.get()
        slider.event_generate("<KeyRelease-Right>")
        wait(
            lambda: (
                runtime.observation is not None and runtime.observation.generation == generation
            ),
            "Keyboard right did not seek.",
        )
        assert abs(target - old_position - 1) < 0.06
        for key, target in (("Home", 0), ("End", 11.95)):
            generation += 1
            slider.event_generate(f"<KeyPress-{key}>")
            slider.event_generate(f"<KeyRelease-{key}>")
            wait(
                lambda expected_generation=generation: (
                    runtime.observation is not None
                    and runtime.observation.generation == expected_generation
                ),
                f"Keyboard {key} did not seek.",
            )
            assert abs(runtime.observation.media_time - target) < 0.06
        assert runtime.status.worker_pid == pids[0]
        checks.append("native-keyboard-second-start-end-seeks-in-the-same-worker")

        studio.playback_button.invoke()
        wait(lambda: runtime.status.state == "ENDED", "End-frame resume did not reach EOF.")
        wait(lambda: not runtime.alive, "EOF did not release the owned worker.")
        pump(0.25)
        assert studio.playback_position.get() == 12
        studio.seek_playback(4)
        wait(lambda: studio.runtime.observation is not None, "EOF seek did not restart replay.")
        assert studio.runtime is not runtime
        assert 4 <= studio.runtime.observation.media_time < 5.5
        pids.append(studio.runtime.status.worker_pid)
        assert pids[-1] != pids[0]
        pause()
        checks.append("finite-eof-cleanup-and-timeline-restart-at-selected-position")

        root.geometry("1020x720")
        studio.set_sections_expanded(False)
        pump(0.3)
        bar = studio.playback_bar
        assert bar.winfo_ismapped()
        assert bar.winfo_rooty() >= studio.preview_frame.winfo_rooty() + (
            studio.preview_frame.winfo_height()
        )
        assert bar.winfo_rooty() + bar.winfo_height() <= root.winfo_rooty() + root.winfo_height()
        assert studio._photo.height() == studio.preview_frame.winfo_height()
        screenshots["synthetic_studio"] = capture_own_window(
            root, destination / "studio-timeline.png"
        )
        studio.open_output()
        pump(0.2)
        assert studio._output_window.winfo_children() == [studio._output_label]
        clean = ImageTk.getimage(studio._output_photo).convert("RGB")
        expected_frame = studio.render_worker.submit(
            studio.renderer.render,
            studio.runtime.observation,
            clean.size,
            now=time.perf_counter(),
            replay=True,
            connection="PAUSED",
            options=StageOptions(
                studio.mirror.get(),
                studio.outline.get(),
                studio.skeleton.get(),
                studio.grid.get(),
                False,
                False,
            ),
        )
        wait(expected_frame.done, "Clean-output reference render did not complete.")
        expected = expected_frame.result()
        assert np.array_equal(np.asarray(clean), cv2.cvtColor(expected, cv2.COLOR_BGR2RGB))
        checks.append("minimum-layout-and-pixel-exact-control-free-clean-output")
        studio._output_window.destroy()
        studio.disconnect()
        wait(lambda: studio.runtime is None, "Paused Disconnect did not release the worker.")
        assert not studio.playback_bar.winfo_ismapped()
        studio.start_demo()
        pump(0.1)
        assert not studio.playback_bar.winfo_ismapped()
        checks.append("paused-disconnect-and-demo-hide-transport")

        if video is not None:
            studio.play_test_video(video)
            wait(lambda: studio.runtime.observation is not None, "Supplied replay did not start.")
            pause()
            runtime = studio.runtime
            pids.append(runtime.status.worker_pid)
            duration = runtime.camera.status.duration_seconds
            assert duration > 2
            target = min(18.0, duration * 0.25)
            seek(target)
            frozen = runtime.observation
            pump(0.75)
            assert runtime.observation == frozen and "PAUSED" in studio.mode_label.get()
            assert not studio.debug_options["input"].get() and runtime.input_preview is None
            if avatar is not None:
                studio.load_model(avatar)
                wait(lambda: not studio._model_pending, "The supplied GLB did not load.")
                assert studio.renderer.imported is not None
                wait(
                    lambda: studio.render_worker.status.frame is not None,
                    "The imported avatar did not finish its first rendered frame.",
                )
            for name in ("skeleton", "face"):
                studio.debug_options[name].set(True)
                studio.toggle_debug(name)
            studio.open_output()
            pump(0.2)
            screenshots["supplied_replay"] = capture_own_window(
                root, destination / "supplied-replay-timeline.png"
            )
            seek(min(30.0, duration * 0.5))
            seek(target)
            if avatar is not None:
                history = studio.renderer.imported.motion.history
                assert len(history) == 1
                assert history[-1].state.generation == runtime.observation.generation
            assert runtime.status.worker_pid == pids[-1]
            studio.playback_button.invoke()
            sequence = runtime.observation.sequence
            wait(
                lambda: runtime.observation is not None and runtime.observation.sequence > sequence,
                "Supplied replay did not resume after seeking.",
            )
            pause()
            supplied = {
                "duration_seconds": duration,
                "inferred_frames": runtime.status.frames,
                "body_frames": runtime.status.body_frames,
                "face_frames": runtime.status.face_frames,
                "seek_positions": positions.copy(),
                "same_worker_during_seeks": True,
                "imported_model_exercised": avatar is not None,
                "input_preview_remained_disabled": runtime.input_preview is None,
            }
            studio.disconnect()
            wait(lambda: studio.runtime is None, "Supplied paused replay did not stop.")
            assert not runtime.alive and not runtime.status.forced_shutdown
            supplied["worker_exit_code"] = runtime.status.worker_exit_code
            checks.append("explicit-supplied-recording-pause-forward-backward-model-and-cleanup")
        assert "mediapipe" not in sys.modules
        checks.append("no-native-tracking-sdk-in-studio")
        studio.close()
        root.update()
    finally:
        studio.render_worker.close()
        studio.render_worker.join(6)
        assert not studio.render_worker.alive
        if studio.runtime is not None:
            studio.runtime.stop()
            studio.runtime.join()
        close_renderer()
        try:
            root.destroy()
        except tk.TclError:
            pass
        synthetic.unlink(missing_ok=True)
        faulthandler.cancel_dump_traceback_later()
    assert all(digest(path) == before for path, before in original.items())
    report = {
        "passed": True,
        "checks": checks,
        "callback_errors": errors,
        "screenshots_captured": screenshots,
        "worker_pids": pids,
        "supplied_recording": supplied,
        "source_files_unchanged": True,
        "owner_camera_opened": False,
        "raw_or_landmark_exports": False,
        "tracking_accuracy_or_performance_qualified": False,
    }
    (destination / "timeline-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/replay-timeline/native"))
    parser.add_argument("--video", type=Path)
    parser.add_argument("--avatar", type=Path)
    arguments = parser.parse_args()
    check(arguments.output, arguments.video, arguments.avatar)
