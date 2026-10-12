"""Reference-driven, landmark-posed low-poly parts with object-space color texture."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from numpy.typing import NDArray

from trickroom.raster import draw_depth
from trickroom.state import Expression, Face


def color(hex_value: str) -> tuple[int, int, int]:
    value = hex_value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (4, 2, 0))


PALETTE = {
    "skin": color("ce955f"),
    "skin_shadow": color("a56c44"),
    "stubble": color("715039"),
    "eye": color("231c19"),
    "hair": color("2c2324"),
    "hair_light": color("453332"),
    "hoodie": color("2e2c2f"),
    "hoodie_dark": color("232226"),
    "hoodie_seam": color("3c383b"),
    "drawstring": color("9e9280"),
    "cargo": color("5b603d"),
    "cargo_dark": color("42492f"),
    "cargo_flap": color("6c6d46"),
    "headphones": color("b9aa93"),
    "headphone_rim": color("d4bea0"),
    "padding": color("302e2c"),
    "shoe": color("a99882"),
    "shoe_panel": color("71695f"),
    "sole": color("cdb89d"),
}


@dataclass(frozen=True, slots=True)
class Mesh:
    vertices: NDArray[np.float64]
    triangles: NDArray[np.int32]
    colors: NDArray[np.uint8]

    def transform(self, basis: NDArray[np.float64], origin: NDArray[np.float64]) -> Mesh:
        return Mesh(self.vertices @ basis.T + origin, self.triangles, self.colors)


class Builder:
    def __init__(self, seed: int = 0) -> None:
        self.vertices: list = []
        self.triangles: list = []
        self.colors: list = []
        self.rng = np.random.default_rng(seed)

    def triangle(self, a, b, c, tint) -> None:
        offset = len(self.vertices)
        self.vertices.extend((a, b, c))
        self.triangles.append((offset, offset + 1, offset + 2))
        self.colors.append(tint)

    def quad(self, a, b, c, d, tint, grid=(1, 1), variation: float = 0.0) -> None:
        a, b, c, d = (np.asarray(p, dtype=float) for p in (a, b, c, d))
        columns, rows = grid
        for row in range(rows):
            v1, v2 = row / rows, (row + 1) / rows
            left1, right1 = a * (1 - v1) + d * v1, b * (1 - v1) + c * v1
            left2, right2 = a * (1 - v2) + d * v2, b * (1 - v2) + c * v2
            for column in range(columns):
                u1, u2 = column / columns, (column + 1) / columns
                p = left1 * (1 - u1) + right1 * u1
                q = left1 * (1 - u2) + right1 * u2
                r = left2 * (1 - u2) + right2 * u2
                s = left2 * (1 - u1) + right2 * u1
                gain = 1.0 + self.rng.uniform(-variation, variation)
                shade = tuple(int(np.clip(channel * gain, 0, 255)) for channel in tint)
                self.triangle(p, q, r, shade)
                self.triangle(p, r, s, shade)

    def box(self, low, high, tint, grid=(1, 1), variation=0.0) -> None:
        x1, y1, z1 = low
        x2, y2, z2 = high
        self.quad((x1, y1, z2), (x2, y1, z2), (x2, y2, z2), (x1, y2, z2), tint, grid, variation)
        self.quad((x2, y1, z1), (x1, y1, z1), (x1, y2, z1), (x2, y2, z1), tint, grid, variation)
        self.quad(
            (x2, y1, z2), (x2, y1, z1), (x2, y2, z1), (x2, y2, z2), tint, (1, grid[1]), variation
        )
        self.quad(
            (x1, y1, z1), (x1, y1, z2), (x1, y2, z2), (x1, y2, z1), tint, (1, grid[1]), variation
        )
        self.quad((x1, y1, z1), (x2, y1, z1), (x2, y1, z2), (x1, y1, z2), tint)
        self.quad((x1, y2, z2), (x2, y2, z2), (x2, y2, z1), (x1, y2, z1), tint)

    def prism(self, rings, tint, grid=(3, 8), variation=0.0, offset=(0, 0, 0)) -> None:
        shape = (
            (-0.78, 1),
            (0.78, 1),
            (1, 0.65),
            (1, -0.65),
            (0.78, -1),
            (-0.78, -1),
            (-1, -0.65),
            (-1, 0.65),
        )
        vertices = [
            np.array([(x * rx, y, z * rz) for x, z in shape]) + offset for y, rx, rz in rings
        ]
        span = max(0.01, rings[-1][0] - rings[0][0])
        for index in range(len(vertices) - 1):
            top, bottom = vertices[index : index + 2]
            rows = max(1, round(grid[1] * (rings[index + 1][0] - rings[index][0]) / span))
            for side in range(8):
                nxt = (side + 1) % 8
                columns = grid[0] if side in (0, 4) else max(1, grid[0] // 2)
                self.quad(
                    top[side], top[nxt], bottom[nxt], bottom[side], tint, (columns, rows), variation
                )
        for end, reverse in ((vertices[0], True), (vertices[-1], False)):
            center = end.mean(axis=0)
            for index in range(8):
                a, b = end[index], end[(index + 1) % 8]
                self.triangle(center, b if reverse else a, a if reverse else b, tint)

    def wedge(self, points, tint) -> None:
        points = np.asarray(points, float)
        center = points.mean(axis=0)
        for indices in ((0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0)):
            a, b, c = points[list(indices)]
            normal = np.cross(b - a, c - a)
            if np.dot(normal, (a + b + c) / 3 - center) < 0:
                b, c = c, b
            self.triangle(a, b, c, tint)

    def build(self) -> Mesh:
        return Mesh(
            np.asarray(self.vertices, np.float64).reshape(-1, 3),
            np.asarray(self.triangles, np.int32).reshape(-1, 3),
            np.asarray(self.colors, np.uint8).reshape(-1, 3),
        )


def combine(meshes: list[Mesh]) -> Mesh:
    if not meshes:
        return Builder().build()
    offsets = np.cumsum([0] + [len(mesh.vertices) for mesh in meshes[:-1]])
    return Mesh(
        np.vstack([mesh.vertices for mesh in meshes]),
        np.vstack([mesh.triangles + offset for mesh, offset in zip(meshes, offsets, strict=True)]),
        np.vstack([mesh.colors for mesh in meshes]),
    )


def rasterize(image: NDArray[np.uint8], mesh: Mesh) -> int:
    if len(mesh.triangles) == 0:
        return 0
    faces = mesh.vertices[mesh.triangles]
    normals = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    visible = (normals[:, 2] > 0.01) & (lengths > 0.01)
    visible &= faces[:, :, 0].max(axis=1) >= 0
    visible &= faces[:, :, 0].min(axis=1) < image.shape[1]
    visible &= faces[:, :, 1].max(axis=1) >= 0
    visible &= faces[:, :, 1].min(axis=1) < image.shape[0]
    indices = np.flatnonzero(visible)
    if len(indices) == 0:
        return 0
    light = np.array((-0.35, -0.45, 0.82))
    light /= np.linalg.norm(light)
    illumination = 0.77 + 0.27 * np.maximum(0, (normals[indices] / lengths[indices, None]) @ light)
    illumination = np.round(illumination * 16) / 16
    colors = np.clip(mesh.colors[indices] * illumination[:, None], 0, 255).astype(np.uint8)
    draw_depth(image, faces[indices], colors)
    return len(indices)


@lru_cache(maxsize=1)
def head_geometry() -> Mesh:
    b = Builder(310)
    b.prism(
        ((-0.58, 0.47, 0.43), (-0.38, 0.53, 0.48), (0.43, 0.49, 0.46), (0.60, 0.37, 0.38)),
        PALETTE["skin"],
        (6, 8),
        0.035,
        (0, 0, 0.09),
    )
    # Stepped jaw shading, not a painted-on mouth or a captured face texture.
    for x, y in (
        (-0.43, 0.32),
        (0.43, 0.32),
        (-0.35, 0.46),
        (0.35, 0.46),
        (-0.245, 0.555),
        (-0.147, 0.57),
        (-0.049, 0.575),
        (0.049, 0.575),
        (0.147, 0.57),
        (0.245, 0.555),
    ):
        z = 0.578
        b.quad(
            (x - 0.038, y - 0.024, z),
            (x + 0.038, y - 0.024, z),
            (x + 0.038, y + 0.029, z),
            (x - 0.038, y + 0.029, z),
            PALETTE["stubble"],
        )
    b.box((-0.025, 0.085, 0.57), (0.040, 0.18, 0.625), PALETTE["skin_shadow"])
    return b.build()


@lru_cache(maxsize=1)
def hair_geometry() -> Mesh:
    b = Builder(73)
    rings = []
    for row, (rx, rz) in enumerate(((0.35, 0.32), (0.65, 0.57), (0.64, 0.57))):
        ring = []
        for i in range(12):
            angle = i * math.tau / 12
            y = (-0.90, -0.59, -0.03 - 0.53 * math.cos(angle))[row]
            y += (i % 3 - 1) * 0.035
            ring.append((math.sin(angle) * rx, y, math.cos(angle) * rz - 0.10))
        rings.append(ring)
    for row in range(2):
        for i in range(12):
            nxt = (i + 1) % 12
            b.quad(
                rings[row][i],
                rings[row][nxt],
                rings[row + 1][nxt],
                rings[row + 1][i],
                PALETTE["hair"],
                variation=0.20,
            )
    for i in range(12):
        b.triangle(
            (0, -1.01, -0.12),
            rings[0][(i + 1) % 12],
            rings[0][i],
            PALETTE["hair_light"] if i % 4 == 0 else PALETTE["hair"],
        )
    spikes = (
        ((-0.58, -0.57, 0.48), (-0.22, -0.80, 0.61), (-0.71, -0.24, 0.59), (-0.41, -0.48, 0.31)),
        ((-0.43, -0.75, 0.56), (-0.05, -0.81, 0.69), (-0.32, 0.055, 0.73), (-0.36, -0.35, 0.34)),
        ((-0.21, -0.83, 0.64), (0.20, -0.79, 0.62), (0.075, -0.18, 0.81), (0.04, -0.54, 0.36)),
        ((0.10, -0.79, 0.59), (0.55, -0.60, 0.46), (0.39, 0.05, 0.70), (0.31, -0.33, 0.30)),
        ((0.46, -0.57, 0.39), (0.67, -0.31, 0.25), (0.55, 0.27, 0.43), (0.42, -0.09, 0.08)),
        ((-0.61, -0.36, 0.30), (-0.47, -0.38, 0.38), (-0.55, 0.27, 0.44), (-0.43, -0.02, 0.06)),
        ((-0.39, -0.84, 0.14), (-0.04, -0.92, 0.25), (-0.57, -1.005, 0.23), (-0.28, -0.66, -0.13)),
        ((-0.15, -0.92, 0.02), (0.21, -0.84, 0.25), (0.34, -1.015, 0.12), (0.04, -0.70, -0.26)),
        ((0.37, -0.74, -0.27), (0.57, -0.50, -0.23), (0.78, -0.68, -0.32), (0.40, -0.49, 0.0)),
        (
            (-0.54, -0.56, -0.22),
            (-0.43, -0.34, -0.45),
            (-0.77, -0.56, -0.25),
            (-0.31, -0.46, -0.02),
        ),
        ((-0.34, -0.75, 0.38), (0.06, -0.84, 0.45), (-0.08, -1.01, 0.57), (-0.12, -0.56, 0.20)),
        ((0.02, -0.82, 0.31), (0.46, -0.69, 0.26), (0.61, -0.88, 0.36), (0.25, -0.54, 0.07)),
        ((-0.61, -0.51, 0.06), (-0.37, -0.69, 0.32), (-0.84, -0.78, 0.19), (-0.32, -0.44, -0.1)),
    )
    for i, spike in enumerate(spikes):
        b.wedge(spike, PALETTE["hair_light"] if i in (2, 6, 8) else PALETTE["hair"])
    for i in range(4, 9):
        angle = i * math.tau / 12
        x, z = math.sin(angle) * 0.56, math.cos(angle) * 0.58 - 0.1
        b.wedge(
            (
                (x - 0.16, 0.02, z),
                (x + 0.14, -0.08, z),
                (x + 0.02, 0.47 + (i % 2) * 0.08, z + 0.02),
                (x, 0.03, z + 0.16),
            ),
            PALETTE["hair"],
        )
    return b.build()


@lru_cache(maxsize=1)
def headphones_geometry() -> Mesh:
    b = Builder(99)
    for sign in (-1, 1):
        rings = []
        for x, ry, rz in (
            (0.59, 0.265, 0.215),
            (0.70, 0.30, 0.24),
            (0.83, 0.28, 0.225),
            (0.91, 0.235, 0.19),
            (0.924, 0.19, 0.15),
        ):
            rings.append(
                [
                    (
                        sign * x,
                        0.015 + math.sin(i * math.tau / 8 + math.pi / 8) * ry,
                        math.cos(i * math.tau / 8 + math.pi / 8) * rz,
                    )
                    for i in range(8)
                ]
            )
        for row in range(len(rings) - 1):
            tint = (
                PALETTE["padding"]
                if row == 0
                else PALETTE["headphone_rim"]
                if row == 2
                else PALETTE["headphones"]
            )
            for i in range(8):
                nxt = (i + 1) % 8
                points = (rings[row][i], rings[row][nxt], rings[row + 1][nxt], rings[row + 1][i])
                if sign > 0:
                    points = points[::-1]
                b.quad(*points, tint)
        for i in range(8):
            a, c = rings[-1][i], rings[-1][(i + 1) % 8]
            b.triangle(
                (sign * 0.925, 0.015, 0),
                c if sign > 0 else a,
                a if sign > 0 else c,
                PALETTE["headphones"],
            )
    for i in range(10):
        a, c = i * math.pi / 10, (i + 1) * math.pi / 10
        pa = np.array((0.81 * math.cos(a), -0.96 * math.sin(a) - 0.06, -0.10))
        pc = np.array((0.81 * math.cos(c), -0.96 * math.sin(c) - 0.06, -0.10))
        outward_a = np.array((math.cos(a), -math.sin(a), 0)) * 0.052
        outward_c = np.array((math.cos(c), -math.sin(c), 0)) * 0.052
        depth = np.array((0, 0, 0.085))
        b.quad(
            pa + outward_a + depth,
            pc + outward_c + depth,
            pc + outward_c - depth,
            pa + outward_a - depth,
            PALETTE["headphone_rim"],
        )
        b.quad(
            pa + depth,
            pc + depth,
            pc + outward_c + depth,
            pa + outward_a + depth,
            PALETTE["headphones"],
        )
        b.quad(
            pa - depth,
            pa + outward_a - depth,
            pc + outward_c - depth,
            pc - depth,
            PALETTE["headphones"],
        )
    return b.build()


def expression_geometry(expression: Expression | None) -> Mesh:
    b = Builder()
    ex = expression or Expression(blink_left=1, blink_right=1)
    for x, blink, brow in (
        (0.225, ex.blink_left, ex.brow_left),
        (-0.225, ex.blink_right, ex.brow_right),
    ):
        x += ex.gaze_x * 0.035
        y = -0.075 + ex.gaze_y * 0.025
        half_height = max(0.009, 0.108 * (1 - min(1, blink * 1.55)))
        half_width = 0.075 if blink > 0.55 else 0.034
        b.quad(
            (x - half_width, y - half_height, 0.586),
            (x + half_width, y - half_height, 0.586),
            (x + half_width, y + half_height, 0.586),
            (x - half_width, y + half_height, 0.586),
            PALETTE["eye"],
        )
        by = -0.245 - brow * 0.10
        b.quad(
            (x - 0.085, by - 0.012, 0.588),
            (x + 0.075, by - 0.020, 0.588),
            (x + 0.075, by + 0.004, 0.588),
            (x - 0.085, by + 0.012, 0.588),
            PALETTE["stubble"],
        )
    jaw = min(1, ex.jaw_open * 1.8)
    half_width = 0.10 + ex.smile * 0.10
    corner = 0.30 - ex.smile * 0.048
    bottom = 0.315 + jaw * 0.16
    b.quad(
        (-half_width, corner, 0.591),
        (half_width, corner, 0.591),
        (half_width * 0.75, bottom, 0.591),
        (-half_width * 0.75, bottom, 0.591),
        PALETTE["eye"] if jaw > 0.1 else PALETTE["stubble"],
    )
    if jaw > 0.35:
        b.quad(
            (-half_width * 0.42, bottom - 0.035, 0.593),
            (half_width * 0.42, bottom - 0.035, 0.593),
            (half_width * 0.42, bottom - 0.012, 0.593),
            (-half_width * 0.42, bottom - 0.012, 0.593),
            color("ac7559"),
        )
    return b.build()


@dataclass(frozen=True)
class HeadPlacement:
    center: tuple[float, float, float]
    width: float
    height: float
    face: Face | None
    roll: float = 0.0


def posed_head(placement: HeadPlacement) -> Mesh:
    face = placement.face
    pitch, yaw, roll = (face.pitch, face.yaw, face.roll) if face else (0, 0, placement.roll)
    pitch, yaw, roll = map(math.radians, (-pitch, yaw, -roll))
    cp, sp, cy, sy, cr, sr = (
        math.cos(pitch),
        math.sin(pitch),
        math.cos(yaw),
        math.sin(yaw),
        math.cos(roll),
        math.sin(roll),
    )
    rotation = (
        np.array(((cr, -sr, 0), (sr, cr, 0), (0, 0, 1)))
        @ np.array(((cy, 0, sy), (0, 1, 0), (-sy, 0, cy)))
        @ np.array(((1, 0, 0), (0, cp, -sp), (0, sp, cp)))
    )
    scale = np.diag((placement.width / 1.4, placement.height / 1.8, placement.width / 1.4))
    skin = head_geometry()
    if face is None:
        muted = (skin.colors * 0.68 + np.array((35, 35, 29))).clip(0, 255).astype(np.uint8)
        skin = Mesh(skin.vertices, skin.triangles, muted)
    model = combine(
        [
            skin,
            hair_geometry(),
            headphones_geometry(),
            expression_geometry(face.expression if face else None),
        ]
    )
    return model.transform(scale @ rotation, np.asarray(placement.center))


def draw_head(
    image: NDArray[np.uint8],
    center: tuple[float, float],
    width: float,
    height: float,
    face: Face | None,
    *,
    pose_roll: float = 0.0,
) -> None:
    rasterize(image, posed_head(HeadPlacement((*center, 0), width, height, face, pose_roll)))


@lru_cache(maxsize=16)
def garment(name: str) -> Mesh:
    b = Builder(sum(map(ord, name)))
    if name == "torso":
        b.prism(
            (
                (-0.035, 0.48, 0.20),
                (0.07, 0.55, 0.24),
                (0.36, 0.51, 0.23),
                (0.83, 0.50, 0.23),
                (1.06, 0.55, 0.25),
                (1.12, 0.53, 0.235),
            ),
            PALETTE["hoodie"],
            (7, 11),
            0.14,
        )
        b.prism(((1.025, 0.545, 0.25), (1.13, 0.54, 0.25)), PALETTE["hoodie_dark"], (9, 2), 0.12)
        b.quad(
            (-0.29, 0.65, 0.262),
            (0.29, 0.65, 0.262),
            (0.38, 0.97, 0.275),
            (-0.38, 0.97, 0.275),
            PALETTE["hoodie_seam"],
            (7, 5),
            0.10,
        )
        b.quad(
            (-0.255, 0.70, 0.267),
            (0.255, 0.70, 0.267),
            (0.33, 0.94, 0.282),
            (-0.33, 0.94, 0.282),
            PALETTE["hoodie"],
            (6, 4),
            0.12,
        )
        for sign in (-1, 1):
            x = sign * 0.14
            b.box(
                (x - 0.025, 0.015, 0.252),
                (x + 0.025, 0.40, 0.275),
                PALETTE["drawstring"],
                (1, 5),
                0.12,
            )
            b.box((x - 0.023, 0.37, 0.276), (x + 0.023, 0.43, 0.29), PALETTE["shoe_panel"])
            b.wedge(
                (
                    (sign * 0.43, -0.045, 0.20),
                    (sign * 0.15, -0.19, 0.09),
                    (0, 0.11, 0.28),
                    (sign * 0.25, 0.04, 0.33),
                ),
                PALETTE["hoodie_dark"],
            )
        # The hood is authored on the back as well, rather than a front-only costume.
        b.wedge(
            ((-0.34, -0.13, -0.21), (0.34, -0.13, -0.21), (0, 0.40, -0.31), (0, 0.055, -0.43)),
            PALETTE["hoodie_dark"],
        )
        b.wedge(
            ((-0.27, -0.08, -0.235), (0.27, -0.08, -0.235), (0, 0.29, -0.37), (0, 0.025, -0.45)),
            PALETTE["hoodie"],
        )
    elif name in ("upper_sleeve", "lower_sleeve"):
        if name == "upper_sleeve":
            rings = (
                (-0.10, 0.165, 0.155),
                (0.20, 0.178, 0.16),
                (0.90, 0.15, 0.14),
                (1.10, 0.145, 0.135),
            )
        else:
            rings = (
                (-0.08, 0.155, 0.145),
                (0.45, 0.145, 0.135),
                (0.89, 0.125, 0.12),
                (1.02, 0.115, 0.11),
            )
        b.prism(rings, PALETTE["hoodie"], (3, 6), 0.14)
        if name == "lower_sleeve":
            b.prism(
                ((0.86, 0.127, 0.12), (1.035, 0.117, 0.113)), PALETTE["hoodie_dark"], (4, 3), 0.18
            )
    elif name in ("left_thigh", "right_thigh"):
        b.prism(
            ((-0.08, 0.245, 0.18), (0.20, 0.255, 0.185), (0.78, 0.24, 0.17), (1.09, 0.25, 0.175)),
            PALETTE["cargo"],
            (4, 8),
            0.15,
        )
        sign = 1 if name == "left_thigh" else -1
        center = sign * 0.17
        b.box(
            (center - 0.105, 0.35, 0.135),
            (center + 0.105, 0.81, 0.222),
            PALETTE["cargo_dark"],
            (3, 5),
            0.14,
        )
        b.box(
            (center - 0.12, 0.32, 0.21),
            (center + 0.12, 0.44, 0.253),
            PALETTE["cargo_flap"],
            (3, 2),
            0.09,
        )
        b.box((center - 0.013, 0.402, 0.254), (center + 0.013, 0.425, 0.258), PALETTE["cargo_dark"])
    elif name == "trouser_shin":
        b.prism(
            (
                (-0.10, 0.25, 0.18),
                (0.17, 0.24, 0.17),
                (0.78, 0.27, 0.19),
                (0.93, 0.295, 0.19),
                (1.00, 0.225, 0.16),
            ),
            PALETTE["cargo"],
            (4, 8),
            0.17,
        )
        b.prism(((0.93, 0.247, 0.175), (1.015, 0.22, 0.155)), PALETTE["cargo_dark"], (5, 2), 0.10)
    elif name == "waist":
        b.box((-0.49, -0.02, -0.185), (0.49, 0.16, 0.185), PALETTE["cargo_dark"], (7, 2), 0.10)
    elif name == "hand":
        b.prism(
            ((0, 0.082, 0.065), (0.60, 0.09, 0.06), (1, 0.075, 0.05)),
            PALETTE["skin"],
            (2, 2),
            0.025,
        )
    elif name == "neck":
        b.prism(((0, 0.095, 0.075), (1, 0.085, 0.07)), PALETTE["skin_shadow"])
    elif name == "shoe":
        b.box((-0.205, 0.04, -0.28), (0.205, 0.14, 0.36), PALETTE["sole"], (5, 2), 0.035)
        b.box((-0.204, 0.135, -0.28), (0.204, 0.158, 0.36), PALETTE["shoe_panel"])
        b.box((-0.16, -0.19, -0.23), (0.16, 0.045, 0.10), PALETTE["shoe"], (4, 3), 0.09)
        b.box((-0.19, -0.055, 0.08), (0.19, 0.045, 0.33), PALETTE["sole"], (5, 2), 0.07)
        b.quad(
            (-0.16, -0.19, 0.075),
            (0.16, -0.19, 0.075),
            (0.19, -0.055, 0.30),
            (-0.19, -0.055, 0.30),
            PALETTE["shoe"],
            (4, 4),
            0.07,
        )
        for sign in (-1, 1):
            x = sign * 0.162
            for z in (-0.13, -0.015):
                points = (
                    (x, -0.18, z),
                    (x, -0.16, z + 0.055),
                    (x, 0.035, z + 0.10),
                    (x, 0.035, z + 0.035),
                )
                if sign > 0:
                    points = points[::-1]
                b.quad(*points, PALETTE["shoe_panel"])
        for i in range(4):
            z = -0.08 + i * 0.064
            y = -0.198 + max(0, z - 0.05) * 0.55
            b.box((-0.105, y - 0.013, z), (0.105, y, z + 0.022), PALETTE["sole"])
    else:
        raise ValueError(f"Unknown avatar part: {name}")
    return b.build()


def unit(vector: NDArray[np.float64], fallback: NDArray[np.float64]) -> NDArray[np.float64]:
    length = float(np.linalg.norm(vector))
    return vector / length if length > 1e-6 else fallback.copy()


def limb_frame(a, b, preferred_front, preferred_side) -> NDArray[np.float64]:
    down = unit(b - a, np.array((0.0, 1.0, 0.0)))
    front = preferred_front - down * np.dot(preferred_front, down)
    if np.linalg.norm(front) < 0.05:
        side = unit(preferred_side - down * np.dot(preferred_side, down), np.array((1.0, 0.0, 0.0)))
        front = unit(np.cross(side, down), np.array((0.0, 0.0, 1.0)))
    else:
        front = unit(front, np.array((0.0, 0.0, 1.0)))
        side = unit(np.cross(down, front), np.array((1.0, 0.0, 0.0)))
    return np.column_stack((side, down, front))


@dataclass(frozen=True)
class Footprint:
    """Projected shoe bounds, not measured physical floor contact."""

    center: tuple[float, float]
    width: float


def character_mesh(
    positions: dict[int, NDArray[np.float64]],
    head: HeadPlacement | None,
    fallback_width: float,
    *,
    footprints: list[Footprint] | None = None,
) -> Mesh:
    meshes: list[Mesh] = []
    side = np.array((1.0, 0.0, 0.0))
    down = np.array((0.0, 1.0, 0.0))
    front = np.array((0.0, 0.0, 1.0))
    shoulder_width = fallback_width
    if 11 in positions and 12 in positions:
        shoulder_vector = positions[11] - positions[12]
        shoulder_width = float(np.linalg.norm(shoulder_vector))
        side = unit(shoulder_vector, side)
    shoulder_width = max(12, min(fallback_width * 2.8, shoulder_width))
    if all(i in positions for i in (11, 12, 23, 24)):
        shoulders = (positions[11] + positions[12]) / 2
        hips = (positions[23] + positions[24]) / 2
        torso_length = float(np.linalg.norm(hips - shoulders))
        down = unit(hips - shoulders, down)
        side = unit(side - down * np.dot(side, down), side)
        front = unit(np.cross(side, down), front)
        basis = np.column_stack(
            (side * shoulder_width, down * torso_length, front * shoulder_width)
        )
        meshes.append(garment("torso").transform(basis, shoulders))
        meshes.append(garment("waist").transform(basis, hips))
    for a, b, name in (
        (23, 25, "left_thigh"),
        (24, 26, "right_thigh"),
        (25, 27, "trouser_shin"),
        (26, 28, "trouser_shin"),
        (11, 13, "upper_sleeve"),
        (12, 14, "upper_sleeve"),
        (13, 15, "lower_sleeve"),
        (14, 16, "lower_sleeve"),
    ):
        if a not in positions or b not in positions:
            continue
        start, end = positions[a], positions[b]
        basis = limb_frame(start, end, front, side)
        basis = basis @ np.diag((shoulder_width, np.linalg.norm(end - start), shoulder_width))
        meshes.append(garment(name).transform(basis, start))
    for wrist, elbow, index, pinky in ((15, 13, 19, 17), (16, 14, 20, 18)):
        if wrist not in positions:
            continue
        a = positions[wrist]
        if index in positions and pinky in positions:
            end = (positions[index] + positions[pinky]) / 2
        elif elbow in positions:
            end = a + unit(a - positions[elbow], down) * shoulder_width * 0.20
        else:
            continue
        basis = limb_frame(a, end, front, side)
        length = max(shoulder_width * 0.15, min(shoulder_width * 0.28, np.linalg.norm(end - a)))
        meshes.append(
            garment("hand").transform(basis @ np.diag((shoulder_width, length, shoulder_width)), a)
        )
    for ankle, toe, heel in ((27, 31, 29), (28, 32, 30)):
        if ankle not in positions or toe not in positions:
            continue
        origin = positions[ankle]
        direction = positions[toe] - positions.get(heel, origin)
        forward = unit(direction - down * np.dot(direction, down), front)
        right = unit(np.cross(down, forward), side)
        shoe_down = unit(np.cross(forward, right), down)
        basis = np.column_stack((right, shoe_down, forward)) * shoulder_width
        shoe = garment("shoe").transform(basis, origin + down * shoulder_width * 0.12)
        meshes.append(shoe)
        if footprints is not None:
            low, high = shoe.vertices.min(axis=0), shoe.vertices.max(axis=0)
            footprints.append(
                Footprint(
                    (float((low[0] + high[0]) / 2), float(high[1])),
                    float(high[0] - low[0]),
                )
            )
    if head is not None:
        if 11 in positions and 12 in positions:
            shoulders = (positions[11] + positions[12]) / 2
            neck_end = np.asarray(head.center) + np.array((0, head.height * 0.27, 0))
            basis = limb_frame(shoulders, neck_end, front, side)
            basis = basis @ np.diag(
                (shoulder_width, np.linalg.norm(neck_end - shoulders), shoulder_width)
            )
            meshes.append(garment("neck").transform(basis, shoulders))
        meshes.append(posed_head(head))
    return combine(meshes)


def draw_character(
    image: NDArray[np.uint8],
    positions: dict[int, NDArray[np.float64]],
    head: HeadPlacement | None,
    fallback_width: float,
) -> int:
    return rasterize(image, character_mesh(positions, head, fallback_width))
