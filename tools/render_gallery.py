"""Generate original, clearly labelled synthetic documentation visuals."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from trickroom.cli import save_png
from trickroom.demo import demo_observation
from trickroom.raster import close_renderer
from trickroom.render import Renderer


def generate(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    renderer = Renderer()
    state = demo_observation(0, 10)
    neutral = replace(state.face, pitch=0, yaw=0, roll=0)
    variants = {
        "01-full-body": (demo_observation(0.7, 10), 10),
        "02-left-wink": (
            replace(
                state,
                face=replace(
                    neutral,
                    expression=replace(neutral.expression, blink_left=1.0),
                ),
            ),
            10,
        ),
        "03-mouth-smile": (
            replace(
                state,
                face=replace(
                    neutral,
                    expression=replace(neutral.expression, jaw_open=0.65, smile=0.75),
                ),
            ),
            10,
        ),
        "04-cropped-legs": (demo_observation(1.1, 10, cropped=True), 10),
        "05-face-unavailable": (replace(state, face=None), 10),
        "06-tracking-stale": (state, 11),
    }
    thumbnails = []
    for name, (observation, now) in variants.items():
        image = renderer.render(observation, now=now, demo=True)
        save_png(directory / f"{name}.png", image)
        thumbnail = cv2.resize(image, (480, 360), interpolation=cv2.INTER_AREA)
        cv2.putText(
            thumbnail,
            name,
            (12, 48),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (225, 232, 232),
            1,
            cv2.LINE_AA,
        )
        thumbnails.append(thumbnail)
    sheet = np.vstack([np.hstack(thumbnails[:3]), np.hstack(thumbnails[3:])])
    save_png(directory / "tracking-contact-sheet.png", sheet)
    frames = []
    for i in range(64):
        observation = demo_observation(i / 16, 10)
        frame = renderer.render(observation, (640, 480), now=10, demo=True)
        frames.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
    frames[0].save(
        directory / "tracking-demo.gif",
        save_all=True,
        append_images=frames[1:],
        duration=62,
        loop=0,
        optimize=False,
    )
    files = [*sorted(directory.glob("*.png")), directory / "tracking-demo.gif"]
    manifest = {
        "kind": "synthetic-renderer-demo-not-camera-validation",
        "source": "tools/render_gallery.py and src/trickroom/demo.py",
        "raw_camera_pixels": False,
        "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/images"))
    try:
        generate(parser.parse_args().output)
    finally:
        close_renderer()
