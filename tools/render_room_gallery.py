"""Generate deterministic perspective-room visuals and mathematical projection evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from trickroom.cli import save_png
from trickroom.demo import demo_observation
from trickroom.raster import close_renderer
from trickroom.render import Renderer, StageOptions
from trickroom.room import room_background


def generate(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    renderer = Renderer()
    state = demo_observation(0.4, 10)
    cases = (
        ("lab-character", state, (960, 720), StageOptions(), 10),
        ("lab-clean", state, (960, 720), StageOptions(hud=False, head_detail=False), 10),
        ("lab-portrait", state, (720, 960), StageOptions(), 10),
        ("lab-wide", state, (1280, 720), StageOptions(), 10),
        ("lab-cropped", demo_observation(0.4, 10, cropped=True), (960, 720), StageOptions(), 10),
        ("lab-stale", state, (960, 720), StageOptions(), 11),
        ("room-off", state, (960, 720), StageOptions(grid=False), 10),
    )
    try:
        for name, observation, size, options, now in cases:
            save_png(
                destination / f"{name}.png",
                renderer.render(
                    observation,
                    size,
                    now=now,
                    options=options,
                    demo=True,
                ),
            )
        background = room_background(960, 720, False)
        save_png(destination / "lab-empty.png", background.pixels)
        samples = []
        renderer.render(state, now=10)
        for _ in range(30):
            started = time.perf_counter()
            renderer.render(state, now=10)
            samples.append((time.perf_counter() - started) * 1000)
        report = {
            "kind": "synthetic perspective-room gallery; no camera or physical floor calibration",
            "projection": asdict(background.projection),
            "surface_count": 5,
            "theme": "dark-green-wireframe",
            "calibration_crosses": False,
            "shared_vanishing_point": list(background.projection.center),
            "reference_images": [
                {
                    "file": "copilot-image-f214d3.png",
                    "sha256": "654a45bf28717481b0271fe8c3b25e1d76c1b51cbdd4ac12fc9bdd5c7f90ac57",
                },
                {
                    "file": "copilot-image-4f6137.png",
                    "sha256": "650a061152786a5838e5cefa6ccf4584c3dfa15ce9f57ca5c9a09ff44f86fb36",
                },
                {
                    "file": "copilot-image-034535.png",
                    "sha256": "203349f64668558009b631545c8286764956db532c1c9320b38fbaedd0cfb734",
                },
            ],
            "warm_full_renderer_median_ms": round(float(np.median(samples)), 2),
            "warm_full_renderer_p95_ms": round(float(np.percentile(samples, 95)), 2),
            "physical_contact_or_collision": False,
            "owner_visual_approval": False,
            "files": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(destination.glob("*.png"))
            },
        }
        (destination / "room-manifest.json").write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({key: value for key, value in report.items() if key != "files"}, indent=2))
    finally:
        close_renderer()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/images/room"))
    generate(parser.parse_args().output)
