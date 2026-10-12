"""Private opt-in visual diagnostics. Nothing here feeds the avatar renderer or exports."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from trickroom.camera import CapturedFrame
from trickroom.state import BODY_CONNECTIONS, Observation

TITLES = {
    "input": "TrickRoom - PRIVATE raw input",
    "skeleton": "TrickRoom - Detected skeleton",
    "face": "TrickRoom - Detected face mesh",
}
HEAD_LINKS = ((8, 6), (6, 5), (5, 4), (4, 0), (0, 1), (1, 2), (2, 3), (3, 7), (9, 10))


def _canvas(size):
    width, height = size
    if not 320 <= width <= 1920 or not 240 <= height <= 1440:
        raise ValueError("Debug window size must be within 320x240 and1920x1440.")
    return np.zeros((height, width, 3), np.uint8)


def _label(image, title, subtitle):
    cv2.putText(
        image, title, (16, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (100, 220, 240), 1, cv2.LINE_AA
    )
    cv2.putText(
        image,
        subtitle,
        (16, image.shape[0] - 15),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.39,
        (170, 170, 170),
        1,
        cv2.LINE_AA,
    )


def _waiting(image, title, subtitle):
    _label(image, title, subtitle)
    cv2.putText(
        image,
        "NO CURRENT DETECTION / INPUT",
        (20, image.shape[0] // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.53,
        (190, 190, 190),
        1,
        cv2.LINE_AA,
    )
    return image


def raw_input(frame: CapturedFrame | None, size, now: float):
    image = _canvas(size)
    subtitle = "PRIVATE / unmirrored input / not exported"
    if frame is None or now - frame.captured_at > 0.6:
        return _waiting(image, "PRIVATE RAW INPUT", subtitle)
    height, width = frame.image.shape[:2]
    scale = min((size[0] - 24) / width, (size[1] - 76) / height)
    target = max(1, round(width * scale)), max(1, round(height * scale))
    pixels = cv2.resize(frame.image, target, interpolation=cv2.INTER_AREA)
    x, y = (size[0] - target[0]) // 2, 40 + (size[1] - 76 - target[1]) // 2
    image[y : y + target[1], x : x + target[0]] = pixels
    _label(image, f"PRIVATE RAW INPUT / FRAME {frame.sequence}", subtitle)
    return image


def skeleton(state: Observation | None, size, now: float, *, paused: bool = False):
    image = _canvas(size)
    subtitle = "Input coordinates / unmirrored / no camera pixels"
    if paused and state is not None and state.media_time is not None:
        now = state.completed_at
        subtitle = "PAUSED REPLAY / unmirrored / no camera pixels"
    if state is None or state.age(now) > 0.6 or not state.joints:
        return _waiting(image, "SKELETON / BLACK", subtitle)
    source_w, source_h = state.frame_size
    scale = min((size[0] - 40) / source_w, (size[1] - 80) / source_h)
    ox = (size[0] - source_w * scale) / 2
    oy = 40 + (size[1] - 80 - source_h * scale) / 2
    points = {
        index: (round(ox + point.x * source_w * scale), round(oy + point.y * source_h * scale))
        for index in range(len(state.joints))
        if (point := state.joint(index)) is not None
    }
    for a, b in (*BODY_CONNECTIONS, *HEAD_LINKS):
        if a in points and b in points:
            cv2.line(image, points[a], points[b], (215, 215, 215), 2, cv2.LINE_AA)
    for index, xy in points.items():
        tint = (160, 240, 180) if index % 2 else (235, 170, 220)
        cv2.circle(image, xy, 3, tint, -1, cv2.LINE_AA)
    _label(image, f"SKELETON / FRAME {state.sequence} / {len(points)}/33", subtitle)
    return image


@lru_cache(maxsize=1)
def face_connections():
    data = json.loads(Path(__file__).with_name("face_topology.json").read_text(encoding="utf-8"))
    result = tuple(
        tuple(tuple(edge) for edge in data[name]) for name in ("mesh", "contours", "irises")
    )
    if not all(
        len(edge) == 2 and all(type(i) is int and 0 <= i < 478 for i in edge)
        for edges in result
        for edge in edges
    ):
        raise ValueError("Packaged face connectivity is invalid.")
    return result


def face_mesh(state: Observation | None, size, now: float, *, paused: bool = False):
    image = _canvas(size)
    subtitle = "Detected points / unmirrored / no camera pixels"
    if paused and state is not None and state.media_time is not None:
        now = state.completed_at
        subtitle = "PAUSED REPLAY / unmirrored / no camera pixels"
    if (
        state is None
        or state.age(now) > 0.6
        or state.face is None
        or len(state.face.landmarks) < 468
    ):
        return _waiting(image, "FACE MESH / BLACK", subtitle)
    points = np.array(
        [(p.x * state.frame_size[0], p.y * state.frame_size[1]) for p in state.face.landmarks]
    )
    if not np.isfinite(points).all():
        return _waiting(image, "FACE MESH / INVALID POINTS", subtitle)
    low, high = points.min(axis=0), points.max(axis=0)
    dimensions = np.maximum(high - low, 1)
    scale = min((size[0] - 64) / dimensions[0], (size[1] - 100) / dimensions[1])
    center = (low + high) / 2
    screen = np.rint((points - center) * scale + (size[0] / 2, size[1] / 2 + 2)).astype(np.int32)
    for edges, tint in zip(
        face_connections(), ((85, 100, 90), (150, 230, 180), (235, 180, 95)), strict=True
    ):
        for a, b in edges:
            if max(a, b) < len(screen):
                cv2.line(image, tuple(screen[a]), tuple(screen[b]), tint, 1, cv2.LINE_AA)
    for xy in screen:
        cv2.circle(image, tuple(xy), 1, (200, 210, 200), -1)
    _label(image, f"FACE MESH / FRAME {state.sequence} / {len(points)} POINTS", subtitle)
    return image
