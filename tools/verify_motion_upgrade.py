"""Explicit local-recording comparison: aggregate results and synthetic images only."""

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from trickroom.assets.motion import MotionOptions
from trickroom.assets.retarget import availability, observed_points
from trickroom.camera import CapturedFrame
from trickroom.cli import save_png
from trickroom.models import default_model_directory
from trickroom.raster import close_renderer
from trickroom.render import Renderer
from trickroom.tracking import Tracker


def verify(video: Path, output: Path):
    if not video.is_file():
        raise FileNotFoundError("Supply an explicit existing local recording; no camera is opened.")
    output.mkdir(parents=True, exist_ok=True)
    with video.open("rb") as stream:
        original_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        capture.release()
        raise ValueError("The recording could not be decoded.")
    fps = capture.get(cv2.CAP_PROP_FPS)
    expected = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if not np.isfinite(fps) or fps <= 0 or expected <= 0:
        capture.release()
        raise ValueError("The recording has no usable timing/frame-count metadata.")
    legacy, enhanced = Renderer(), Renderer()
    model = Path("examples/blender/TrickRoom-Conformance.glb")
    for renderer in (legacy, enhanced):
        renderer.load_model(model)
    enhanced.motion_options = MotionOptions(enabled=True, relax_missing=True)
    enhanced.face_response.enabled = True
    snapshots = {round(i * (expected - 1) / 8) for i in range(9)}
    gallery, counts, states = [], Counter(), Counter()
    timings = {"legacy": [], "enhanced": []}
    max_length_error = 0.0
    changing_subframes = 0
    decoded = 0
    tracker = None
    started = time.perf_counter()
    try:
        tracker = Tracker(default_model_directory())
        asset = enhanced.imported.asset
        parents = np.array([n.parent for n in asset.nodes])
        children = np.where(parents >= 0)[0]
        rest_lengths = np.linalg.norm(
            asset.rest_globals[children, :3, 3] - asset.rest_globals[parents[children], :3, 3],
            axis=1,
        )
        while True:
            ok, pixels = capture.read()
            if not ok:
                break
            number, now = decoded, decoded / fps
            decoded += 1
            state = tracker.process(CapturedFrame(decoded, now, pixels))
            raw_joints, raw_face, raw_world = state.joints, state.face, state.world_joints
            counts[state.body_status(now)] += 1
            counts["face_present"] += state.face is not None
            images = []
            for name, renderer in (("legacy", legacy), ("enhanced", enhanced)):
                render_started = time.perf_counter()
                image = renderer.render(state, (640, 480), now=now, connection="REPLAY")
                timings[name].append((time.perf_counter() - render_started) * 1000)
                images.append(image)
            assert (
                state.joints == raw_joints
                and state.face == raw_face
                and state.world_joints == raw_world
            )
            frame = enhanced._imported_frame
            if frame is not None:
                evaluation = frame.evaluation
                assert np.isfinite(evaluation.globals).all()
                lengths = np.linalg.norm(
                    evaluation.globals[children, :3, 3]
                    - evaluation.globals[parents[children], :3, 3],
                    axis=1,
                )
                max_length_error = max(
                    max_length_error, float(np.max(np.abs(lengths - rest_lengths)))
                )
                assert max_length_error < 1e-6
                eligible = availability(state, observed_points(state, "world"))
                for name, status in evaluation.tracking_states.items():
                    if status in ("TRACKED", "REACQUIRING"):
                        assert name in eligible
                    states[status] += 1
                middle = enhanced.imported.evaluate(state, now + 0.5 / fps)
                changing_subframes += not np.allclose(evaluation.globals, middle.globals, atol=1e-6)
                assert len(enhanced.imported.motion.history) <= 8
            if number in snapshots:
                pair = np.hstack(
                    [
                        cv2.resize(image, (480, 360), interpolation=cv2.INTER_AREA)
                        for image in images
                    ]
                )
                cv2.rectangle(pair, (0, 0), (959, 25), (0, 0, 0), -1)
                cv2.putText(
                    pair,
                    f"{now:.1f}s / LEGACY IMAGE RIG | ENHANCED WORLD RIG / synthetic only",
                    (8, 18),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.48,
                    (210, 240, 220),
                    1,
                    cv2.LINE_AA,
                )
                save_png(output / f"comparison-{len(gallery):02}.png", pair)
                gallery.append(cv2.resize(pair, (640, 240), interpolation=cv2.INTER_AREA))
            if decoded % 300 == 0:
                print(f"Compared {decoded}/{expected} frames.", flush=True)
    finally:
        capture.release()
        if tracker is not None:
            tracker.close()
        close_renderer()
    assert decoded == expected, f"Decoded {decoded} of {expected} frames."
    with video.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == original_hash
    if gallery:
        save_png(output / "comparison-sheet.png", np.vstack(gallery))
    report = {
        "recorded_at": datetime.now().astimezone().isoformat(),
        "evidence_class": "every-frame recording comparison on an original technical GLB",
        "source_sha256": original_hash,
        "source_unchanged": True,
        "decoded_frames": decoded,
        "reported_fps": fps,
        "raw_detection_counts": dict(counts),
        "presentation_bone_state_samples": dict(states),
        "max_authored_bone_length_error": max_length_error,
        "changed_pose_between_detection_frames": changing_subframes,
        "render_timings": {
            name: {"mean_ms": float(np.mean(values)), "p95_ms": float(np.percentile(values, 95))}
            for name, values in timings.items()
        },
        "elapsed_seconds": time.perf_counter() - started,
        "passed": True,
        "owner_camera_opened": False,
        "raw_frames_saved": False,
        "landmarks_saved": False,
        "personal_calibration_saved": False,
        "sensing_accuracy_improvement_claimed": False,
        "limitations": [
            "Both modes receive the same detections; this does not measure detector improvement.",
            "Technical conformance GLB is not the final reference-art character.",
            "Enhanced face shaping uses defaults, not an assumed neutral segment of the recording.",
            "Synchronous timing is not camera-to-display latency or production throughput.",
        ],
    }
    (output / "comparison-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(".local/motion-upgrade/recording"))
    args = parser.parse_args()
    verify(args.video, args.output)
