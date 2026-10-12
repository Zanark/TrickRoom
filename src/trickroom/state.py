"""Image-free contracts shared by tracking, rendering and diagnostics."""

from __future__ import annotations

import math
from dataclasses import dataclass

JOINT_NAMES = (
    "nose",
    "left eye inner",
    "left eye",
    "left eye outer",
    "right eye inner",
    "right eye",
    "right eye outer",
    "left ear",
    "right ear",
    "mouth left",
    "mouth right",
    "left shoulder",
    "right shoulder",
    "left elbow",
    "right elbow",
    "left wrist",
    "right wrist",
    "left pinky",
    "right pinky",
    "left index",
    "right index",
    "left thumb",
    "right thumb",
    "left hip",
    "right hip",
    "left knee",
    "right knee",
    "left ankle",
    "right ankle",
    "left heel",
    "right heel",
    "left foot",
    "right foot",
)
BODY_CONNECTIONS = (
    (11, 12),
    (11, 13),
    (13, 15),
    (15, 17),
    (15, 19),
    (15, 21),
    (17, 19),
    (12, 14),
    (14, 16),
    (16, 18),
    (16, 20),
    (16, 22),
    (18, 20),
    (11, 23),
    (12, 24),
    (23, 24),
    (23, 25),
    (25, 27),
    (27, 29),
    (29, 31),
    (27, 31),
    (24, 26),
    (26, 28),
    (28, 30),
    (30, 32),
    (28, 32),
)


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float
    z: float = 0.0
    visibility: float = 1.0
    presence: float = 1.0

    def reliable(self, threshold: float = 0.5) -> bool:
        values = (self.x, self.y, self.z, self.visibility, self.presence)
        return (
            all(math.isfinite(value) for value in values)
            and self.visibility >= threshold
            and self.presence >= threshold
        )

    def usable(self, threshold: float = 0.5) -> bool:
        return self.reliable(threshold) and 0.0 <= self.x <= 1.0 and 0.0 <= self.y <= 1.0


@dataclass(frozen=True, slots=True)
class Expression:
    """Subject-anatomical sides; blink is zero open, one closed."""

    blink_left: float = 0.0
    blink_right: float = 0.0
    jaw_open: float = 0.0
    smile: float = 0.0
    brow_left: float = 0.0
    brow_right: float = 0.0
    gaze_x: float = 0.0
    gaze_y: float = 0.0


@dataclass(frozen=True, slots=True)
class Face:
    center: Point
    width: float
    height: float
    pitch: float
    yaw: float
    roll: float
    expression: Expression = Expression()
    landmarks: tuple[Point, ...] = ()
    crop_used: bool = False


@dataclass(frozen=True, slots=True)
class Observation:
    sequence: int
    captured_at: float
    completed_at: float
    frame_size: tuple[int, int]
    joints: tuple[Point, ...] = ()
    world_joints: tuple[Point, ...] = ()
    face: Face | None = None
    contours: tuple[tuple[Point, ...], ...] = ()
    inference_ms: float = 0.0
    media_time: float | None = None
    generation: int = 0

    def joint(self, index: int, threshold: float = 0.5) -> Point | None:
        if index < 0 or index >= len(self.joints):
            return None
        point = self.joints[index]
        return point if point.usable(threshold) else None

    def world_joint(self, index: int, threshold: float = 0.5) -> Point | None:
        if self.joint(index, threshold) is None or len(self.world_joints) != len(self.joints):
            return None
        point = self.world_joints[index]
        return point if point.reliable(threshold) else None

    @property
    def visible_joints(self) -> int:
        return sum(point.usable() for point in self.joints)

    def age(self, now: float) -> float:
        return max(0.0, now - self.captured_at)

    def body_status(self, now: float, stale_after: float = 0.6) -> str:
        if self.age(now) > stale_after:
            return "STALE"
        if not self.joints or self.visible_joints < 4:
            return "NOT FOUND"
        if all(
            self.joint(index) is not None
            for index in (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28, 31, 32)
        ):
            return "FULL BODY"
        return "PARTIAL BODY"
