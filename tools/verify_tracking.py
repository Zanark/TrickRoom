"""Explicit public-fixture inference check; stores only aggregate evidence and synthetic images."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from trickroom.camera import CapturedFrame
from trickroom.cli import save_png
from trickroom.models import default_model_directory
from trickroom.raster import close_renderer
from trickroom.render import Renderer, StageOptions
from trickroom.tracking import Tracker

FIXTURE_URL = "https://storage.googleapis.com/mediapipe-assets/pose.jpg"
FIXTURE_SHA256 = "c8a830ed683c0276d713dd5aeda28f415f10cd6291972084a40d0d8b934ed62b"
FRONT_URL = "https://cdn.pixabay.com/photo/2019/03/12/20/39/girl-4051811_960_720.jpg"
FRONT_SHA256 = "99e0649aa4f2553b0213982f544146565a1028877c4bb9fbe3884453659d8cdc"


def run(destination: Path, download: bool) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    decoded = {}
    for filename, url, digest in (
        ("pose.jpg", FIXTURE_URL, FIXTURE_SHA256),
        ("fitness.jpg", FRONT_URL, FRONT_SHA256),
    ):
        fixture = destination / filename
        if download and not fixture.exists():
            with urllib.request.urlopen(url, timeout=20) as response:
                fixture.write_bytes(response.read(2 * 1024 * 1024))
        if not fixture.is_file():
            raise FileNotFoundError("Use --download-fixture to fetch the public test assets.")
        if hashlib.sha256(fixture.read_bytes()).hexdigest() != digest:
            raise ValueError("Public fixture checksum mismatch.")
        decoded[filename] = cv2.imdecode(
            np.frombuffer(fixture.read_bytes(), np.uint8),
            cv2.IMREAD_COLOR,
        )
        if decoded[filename] is None:
            raise ValueError("Public fixture did not decode.")
    image = decoded["pose.jpg"]
    front = decoded["fitness.jpg"]
    h, w = image.shape[:2]
    cases = {
        "full-body-profile": image,
        "body-and-expressive-face": front,
        "cropped-lower-legs": image[: round(h * 0.79)].copy(),
        "portrait-frame": image[:, round(w * 0.27) : round(w * 0.73)].copy(),
        "blank": np.zeros_like(image),
    }
    report = {
        "recorded_at": datetime.now().astimezone().isoformat(),
        "evidence_class": "actual-model inference on a public still and deterministic crops",
        "fixtures": [
            {"url": FIXTURE_URL, "sha256": FIXTURE_SHA256},
            {"url": FRONT_URL, "sha256": FRONT_SHA256},
        ],
        "input_media_in_report": False,
        "owner_camera_tested": False,
        "real_motion_or_end_to_end_latency_measured": False,
        "cases": {},
    }
    renderer = Renderer()
    for name, pixels in cases.items():
        tracker = Tracker(default_model_directory())
        results, timings = [], []
        try:
            for number in range(16):
                frame = CapturedFrame(number + 1, time.perf_counter(), pixels)
                observation = tracker.process(frame)
                results.append(observation)
                timings.append(observation.inference_ms)
            state = results[-1]
            if name in ("full-body-profile", "body-and-expressive-face"):
                assert state.visible_joints >= 25, "Expected positive full-body detection."
                if name == "body-and-expressive-face":
                    assert state.face is not None, (
                        "Expected face detection inside the body-guided crop."
                    )
                assert state.contours, "Expected a segmentation-derived outline."
                assert len(state.world_joints) == 33
            elif name == "cropped-lower-legs":
                assert state.visible_joints >= 12
                assert state.joint(27) is None and state.joint(28) is None
                assert state.body_status(state.completed_at) == "PARTIAL BODY"
            elif name == "portrait-frame":
                assert state.visible_joints >= 10
            elif name == "blank":
                assert not state.joints and state.face is None and not state.contours
            output = renderer.render(
                state,
                now=state.completed_at,
                options=StageOptions(mirror=False),
            )
            save_png(destination / f"{name}-synthetic.png", output)
            report["cases"][name] = {
                "frames": len(results),
                "input_size": list(state.frame_size),
                "visible_landmarks": state.visible_joints,
                "face_frames": sum(s.face is not None for s in results),
                "body_frames": sum(s.visible_joints >= 4 for s in results),
                "contours": len(state.contours),
                "face_crop_used": state.face.crop_used if state.face else False,
                "status": state.body_status(state.completed_at),
                "warm_mean_inference_ms": round(statistics.mean(timings[1:]), 2),
                "warm_p95_inference_ms": round(float(np.percentile(timings[1:], 95)), 2),
                "synthetic_image": f"{name}-synthetic.png",
                "passed": True,
            }
        finally:
            tracker.close()
    tracker = Tracker(default_model_directory())
    try:
        sequence = 0

        def repeat(pixels, count=10):
            nonlocal sequence
            for _ in range(count):
                sequence += 1
                observed = tracker.process(CapturedFrame(sequence, time.perf_counter(), pixels))
            return observed

        before = repeat(front)
        moved_pixels = cv2.warpAffine(
            front,
            np.float32(((1, 0, 35), (0, 1, 0))),
            (front.shape[1], front.shape[0]),
        )
        moved = repeat(moved_pixels)
        assert before.face is not None and moved.face is not None
        assert before.joint(11) is not None and moved.joint(11) is not None
        body_shift = (moved.joint(11).x - before.joint(11).x) * front.shape[1]
        face_shift = (moved.face.center.x - before.face.center.x) * front.shape[1]
        assert 10 < body_shift < 65, f"Body did not follow translated input: {body_shift}"
        assert 10 < face_shift < 65, f"Face did not follow translated input: {face_shift}"
        blank = repeat(np.zeros_like(front), 4)
        assert not blank.joints and blank.face is None
        reacquired = repeat(front, 8)
        assert reacquired.face is not None and reacquired.visible_joints >= 20
        report["same_session_motion_and_reacquisition"] = {
            "kind": "deterministic image translation, not a real motion recording",
            "translated_input_px": 35,
            "observed_body_shift_px": round(body_shift, 2),
            "observed_face_shift_px": round(face_shift, 2),
            "blank_clears_tracking": True,
            "body_and_face_reacquired": True,
            "passed": True,
        }
    finally:
        tracker.close()
    (destination / "inference-report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/verification"))
    parser.add_argument("--download-fixture", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.output, args.download_fixture), indent=2))
    finally:
        close_renderer()
