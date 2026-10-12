"""Time-aware motion filtering; observations retain unsmoothed confidence."""

from __future__ import annotations

import math
from dataclasses import replace

from trickroom.state import Observation, Point


class OneEuro:
    def __init__(self, min_cutoff: float = 1.8, beta: float = 0.08) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.time: float | None = None
        self.value = 0.0
        self.raw = 0.0
        self.velocity = 0.0

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        return 1.0 / (1.0 + 1.0 / (2.0 * math.pi * cutoff * dt))

    def update(self, value: float, now: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Motion values must be finite.")
        if self.time is None or now <= self.time or now - self.time > 0.5:
            self.value = self.raw = value
            self.velocity = 0.0
        else:
            dt = now - self.time
            velocity = (value - self.raw) / dt
            self.velocity += self._alpha(1.0, dt) * (velocity - self.velocity)
            cutoff = self.min_cutoff + self.beta * abs(self.velocity)
            self.value += self._alpha(cutoff, dt) * (value - self.value)
            self.raw = value
        self.time = now
        return self.value


class MotionSmoother:
    def __init__(self) -> None:
        self._joints: dict[int, tuple[OneEuro, OneEuro, OneEuro]] = {}
        self._world: dict[int, tuple[OneEuro, OneEuro, OneEuro]] = {}
        self._face: dict[str, OneEuro] = {}
        self._frame_size = None

    def apply(self, state: Observation) -> Observation:
        now = state.captured_at
        if self._frame_size != state.frame_size:
            self._joints.clear()
            self._world.clear()
            self._face.clear()
            self._frame_size = state.frame_size
        joints: list[Point] = []
        for index, point in enumerate(state.joints):
            if not point.usable():
                self._joints.pop(index, None)
                joints.append(point)
                continue
            filters = self._joints.setdefault(index, (OneEuro(), OneEuro(), OneEuro()))
            values = (point.x, point.y, point.z)
            xyz = tuple(f.update(value, now) for f, value in zip(filters, values, strict=True))
            joints.append(replace(point, x=xyz[0], y=xyz[1], z=xyz[2]))
        if not state.joints:
            self._joints.clear()
        world = []
        for index, point in enumerate(state.world_joints):
            if state.world_joint(index) is None:
                self._world.pop(index, None)
                world.append(point)
                continue
            filters = self._world.setdefault(index, (OneEuro(), OneEuro(), OneEuro()))
            xyz = tuple(
                f.update(value, now)
                for f, value in zip(filters, (point.x, point.y, point.z), strict=True)
            )
            world.append(replace(point, x=xyz[0], y=xyz[1], z=xyz[2]))
        if not state.world_joints:
            self._world.clear()
        face = state.face
        if face is None:
            self._face.clear()
        else:
            values = {
                "x": face.center.x,
                "y": face.center.y,
                "width": face.width,
                "height": face.height,
                "pitch": face.pitch,
                "yaw": face.yaw,
                "roll": face.roll,
            }
            filtered: dict[str, float] = {}
            for key, value in values.items():
                filt = self._face.setdefault(key, OneEuro(2.5, 0.12))
                if key in ("pitch", "yaw", "roll") and filt.time is not None:
                    value = filt.raw + ((value - filt.raw + 180.0) % 360.0 - 180.0)
                filtered[key] = filt.update(value, now)
            face = replace(
                face,
                center=replace(face.center, x=filtered["x"], y=filtered["y"]),
                width=filtered["width"],
                height=filtered["height"],
                pitch=filtered["pitch"],
                yaw=filtered["yaw"],
                roll=filtered["roll"],
            )
        # Expressions stay immediate so short blinks are not erased by motion smoothing.
        return replace(state, joints=tuple(joints), world_joints=tuple(world), face=face)
