"""Verify actual Blender exports through numerical deformation and the TrickRoom renderer."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from trickroom.assets.animation import deform, global_transforms, sample_clip
from trickroom.assets.gltf import load_asset
from trickroom.assets.retarget import AvatarInstance
from trickroom.cli import save_png
from trickroom.demo import demo_observation
from trickroom.raster import close_renderer, renderer_info
from trickroom.render import Renderer
from trickroom.state import Expression


def verify(output: Path, samples: Path):
    output.mkdir(parents=True, exist_ok=True)
    model = Path("examples/blender/TrickRoom-Conformance.glb")
    asset = load_asset(model)
    renderer = Renderer()
    renderer.set_model(AvatarInstance(asset))
    report = {
        "recorded_at": datetime.now().astimezone().isoformat(),
        "asset": asset.report(),
        "owner_camera_opened": False,
        "actual_exporter": "Blender4.5.14",
        "checks": {},
        "images": {},
    }
    try:
        poses = [
            ("bind", "bind", demo_observation(0, 10), 10),
            ("live-wave", "live", demo_observation(1, 10), 10),
            ("live-cropped", "live", demo_observation(1, 10, cropped=True), 10),
            ("face-unavailable", "live", replace(demo_observation(1, 10), face=None), 10),
            ("stale", "live", demo_observation(0, 10), 11),
            ("clip-wave", "ConformanceWave", None, 10.5),
            ("clip-face", "ConformanceFace", None, 10.5),
        ]
        neutral = demo_observation(0, 10)
        for name, expression in (
            ("blink-left", Expression(blink_left=1)),
            ("blink-right", Expression(blink_right=1)),
            ("mouth", Expression(jaw_open=1, smile=0.5)),
            ("brows-gaze", Expression(brow_left=0.8, brow_right=0.7, gaze_x=0.8)),
        ):
            poses.append(
                (
                    name,
                    "live",
                    replace(neutral, face=replace(neutral.face, expression=expression)),
                    10,
                )
            )
        images = []
        for name, mode, state, now in poses:
            renderer.imported.set_mode(mode, 10)
            frame = renderer.render(state, now=now, demo=mode == "live")
            save_png(output / f"{name}.png", frame)
            report["images"][name] = hashlib.sha256(
                (output / f"{name}.png").read_bytes()
            ).hexdigest()
            thumb = cv2.resize(frame, (480, 360), interpolation=cv2.INTER_AREA)
            cv2.putText(thumb, name, (12, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 230, 230), 1)
            images.append(thumb)
        while len(images) % 3:
            images.append(np.zeros_like(images[0]))
        save_png(
            output / "contact-sheet.png",
            np.vstack([np.hstack(images[i : i + 3]) for i in range(0, len(images), 3)]),
        )
        if not samples.is_file():
            raise FileNotFoundError(
                "Run Blender sample_conformance.py before numerical verification."
            )
        source = json.loads(samples.read_text())
        bind = np.asarray(source["samples"]["bind"])
        rest = deform(asset, asset.rest_globals, {})
        mapping = []
        for primitive in rest:
            distance = np.linalg.norm(primitive.positions[:, None, :] - bind[None, :, :], axis=2)
            ids = distance.argmin(axis=1)
            assert np.max(distance[np.arange(len(ids)), ids]) < 1e-5
            mapping.append(ids)
        errors = {}
        for clip_name in ("ConformanceWave", "ConformanceFace"):
            clip = next(c for c in asset.clips if c.name == clip_name)
            overrides, weights = sample_clip(clip, 0.5, loop=False)
            current = deform(asset, global_transforms(asset, overrides), weights)
            expected = np.asarray(source["samples"][clip_name])
            error = max(
                float(np.max(np.linalg.norm(p.positions - expected[ids], axis=1)))
                for p, ids in zip(current, mapping, strict=True)
            )
            errors[clip_name] = error
            assert error < 2e-4, f"Runtime differs from Blender for {clip_name}: {error}"
        report["checks"]["blender_vertex_max_error"] = errors
        renderer.imported.set_mode("live", 10)
        timings = []
        for i in range(40):
            state = demo_observation(i / 30, 10 + i / 30)
            start = time.perf_counter()
            renderer.render(state, now=state.captured_at, demo=True)
            timings.append((time.perf_counter() - start) * 1000)
        report["checks"]["live_full_render_median_ms"] = float(np.median(timings))
        report["checks"]["live_full_render_p95_ms"] = float(np.percentile(timings, 95))
        eye_model = Path("examples/blender/TrickRoom-EyeBones.glb")
        eyes = load_asset(eye_model, eye_model.with_suffix(".trickroom.json"))
        instance = AvatarInstance(eyes)
        center = demo_observation(0, 10)
        gaze = replace(
            center, face=replace(center.face, expression=Expression(gaze_x=0.9, gaze_y=0.3))
        )
        a, b = instance.evaluate(center, 10), instance.evaluate(gaze, 10)
        changed = max(
            float(np.max(np.linalg.norm(x.positions - y.positions, axis=1)))
            for x, y in zip(a.primitives, b.primitives, strict=True)
        )
        assert changed > 0.005
        report["checks"]["bone_gaze_vertex_motion"] = changed
        report["graphics"] = renderer_info()
        report["passed"] = True
        (output / "blender-runtime-report.json").write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps({k: v for k, v in report.items() if k not in ("images", "asset")}, indent=2)
        )
    finally:
        close_renderer()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/blender-conformance"))
    parser.add_argument(
        "--samples", type=Path, default=Path(".local/blender-conformance/blender-samples.json")
    )
    args = parser.parse_args()
    verify(args.output, args.samples)
