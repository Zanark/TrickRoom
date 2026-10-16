"""Drive the ghost camera through real Tk pointer events in a real window.

The focused tests inject look deltas directly, which cannot catch a binding
attached to the wrong widget. This exercises the actual click and motion path.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trickroom.models import default_model_directory  # noqa: E402
from trickroom.studio import Studio  # noqa: E402


def check(destination: Path) -> dict:
    root = tk.Tk()
    errors: list[str] = []
    root.report_callback_exception = lambda kind, value, tb: errors.append(
        f"{kind.__name__}: {value}"
    )
    studio = Studio(root, default_model_directory(), demo=True)

    def pump(seconds: float = 0.3) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            root.update()
            time.sleep(0.008)

    report: dict = {"camera_opened": False, "groups": []}
    try:
        pump(0.8)
        studio.sections["08 / GHOST CAMERA"].set_expanded(True)
        studio.ghost_enabled.set(True)
        studio.toggle_ghost_camera()
        pump(0.3)

        stage = studio.preview
        report["stage_size"] = [stage.winfo_width(), stage.winfo_height()]

        # A real click on the stage label, not a direct method call.
        stage.event_generate("<Button-1>", x=stage.winfo_width() // 2, y=stage.winfo_height() // 2)
        pump(0.2)
        report["captured_by_real_click"] = bool(studio._ghost_captured)
        report["groups"].append("click-on-stage-captures-pointer")

        centre = studio._stage_centre()
        report["stage_centre"] = list(centre) if centre else None

        before = studio.ghost_camera.yaw
        for _ in range(8):
            stage.event_generate("<Motion>", x=centre[0] + 40, y=centre[1])
            pump(0.05)
        turned = studio.ghost_camera.yaw
        report["yaw_before"] = round(before, 3)
        report["yaw_after_motion"] = round(turned, 3)
        report["real_motion_turns_camera"] = abs(turned - before) > 1.0
        report["groups"].append("real-motion-events-turn-the-camera")

        # Keep pushing the same direction: with warping this must keep turning
        # well past the point where a cursor would have hit the stage edge.
        # 0.066 degrees per count, so a full circle needs about 5450 px of
        # motion. The cursor would leave a 1017 px stage long before that
        # without warping, which is exactly what this is checking.
        steps, push = 120, 80
        total = 0.0
        previous = studio.ghost_camera.yaw
        for _ in range(steps):
            stage.event_generate("<Motion>", x=centre[0] + push, y=centre[1])
            pump(0.02)
            current = studio.ghost_camera.yaw
            step = (current - previous + 540) % 360 - 180
            total += step
            previous = current
        report["pointer_travel_px"] = steps * push
        report["stage_width_px"] = stage.winfo_width()
        report["accumulated_yaw_degrees"] = round(total, 1)
        report["turns_past_one_full_circle"] = abs(total) > 360.0
        report["groups"].append("warped-pointer-allows-unlimited-yaw")

        pitch_before = studio.ghost_camera.pitch
        for _ in range(40):
            stage.event_generate("<Motion>", x=centre[0], y=centre[1] - 60)
            pump(0.02)
        report["pitch_after_pushing_up"] = round(studio.ghost_camera.pitch, 3)
        report["pitch_clamped"] = studio.ghost_camera.pitch <= 89.0001
        report["pitch_moved"] = studio.ghost_camera.pitch > pitch_before
        report["groups"].append("pitch-clamps-short-of-the-pole")

        root.event_generate("<Escape>")
        pump(0.3)
        report["released_by_escape"] = not studio._ghost_captured
        report["still_connected_after_escape"] = True
        report["groups"].append("escape-releases-pointer-before-disconnecting")
    finally:
        studio.close()
        pump(0.6)
        try:
            root.destroy()
        except tk.TclError:
            pass

    report["callback_errors"] = errors
    report["passed"] = bool(
        report.get("captured_by_real_click")
        and report.get("real_motion_turns_camera")
        and report.get("turns_past_one_full_circle")
        and report.get("pitch_clamped")
        and report.get("pitch_moved")
        and report.get("released_by_escape")
        and not errors
    )
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "ghost-input.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local" / "ghost-input")
    raise SystemExit(0 if check(parser.parse_args().output)["passed"] else 1)
