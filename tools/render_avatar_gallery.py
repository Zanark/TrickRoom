"""Reference-avatar turnarounds use authored poses, never claimed live rear-face tracking."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from trickroom.avatar import PALETTE, HeadPlacement, character_mesh, color
from trickroom.cli import save_png
from trickroom.demo import demo_observation
from trickroom.raster import close_renderer, renderer_info
from trickroom.render import Renderer, StageOptions, draw_head
from trickroom.state import Expression, Point


def turnaround(yaw: float):
    state = demo_observation(0, 10)
    points = list(state.joints)
    for index, x, y in (
        (13, 0.76, 0.29),
        (15, 0.895, 0.30),
        (17, 0.955, 0.31),
        (19, 0.96, 0.295),
        (21, 0.945, 0.28),
        (14, 0.24, 0.29),
        (16, 0.105, 0.30),
        (18, 0.045, 0.31),
        (20, 0.04, 0.295),
        (22, 0.055, 0.28),
    ):
        points[index] = Point(x, y)
    angle = math.radians(yaw)
    rotation = np.array(
        ((math.cos(angle), 0, math.sin(angle)), (0, 1, 0), (-math.sin(angle), 0, math.cos(angle)))
    )
    transformed = []
    for point in points:
        xyz = rotation @ np.array(((point.x - 0.5) * 900, (point.y - 0.5) * 1200, -point.z * 900))
        transformed.append(
            replace(point, x=xyz[0] / 900 + 0.5, y=xyz[1] / 1200 + 0.5, z=-xyz[2] / 900)
        )
    face = replace(state.face, yaw=yaw, pitch=0, roll=0, expression=Expression())
    return replace(state, joints=tuple(transformed), contours=(), face=face)


def build(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    renderer = Renderer()
    options = StageOptions(
        mirror=False, outline=False, skeleton=False, grid=False, head_detail=False, hud=False
    )
    angles = (
        ("front", 0),
        ("front-three-quarter", 40),
        ("left-side", 90),
        ("back", 180),
        ("right-side", -90),
        ("back-three-quarter", -140),
    )
    bodies, heads = [], []
    for label, angle in angles:
        state = turnaround(angle)
        body = renderer.render(state, (480, 680), now=10, options=options)
        cv2.putText(
            body,
            label.upper().replace("-", " "),
            (18, 652),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            color("d1c8b7"),
            1,
            cv2.LINE_AA,
        )
        save_png(directory / f"body-{label}.png", body)
        bodies.append(body)
        head = np.full((320, 300, 3), color("131c25"), np.uint8)
        draw_head(head, (150, 163), 173, 213, state.face)
        cv2.putText(
            head,
            label.upper().replace("-", " "),
            (14, 299),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            color("d1c8b7"),
            1,
            cv2.LINE_AA,
        )
        heads.append(head)
    body_sheet = np.hstack(bodies)
    save_png(directory / "reference-turnaround.png", body_sheet)
    save_png(directory / "head-turnaround.png", np.hstack(heads))
    expression_images = []
    base = turnaround(0)
    for label, expression in (
        ("NEUTRAL", Expression()),
        ("LEFT WINK", Expression(blink_left=1)),
        ("RIGHT WINK", Expression(blink_right=1)),
        ("BLINK", Expression(blink_left=1, blink_right=1)),
        ("TALK / SMILE", Expression(jaw_open=0.7, smile=0.8)),
        ("BROWS / GAZE", Expression(brow_left=0.8, brow_right=0.7, gaze_x=0.6)),
    ):
        frame = np.full((320, 300, 3), color("131c25"), np.uint8)
        draw_head(frame, (150, 163), 173, 213, replace(base.face, expression=expression))
        cv2.putText(
            frame, label, (14, 299), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color("d1c8b7"), 1, cv2.LINE_AA
        )
        expression_images.append(frame)
    save_png(directory / "reference-expressions.png", np.hstack(expression_images))
    positions = {
        i: np.array((p.x * 900, p.y * 1200, -p.z * 900))
        for i, p in enumerate(base.joints)
        if p.usable()
    }
    mesh = character_mesh(positions, HeadPlacement((450, 230, 0), 174, 218, base.face), 234)
    timings = []
    for _ in range(30):
        start = time.perf_counter()
        renderer.render(base, now=10)
        timings.append((time.perf_counter() - start) * 1000)
    report = {
        "kind": "authored-poses-not-live-camera-validation",
        "geometry": {
            "vertices": len(mesh.vertices),
            "triangles": len(mesh.triangles),
            "note": "Includes coplanar material tiles; not the sheet's illustrative counts.",
        },
        "warm_renderer_median_ms": round(float(np.median(timings)), 2),
        "warm_renderer_p95_ms": round(float(np.percentile(timings, 95)), 2),
        "palette_bgr": PALETTE,
        "files": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.glob("*.png"))
        },
        "owner_visual_approval": False,
        "renderer": renderer_info(),
    }
    (directory / "avatar-manifest.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key not in ("files", "palette_bgr")},
            indent=2,
        )
    )
    close_renderer()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/images/avatar"))
    build(parser.parse_args().output)
