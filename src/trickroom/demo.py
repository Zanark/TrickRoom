"""Deterministic synthetic motion, always labelled as demonstration rather than inference."""

from __future__ import annotations

import math
from dataclasses import replace

from trickroom.state import Expression, Face, Observation, Point


def demo_observation(t: float, now: float, *, cropped: bool = False) -> Observation:
    sway = math.sin(t * 0.8) * 0.028
    bob = math.sin(t * 1.6) * 0.008
    points = [Point(0.5 + sway, 0.16 + bob) for _ in range(33)]
    coordinates = {
        0: (0.50, 0.158),
        1: (0.525, 0.140),
        2: (0.536, 0.138),
        3: (0.547, 0.140),
        4: (0.475, 0.140),
        5: (0.464, 0.138),
        6: (0.453, 0.140),
        7: (0.565, 0.155),
        8: (0.435, 0.155),
        9: (0.519, 0.188),
        10: (0.481, 0.188),
        11: (0.630, 0.285),
        12: (0.370, 0.285),
        13: (0.725, 0.395),
        14: (0.275, 0.395),
        15: (0.77, 0.510),
        16: (0.23, 0.510),
        17: (0.785, 0.540),
        18: (0.215, 0.540),
        19: (0.805, 0.538),
        20: (0.195, 0.538),
        21: (0.793, 0.515),
        22: (0.207, 0.515),
        23: (0.586, 0.545),
        24: (0.414, 0.545),
        25: (0.603, 0.730),
        26: (0.397, 0.730),
        27: (0.612, 0.907),
        28: (0.388, 0.907),
        29: (0.598, 0.927),
        30: (0.402, 0.927),
        31: (0.660, 0.946),
        32: (0.340, 0.946),
    }
    wave = max(0.0, math.sin(t * 1.15))
    for index, (x, y) in coordinates.items():
        if index in (13, 15, 17, 19, 21):
            factor = 0.35 if index == 13 else 1.0
            y -= wave * 0.34 * factor
            x += wave * 0.035
        points[index] = Point(
            x + sway,
            (y + bob) / (0.79 if cropped else 1.0),
            -0.06 * wave if index in (15, 17, 19, 21) else 0.0,
        )
        if index in (29, 30, 31, 32):
            points[index] = replace(points[index], z=-0.10 if index in (31, 32) else 0.02)
    blink = max(0.0, 1.0 - abs((t % 4.0) - 2.0) / 0.12)
    wink = max(0.0, 1.0 - abs((t % 7.0) - 4.5) / 0.22)
    face = Face(
        Point(0.5 + sway, (0.158 + bob) / (0.79 if cropped else 1.0)),
        0.132,
        0.142 / (0.79 if cropped else 1.0),
        math.sin(t * 0.7) * 13.0,
        math.sin(t * 0.9) * 32.0,
        math.sin(t) * 7.0,
        Expression(
            max(blink, wink),
            blink,
            max(0.0, math.sin(t * 3)) * 0.45,
            0.35 + math.sin(t * 0.6) * 0.25,
            math.sin(t * 0.8) * 0.35,
            math.sin(t * 0.8 + 0.5) * 0.3,
            math.sin(t) * 0.25,
            math.sin(t * 0.6) * 0.15,
        ),
    )
    outline_indices = (
        8,
        12,
        14,
        16,
        20,
        18,
        14,
        24,
        26,
        28,
        32,
        30,
        28,
        26,
        24,
        23,
        25,
        27,
        29,
        31,
        27,
        25,
        23,
        13,
        17,
        19,
        15,
        13,
        11,
        7,
    )
    contour = []
    for i, index in enumerate(outline_indices):
        p = points[index]
        edge = 0.025 if p.x >= 0.5 + sway else -0.025
        if 12 <= i <= 18:
            edge *= -1
        contour.append(replace(p, x=p.x + edge))
    return Observation(
        int(t * 30) + 1,
        now,
        now,
        (900, 1200),
        tuple(points),
        tuple(
            replace(
                p,
                x=(p.x - 0.5 - sway) * 1.8,
                y=(p.y - (points[23].y + points[24].y) / 2) * 2.4,
                z=p.z * 1.8,
            )
            for p in points
        ),
        face,
        (tuple(contour),),
        0.0,
    )
