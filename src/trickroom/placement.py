"""Anchor stage presentation to the first fully visible body in a session.

Presentation scale previously followed the measured body span directly, so the
character was drawn as large as the performer happened to appear in the source
frame. A close scripted demo filled the stage while a performer standing back
from a phone camera became small, and the two avatar paths disagreed because
they estimated that span differently.

The first fully visible body instead defines a base distance. The character is
drawn at ``target_height`` of the stage there, and every later observation is
scaled by the ratio of its span to that base span. For a fixed camera apparent
size varies with the inverse of distance, so the same ratio also gives a room
depth that can place the character on the floor plane.

The captured anchor is session-only. It is discarded when the source frame size
changes or when the caller explicitly recalibrates, and it is never written to
disk.

This is a presentation anchor derived from image spans. It is not a measured
physical distance, a calibrated camera focal length, a floor-contact estimate
or a claim about tracking accuracy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from trickroom.state import Observation

SPAN_JOINTS = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28, 31, 32)
MIN_SPAN = 8.0


def body_span(state: Observation) -> float | None:
    """Vertical pixel extent of a fully visible body, or None when incomplete."""
    height = state.frame_size[1]
    values = []
    for index in SPAN_JOINTS:
        point = state.joint(index)
        if point is None:
            return None
        values.append(point.y * height)
    span = max(values) - min(values)
    if not math.isfinite(span) or span < MIN_SPAN:
        return None
    return float(span)


@dataclass(frozen=True)
class StagePlacement:
    """How large and how deep the character should be drawn for one observation."""

    scale_ratio: float
    depth: float
    height_fraction: float
    clamped: bool


class StageAnchor:
    """Session-scoped base distance captured from the first fully visible body."""

    def __init__(
        self,
        *,
        target_height: float = 0.7,
        base_depth: float = 3.0,
        near: float = 0.6,
        back: float = 8.4,
    ) -> None:
        if not 0.05 <= target_height <= 1.0:
            raise ValueError("Target stage height must be between 0.05 and 1.0.")
        if not math.isfinite(base_depth) or base_depth <= 0:
            raise ValueError("Base depth must be finite and positive.")
        if not 0 < near < back:
            raise ValueError("Room depth bounds must satisfy 0 < near < back.")
        if not near <= base_depth <= back:
            raise ValueError("Base depth must lie within the room depth bounds.")
        self.target_height = float(target_height)
        self.base_depth = float(base_depth)
        self.near = float(near)
        self.back = float(back)
        self.base_span: float | None = None
        self.frame_size: tuple[int, int] | None = None

    @property
    def anchored(self) -> bool:
        return self.base_span is not None

    def reset(self) -> None:
        """Discard the captured base distance; the next full body anchors again."""
        self.base_span = None
        self.frame_size = None

    def capture(self, span: float, frame_size: tuple[int, int]) -> bool:
        """Record the base distance. Returns False when an anchor already holds."""
        if not math.isfinite(span) or span < MIN_SPAN:
            raise ValueError("Base span must be finite and at least the minimum span.")
        if self.anchored and self.frame_size == tuple(frame_size):
            return False
        self.base_span = float(span)
        self.frame_size = (int(frame_size[0]), int(frame_size[1]))
        return True

    def observe(self, state: Observation) -> StagePlacement | None:
        """Capture on the first full body, then place every later observation."""
        if self.frame_size is not None and tuple(state.frame_size) != self.frame_size:
            self.reset()
        span = body_span(state)
        if not self.anchored:
            if span is None:
                return None
            self.capture(span, state.frame_size)
        return self.placement(span)

    def placement(self, span: float | None) -> StagePlacement | None:
        """Scale and depth for a measured span, or None while unanchored."""
        if self.base_span is None or span is None:
            return None
        if not math.isfinite(span) or span <= 0:
            raise ValueError("Measured span must be finite and positive.")
        ratio = span / self.base_span
        depth = self.base_depth / ratio
        clamped = not self.near <= depth <= self.back
        depth = min(max(depth, self.near), self.back)
        ratio = self.base_depth / depth
        return StagePlacement(
            scale_ratio=float(ratio),
            depth=float(depth),
            height_fraction=float(self.target_height * ratio),
            clamped=clamped,
        )
