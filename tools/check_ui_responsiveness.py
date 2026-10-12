"""Measure queued Tk timeline input in native Studio with explicitly selected local files."""

from __future__ import annotations

import argparse
import faulthandler
import hashlib
import json
import queue
import threading
import time
import tkinter as tk
from pathlib import Path

import numpy as np

from trickroom.camera import Source
from trickroom.models import default_model_directory
from trickroom.raster import close_renderer
from trickroom.studio import Studio


def distribution(values):
    assert values, "No native samples were collected."
    return dict(
        zip(("median", "p95", "max"), np.percentile(values, (50, 95, 100)).tolist(), strict=True)
    )


def check(video: Path, avatar: Path | None, output: Path, measure_only: bool) -> None:
    originals = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (video, avatar, avatar.with_suffix(".trickroom.json") if avatar else None)
        if path is not None and path.is_file()
    }
    root = tk.Tk()
    studio = Studio(root, default_model_directory(), demo=True)
    root.geometry("1380x920")
    callbacks, reports, posts, delays, beats, renders = [], [], {}, [], [], []
    posting_errors = []
    pointer_events = queue.Queue(maxsize=82)
    timers = {}
    active = False
    producer = None
    producer_stop = threading.Event()
    errors = []
    root.report_callback_exception = lambda kind, value, tb: errors.append(
        f"{kind.__name__}: {value}"
    )
    faulthandler.dump_traceback_later(180, exit=True)
    original_render = studio.renderer.render
    original_seek = studio.seek_playback

    def render(*args, **kwargs):
        started = time.perf_counter()
        result = original_render(*args, **kwargs)
        if active:
            renders.append((time.perf_counter() - started) * 1000)
        return result

    def seek(seconds):
        callbacks.append(seconds)
        return original_seek(seconds)

    studio.renderer.render = render
    studio.seek_playback = seek

    def pump(seconds=0.05):
        until = time.perf_counter() + seconds
        while time.perf_counter() < until:
            root.update()
            time.sleep(0.002)
        assert not errors, errors
        assert not posting_errors, posting_errors
        if studio.runtime is not None:
            assert studio.runtime.status.state != "ERROR", studio.runtime.status.message

    def wait(predicate, label, timeout=25):
        until = time.perf_counter() + timeout
        while not predicate() and time.perf_counter() < until:
            pump()
        assert predicate(), {
            "check": label,
            "handled": len(delays),
            "seeks": len(callbacks),
            "scrubbing": studio._scrubbing,
            "runtime_state": studio.runtime.status.state if studio.runtime else None,
        }

    def heartbeat(expected):
        if active:
            beats.append(max(0, time.perf_counter() - expected) * 1000)
        if not studio._closing:
            timers["heartbeat"] = root.after(16, heartbeat, time.perf_counter() + 0.016)

    def drag(event):
        sent = posts.get(event.x)
        if active and sent is not None:
            delays.append((time.perf_counter() - sent) * 1000)
        return studio._drag_playback(event)

    def dispatch_input():
        while True:
            try:
                sequence, x, y = pointer_events.get_nowait()
            except queue.Empty:
                break
            slider.event_generate(sequence, x=x, y=y)
        if not studio._closing:
            timers["input"] = root.after(8, dispatch_input)

    def post_drag(width, height):
        try:
            y = height // 2
            xs = np.linspace(24, round(width * 0.7), 80).astype(int)
            posts[int(xs[0])] = time.perf_counter()
            pointer_events.put_nowait(("<ButtonPress-1>", int(xs[0]), y))
            for value in xs[1:]:
                if producer_stop.wait(0.025):
                    return
                x = int(value)
                posts[x] = time.perf_counter()
                pointer_events.put_nowait(("<B1-Motion>", x, y))
            pointer_events.put_nowait(("<ButtonRelease-1>", int(xs[-1]), y))
        except queue.Full:
            posting_errors.append("The bounded authored-input queue overflowed.")

    try:
        pump(0.25)
        if avatar is not None:
            studio.load_model(avatar)
            wait(lambda: not studio._model_pending, "The selected GLB did not finish loading.")
            assert studio.renderer.imported is not None
        studio._start_source(Source.parse(str(video)), start_position=18, paused=True)
        wait(
            lambda: (
                studio.runtime.status.state == "PAUSED"
                and str(studio.playback_button["state"]) == "normal"
            ),
            "The selected recording did not become ready.",
        )
        studio.open_output()
        for name in ("skeleton", "face"):
            studio.debug_options[name].set(True)
            studio.toggle_debug(name)
        pump(0.4)
        slider = studio.playback_slider
        slider.bind("<ButtonPress-1>", drag)
        slider.bind("<B1-Motion>", drag)
        slider.focus_force()
        timers["heartbeat"] = root.after(16, heartbeat, time.perf_counter() + 0.016)
        timers["input"] = root.after(8, dispatch_input)
        for name, paused in (("paused", True), ("playing", False)):
            if studio.runtime.camera.status.paused != paused:
                studio.toggle_playback()
                wait(
                    lambda expected=paused: studio.runtime.camera.status.paused == expected,
                    "Playback mode was not acknowledged.",
                )
            pump(0.25)
            callbacks.clear()
            posts.clear()
            delays.clear()
            beats.clear()
            renders.clear()
            generation = studio.runtime.camera.status.generation
            active = True
            producer = threading.Thread(
                target=post_drag,
                args=(slider.winfo_width(), slider.winfo_height()),
                name="owned-window-pointer-input",
                daemon=True,
            )
            producer.start()
            wait(
                lambda current=producer: not current.is_alive(),
                "Native input producer did not stop.",
                12,
            )
            wait(lambda: len(callbacks) == 1, "The native drag did not commit one seek.", 5)
            active = False
            producer.join()
            assert not studio._scrubbing
            assert len(callbacks) == 1
            assert len(delays) >= 5, (
                "Too few native pointer events reached the actual drag handler."
            )
            wait(
                lambda expected=generation + 1: (
                    studio.runtime.observation is not None
                    and studio.runtime.observation.generation == expected
                ),
                "The requested seek did not produce a new observation.",
            )
            assert not studio.debug_options["input"].get() and studio.runtime.input_preview is None
            report = {
                "mode": name,
                "posted_pointer_positions": len(posts),
                "handled_pointer_positions": len(delays),
                "input_delivery_ms": distribution(delays),
                "heartbeat_lateness_ms": distribution(beats),
                "avatar_render_ms": distribution(renders),
                "seek_commands": len(callbacks),
                "new_seek_generation_received": True,
            }
            reports.append(report)
        studio.disconnect()
        wait(lambda: studio.runtime is None, "Replay did not disconnect.")
        for timer in timers.values():
            root.after_cancel(timer)
        timers.clear()
        studio.close()
        root.update()
    finally:
        active = False
        studio.render_worker.close()
        studio.render_worker.join(6)
        assert not studio.render_worker.alive
        producer_stop.set()
        for timer in timers.values():
            root.after_cancel(timer)
        if producer is not None:
            producer.join(1)
        if studio.runtime is not None:
            studio.runtime.stop()
            studio.runtime.join()
        close_renderer()
        try:
            root.destroy()
        except tk.TclError:
            pass
        faulthandler.cancel_dump_traceback_later()
    assert all(
        hashlib.sha256(path.read_bytes()).hexdigest() == old for path, old in originals.items()
    )
    passed = all(
        report["input_delivery_ms"]["p95"] <= 50
        and report["input_delivery_ms"]["max"] <= 150
        and report["heartbeat_lateness_ms"]["p95"] <= 50
        for report in reports
    )
    result = {
        "measurement_only": measure_only,
        "input_method": (
            "Background-timestamped synthetic Tk events dispatched on the UI thread; "
            "not physical input latency."
        ),
        "responsiveness_budget_passed": passed,
        "input_budget_ms": {"p95": 50, "max": 150},
        "heartbeat_p95_budget_ms": 50,
        "phases": reports,
        "callback_errors": errors,
        "source_files_unchanged": True,
        "real_camera_opened": False,
        "raw_input_enabled": False,
        "tracking_accuracy_qualified": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "native-input.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not measure_only:
        assert passed, "Native input exceeded the declared responsiveness budget."


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--avatar", type=Path)
    parser.add_argument("--output", type=Path, default=Path(".local/ui-responsiveness/current"))
    parser.add_argument("--measure-only", action="store_true")
    arguments = parser.parse_args()
    check(arguments.video, arguments.avatar, arguments.output, arguments.measure_only)
