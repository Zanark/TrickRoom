"""Session-local facial response calibration; detector observations remain unchanged."""

import math
from dataclasses import fields, replace

import numpy as np

from trickroom.state import Expression, Observation

CHANNELS = tuple(field.name for field in fields(Expression))
TIME_CONSTANTS = np.array((0, 0, 0.025, 0.06, 0.06, 0.06, 0.05, 0.05))


class FaceResponse:
    def __init__(self) -> None:
        self.enabled = False
        self.gains = np.ones(len(CHANNELS))
        self.reset()

    def reset(self) -> None:
        self.neutral = np.zeros(len(CHANNELS))
        self.low = np.array((0, 0, 0, 0, -1, -1, -1, -1), dtype=float)
        self.high = np.ones(len(CHANNELS))
        self.calibrated = False
        self.collecting = None
        self.samples = []
        self.started_at = 0.0
        self._last_key = None
        self._sample_key = None
        self._last_time = None
        self._last = None
        self._result = None
        self.message = "Face response: uncalibrated; no personal values saved."

    def set_gain(self, channel: str, value: float) -> None:
        if channel not in CHANNELS or not math.isfinite(value) or not 0.25 <= value <= 3:
            raise ValueError("Face gain requires a known channel and a value from 0.25 to 3.")
        self.gains[CHANNELS.index(channel)] = value
        self._last_key = None

    def begin(self, kind: str, now: float) -> None:
        if kind not in ("neutral", "range") or not math.isfinite(now):
            raise ValueError("Choose neutral or range calibration with a finite timestamp.")
        if kind == "range" and not self.calibrated:
            raise ValueError("Calibrate a neutral face before capturing expression range.")
        self.collecting, self.started_at = kind, now
        self.samples = []
        self._sample_key = None
        self._last_key = None
        self.message = (
            "Hold a neutral face for 1 second."
            if kind == "neutral"
            else "For 3 seconds: blink, smile, open mouth, move brows/gaze."
        )

    def _finish(self) -> None:
        kind, samples = self.collecting, np.asarray(self.samples)
        self.collecting = None
        self.samples = []
        if len(samples) < 12:
            self.message = "Calibration unchanged: not enough fresh face samples. Retry."
            return
        if kind == "neutral":
            spread = np.quantile(samples, 0.8, axis=0) - np.quantile(samples, 0.2, axis=0)
            if np.max(spread) > 0.25:
                self.message = "Calibration unchanged: neutral face was unstable. Retry."
                return
            self.neutral = np.median(samples, axis=0)
            self.low = np.array((0, 0, 0, 0, -1, -1, -1, -1), dtype=float)
            self.high = np.ones(len(CHANNELS))
            self.calibrated = True
            self.message = "Neutral calibrated for this session only."
        else:
            low, high = samples.min(axis=0), samples.max(axis=0)
            usable_high = high - self.neutral >= 0.12
            usable_low = self.neutral - low >= 0.12
            self.high = np.where(usable_high, high, self.high)
            self.low = np.where(usable_low, low, self.low)
            count = int(np.count_nonzero(usable_high | usable_low))
            self.message = f"Range captured for {count}/8 controls; others retain prior ranges."
        self.enabled = True
        self._last_time = self._last = None

    def apply(self, state: Observation | None, now: float) -> Observation | None:
        if state is None or state.face is None or state.age(now) > 0.6:
            if self.collecting is not None:
                self.message = "Calibration cancelled: face unavailable or stale. Retry."
                self.collecting = None
                self.samples = []
            self._last_key = self._last_time = self._last = self._result = None
            return state
        key = (state.sequence, state.captured_at, self.enabled)
        if key != self._last_key:
            raw = np.array([getattr(state.face.expression, channel) for channel in CHANNELS])
            if not np.isfinite(raw).all():
                raise ValueError("Facial response requires finite detector coefficients.")
            sample_key = (state.sequence, state.captured_at)
            if (
                self.collecting is not None
                and state.captured_at >= self.started_at
                and sample_key != self._sample_key
            ):
                self.samples.append(raw)
                self._sample_key = sample_key
                duration = 1 if self.collecting == "neutral" else 3
                if now - self.started_at >= duration or len(self.samples) >= 256:
                    self._finish()
            if not self.enabled:
                self._result = state.face.expression
            else:
                difference = raw - self.neutral
                extent = np.where(
                    difference >= 0, self.high - self.neutral, self.neutral - self.low
                )
                values = np.clip(difference / np.maximum(extent, 0.12) * self.gains, -1, 1)
                values[:4] = np.maximum(values[:4], 0)
                values[:2] = np.clip((values[:2] - 0.05) / 0.8, 0, 1)
                values[2:] = np.sign(values[2:]) * np.maximum(
                    0, (np.abs(values[2:]) - 0.025) / 0.975
                )
                dt = state.captured_at - self._last_time if self._last_time is not None else 0
                if self._last is not None and 0 < dt <= 0.6:
                    alpha = np.ones(len(CHANNELS))
                    alpha[2:] = 1 - np.exp(-dt / TIME_CONSTANTS[2:])
                    values = self._last + alpha * (values - self._last)
                self._last, self._last_time = values, state.captured_at
                self._result = Expression(*map(float, values))
            self._last_key = (state.sequence, state.captured_at, self.enabled)
        if not self.enabled:
            return state
        return replace(state, face=replace(state.face, expression=self._result))
