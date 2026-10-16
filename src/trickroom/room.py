"""A pinhole-projected synthetic calibration room, not a reconstructed physical room."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
from numpy.typing import NDArray

from trickroom.avatar import Footprint, color

GRID_COLOR = color("29b535")
BORDER_COLOR = color("2dc83d")
PANEL_COLORS = {
    "floor": color("0d2118"),
    "ceiling": color("0a1a12"),
    "left": color("0c1c14"),
    "right": color("0a1912"),
    "back": color("0c1b13"),
}


@dataclass(frozen=True)
class RoomProjection:
    width: int
    height: int
    top: int
    bottom: int
    focal: float
    center: tuple[float, float]
    half_width: float = 3.0
    ceiling: float = 3.6
    eye_height: float = 1.65
    near: float = 0.6
    back: float = 8.4
    tile: float = 0.6

    @classmethod
    def for_stage(cls, width: int, height: int, hud: bool) -> RoomProjection:
        if width < 64 or height < 128:
            raise ValueError("The room requires a nonzero, usable stage.")
        top, bottom = (46, height - 34) if hud else (0, height)
        usable_height = bottom - top
        focal = min(width * 0.9, usable_height * 1.2)
        return cls(width, height, top, bottom, focal, ((width - 1) / 2, top + usable_height * 0.43))

    def project(self, points) -> NDArray[np.float64]:
        xyz = np.asarray(points, dtype=float).reshape(-1, 3)
        if not np.isfinite(xyz).all() or np.any(xyz[:, 2] <= 0):
            raise ValueError("Room points must be finite and in front of the camera.")
        result = np.empty((len(xyz), 2), dtype=float)
        result[:, 0] = self.center[0] + self.focal * xyz[:, 0] / xyz[:, 2]
        result[:, 1] = self.center[1] - self.focal * (xyz[:, 1] - self.eye_height) / xyz[:, 2]
        return result

    def floor_point(self, pixel: tuple[float, float]) -> NDArray[np.float64] | None:
        """Intersect a presentation ray with the decorative floor; not a contact estimate."""
        x, y = pixel
        if not math.isfinite(x + y) or not (0 <= x < self.width and self.top <= y < self.bottom):
            return None
        if y <= self.center[1]:
            return None
        depth = self.focal * self.eye_height / (y - self.center[1])
        world_x = (x - self.center[0]) * depth / self.focal
        if not self.near <= depth <= self.back or abs(world_x) > self.half_width:
            return None
        return np.array((world_x, 0.0, depth))


@dataclass(frozen=True)
class CameraProjection:
    """Project the room through a movable camera instead of the fixed stage view.

    This mirrors RoomProjection's interface so the same surface definitions can
    be drawn either way. Points at or behind the near plane are returned as NaN
    rather than raising, because a free camera routinely puts part of the room
    behind itself; callers skip those polygons.
    """

    camera: object
    width: int
    height: int
    top: int = 0
    bottom: int = 0
    half_width: float = 3.0
    ceiling: float = 3.6
    near: float = 0.6
    back: float = 8.4
    tile: float = 0.6

    def project(self, points) -> NDArray[np.float64]:
        from trickroom.ghostcam import project_to_screen

        screen, valid = project_to_screen(points, self.camera, self.width, self.height)
        result = screen[:, :2].copy()
        result[~valid] = np.nan
        return result


def _visible(polygon: NDArray[np.float64], width: int, height: int) -> bool:
    """Reject polygons that cross the near plane or sit far outside the frame."""
    if not np.isfinite(polygon).all():
        return False
    margin = max(width, height) * 4
    return bool(
        polygon[:, 0].max() > -margin
        and polygon[:, 0].min() < width + margin
        and polygon[:, 1].max() > -margin
        and polygon[:, 1].min() < height + margin
    )


@dataclass(frozen=True)
class RoomBackground:
    pixels: NDArray[np.uint8]
    floor_mask: NDArray[np.uint8]
    projection: RoomProjection


def _shade(tint, amount):
    return tuple(int(np.clip(channel * amount, 0, 255)) for channel in tint)


def _surface(image, projection: RoomProjection, origin, u_axis, v_axis, u_size, v_size, tint):
    origin, u_axis, v_axis = (np.asarray(value, dtype=float) for value in (origin, u_axis, v_axis))
    us = np.linspace(0, u_size, round(u_size / projection.tile) + 1)
    vs = np.linspace(0, v_size, round(v_size / projection.tile) + 1)

    def world(u, v):
        return origin + u_axis * u + v_axis * v

    for row in range(len(vs) - 1):
        for column in range(len(us) - 1):
            u1, u2 = us[column : column + 2]
            v1, v2 = vs[row : row + 2]
            corners = np.array((world(u1, v1), world(u2, v1), world(u2, v2), world(u1, v2)))
            projected = projection.project(corners)
            if not _visible(projected, image.shape[1], image.shape[0]):
                continue
            polygon = np.rint(projected).astype(np.int32)
            variation = (((column * 7 + row * 13) % 9) - 4) * 0.003
            depth_shade = 1.03 - 0.08 * float(corners[:, 2].mean()) / projection.back
            cv2.fillConvexPoly(image, polygon, _shade(tint, depth_shade + variation))
    for u in us:
        line = projection.project((world(u, 0), world(u, v_size)))
        if not _visible(line, image.shape[1], image.shape[0]):
            continue
        ends = np.rint(line).astype(np.int32)
        cv2.line(image, tuple(ends[0]), tuple(ends[1]), GRID_COLOR, 1, cv2.LINE_AA)
    for v in vs:
        line = projection.project((world(0, v), world(u_size, v)))
        if not _visible(line, image.shape[1], image.shape[0]):
            continue
        ends = np.rint(line).astype(np.int32)
        cv2.line(image, tuple(ends[0]), tuple(ends[1]), GRID_COLOR, 1, cv2.LINE_AA)
    border = projection.project(
        (world(0, 0), world(u_size, 0), world(u_size, v_size), world(0, v_size))
    )
    if _visible(border, image.shape[1], image.shape[0]):
        cv2.polylines(image, [np.rint(border).astype(np.int32)], True, BORDER_COLOR, 1, cv2.LINE_AA)


def _surfaces(half: float, near: float, back: float, ceiling: float):
    return (
        ((-half, 0, near), (1, 0, 0), (0, 0, 1), half * 2, back - near, PANEL_COLORS["floor"]),
        (
            (-half, ceiling, near),
            (1, 0, 0),
            (0, 0, 1),
            half * 2,
            back - near,
            PANEL_COLORS["ceiling"],
        ),
        ((-half, 0, near), (0, 0, 1), (0, 1, 0), back - near, ceiling, PANEL_COLORS["left"]),
        ((half, 0, near), (0, 0, 1), (0, 1, 0), back - near, ceiling, PANEL_COLORS["right"]),
        ((-half, 0, back), (1, 0, 0), (0, 1, 0), half * 2, ceiling, PANEL_COLORS["back"]),
    )


def _paint(image, projection, half, near, back, ceiling):
    for surface in _surfaces(half, near, back, ceiling):
        _surface(image, projection, *surface)


@lru_cache(maxsize=4)
def room_background(width: int, height: int, hud: bool = True) -> RoomBackground:
    projection = RoomProjection.for_stage(width, height, hud)
    image = np.full((height, width, 3), PANEL_COLORS["back"], np.uint8)
    half, near, back, ceiling = (
        projection.half_width,
        projection.near,
        projection.back,
        projection.ceiling,
    )
    _paint(image, projection, half, near, back, ceiling)
    floor = projection.project(
        ((-half, 0, near), (half, 0, near), (half, 0, back), (-half, 0, back))
    )
    floor_mask = np.zeros((height, width), np.uint8)
    cv2.fillConvexPoly(floor_mask, np.rint(floor).astype(np.int32), 255)
    floor_mask[: projection.top] = 0
    floor_mask[projection.bottom :] = 0
    image.flags.writeable = False
    floor_mask.flags.writeable = False
    return RoomBackground(image, floor_mask, projection)


def camera_room(camera, width: int, height: int) -> RoomBackground:
    """The same room, drawn from wherever the ghost camera happens to be.

    Not cached: the image depends on the camera pose, which changes every frame
    while flying. Polygons crossing the near plane are skipped rather than
    clipped, so geometry very close to the camera thins out instead of tearing.
    """
    projection = CameraProjection(camera, width, height, top=0, bottom=height)
    image = np.full((height, width, 3), PANEL_COLORS["back"], np.uint8)
    _paint(
        image,
        projection,
        projection.half_width,
        projection.near,
        projection.back,
        projection.ceiling,
    )
    floor = projection.project(
        (
            (-projection.half_width, 0, projection.near),
            (projection.half_width, 0, projection.near),
            (projection.half_width, 0, projection.back),
            (-projection.half_width, 0, projection.back),
        )
    )
    floor_mask = np.zeros((height, width), np.uint8)
    if _visible(floor, width, height):
        cv2.fillConvexPoly(floor_mask, np.rint(floor).astype(np.int32), 255)
    image.flags.writeable = False
    floor_mask.flags.writeable = False
    return RoomBackground(image, floor_mask, projection)


def draw_foot_shadows(
    image: NDArray[np.uint8],
    room: RoomBackground,
    footprints: list[Footprint],
) -> int:
    if not footprints:
        return 0
    mask = np.zeros(image.shape[:2], np.uint8)
    projection = room.projection
    count = 0
    angles = np.linspace(0, math.tau, 36, endpoint=False)
    for footprint in footprints:
        center = projection.floor_point(footprint.center)
        if center is None or not math.isfinite(footprint.width) or footprint.width <= 0:
            continue
        radius = min(0.65, max(0.035, footprint.width * 0.64 * center[2] / projection.focal))
        count += 1
        foot_mask = np.zeros_like(mask)
        for scale, opacity in ((1.35, 6), (1.12, 14), (1.0, 27), (0.72, 43), (0.42, 56)):
            points = np.tile(center, (len(angles), 1))
            points[:, 0] += np.cos(angles) * radius * scale
            points[:, 2] += np.sin(angles) * radius * scale * 0.7
            if np.any(points[:, 2] <= projection.near):
                continue
            polygon = np.rint(projection.project(points)).astype(np.int32)
            cv2.fillConvexPoly(foot_mask, polygon, opacity, cv2.LINE_AA)
        np.maximum(mask, foot_mask, out=mask)
    mask = cv2.GaussianBlur(mask, (5, 5), 1.0)
    cv2.bitwise_and(mask, room.floor_mask, dst=mask)
    bounds = cv2.boundingRect(mask)
    x, y, width, height = bounds
    if width and height:
        alpha = mask[y : y + height, x : x + width, None].astype(np.float32) / 255
        pixels = image[y : y + height, x : x + width]
        pixels[:] = np.rint(pixels * (1 - alpha)).astype(np.uint8)
    return count
