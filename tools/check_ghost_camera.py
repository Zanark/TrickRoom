"""Render one posed frame from several ghost-camera angles; no camera is opened.

The pose is identical in every shot. Only the viewpoint changes, which is the
whole point of the feature: the capture camera supplies the pose and this camera
decides where it is watched from.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trickroom.assets.gltf import load_asset  # noqa: E402
from trickroom.assets.motion import MotionOptions  # noqa: E402
from trickroom.assets.presentation import camera_batches  # noqa: E402
from trickroom.assets.retarget import AvatarInstance  # noqa: E402
from trickroom.demo import demo_observation  # noqa: E402
from trickroom.ghostcam import GhostCamera, stand_off  # noqa: E402
from trickroom.raster import close_renderer, draw_textured  # noqa: E402
from trickroom.room import camera_room  # noqa: E402

FIXTURE = ROOT / "examples" / "blender" / "TrickRoom-Conformance.glb"
SUBJECT = np.array((0.0, 0.0, 3.0))


def shots(camera: GhostCamera) -> dict[str, tuple]:
    """Positions around a subject standing at SUBJECT, all aimed at its chest."""
    distance = stand_off(camera, subject_height=1.8, fill=0.7)
    chest = SUBJECT + np.array((0.0, 1.25, 0.0))
    return {
        "front": chest + np.array((0.0, 0.0, -distance)),
        "three-quarter": chest + np.array((-distance * 0.7, 0.1, -distance * 0.7)),
        "side": chest + np.array((-distance, 0.0, 0.0)),
        "behind": chest + np.array((0.0, 0.0, distance)),
        "low": chest + np.array((0.0, -1.0, -distance * 0.8)),
        "high": chest + np.array((0.0, 1.9, -distance * 0.8)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avatar", type=Path, default=FIXTURE)
    parser.add_argument("--output", type=Path, default=ROOT / ".local" / "ghost-camera")
    parser.add_argument("--size", type=int, nargs=2, default=(640, 480))
    args = parser.parse_args()

    width, height = args.size
    args.output.mkdir(parents=True, exist_ok=True)
    asset = load_asset(args.avatar)
    instance = AvatarInstance(asset)
    instance.motion.options = MotionOptions(enabled=False)
    state = demo_observation(0.6, 0.6)
    evaluation = instance.evaluate(state, 0.6)

    report = {
        "avatar": asset.name,
        "pose_frames": 1,
        "camera_opened": False,
        "raw_pixels_or_landmarks_saved": False,
        "shots": {},
    }
    images = {}
    try:
        for name, position in shots(GhostCamera()).items():
            camera = GhostCamera(position=position)
            camera.aim_at(SUBJECT + np.array((0.0, 1.25, 0.0)))
            frame = camera_room(camera, width, height).pixels.copy()
            batches = camera_batches(instance, evaluation, camera, width, height, origin=SUBJECT)
            drawn = sum(len(batch.triangles) for batch in batches)
            if batches:
                draw_textured(frame, batches)
            body = ~(
                (
                    (frame[..., 1].astype(int) > frame[..., 2].astype(int) + 6)
                    & (frame[..., 1].astype(int) > frame[..., 0].astype(int) + 6)
                )
                | (frame.max(2) < 40)
            )
            rows = np.where(body.sum(1) > 2)[0]
            path = args.output / f"{name}.png"
            cv2.imwrite(str(path), frame)
            images[name] = frame
            report["shots"][name] = {
                "pose": camera.pose(),
                "triangles_drawn": int(drawn),
                "subject_pixels": int(body.sum()),
                "subject_height_px": int(rows[-1] - rows[0]) if len(rows) else 0,
                "image": path.name,
            }
    finally:
        close_renderer()

    names = list(images)
    distinct = all(
        not np.array_equal(images[a], images[b])
        for i, a in enumerate(names)
        for b in names[i + 1 :]
    )
    report["all_shots_distinct"] = bool(distinct)
    report["shots_with_subject"] = sum(
        1 for shot in report["shots"].values() if shot["triangles_drawn"] > 0
    )
    report["passed"] = bool(distinct and report["shots_with_subject"] == len(names))
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
