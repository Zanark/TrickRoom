"""Presentation-only rig history. Held/rest poses never become tracking observations."""

from collections import deque
from dataclasses import dataclass, replace

import numpy as np

from trickroom.assets.animation import global_transforms
from trickroom.assets.math3d import matrix_quaternion, rotation_only, slerp
from trickroom.state import Observation


@dataclass(frozen=True)
class MotionOptions:
    enabled: bool = False
    space: str = "world"
    interpolation_delay: float = 1 / 30
    relax_missing: bool = False
    hold_seconds: float = 0.15
    transition_seconds: float = 0.2
    constrain_limbs: bool = True

    def __post_init__(self):
        if self.space not in ("image", "world"):
            raise ValueError("Rig coordinates must be image or world.")
        if not 0 <= self.interpolation_delay <= 0.15:
            raise ValueError("Interpolation delay must be between 0 and 150 ms.")
        if not 0 <= self.hold_seconds <= 0.25 or not 0 < self.transition_seconds <= 0.5:
            raise ValueError("Invalid bounded pose transition settings.")


@dataclass
class _Pose:
    state: Observation
    received_at: float
    rotations: np.ndarray
    morphs: dict
    active: set[str]


class RigMotion:
    def __init__(self, asset) -> None:
        self.asset = asset
        self.options = MotionOptions()
        self.reset()

    def reset(self) -> None:
        self.history: deque[_Pose] = deque(maxlen=8)
        self.last_good = {}
        self.reacquiring = {}
        self.last_output = None
        self.bend_normals = {}
        self.playhead = None

    def configure(self, options: MotionOptions) -> None:
        if options != self.options:
            self.options = options
            self.reset()

    def is_new(self, state: Observation) -> bool:
        return not self.history or (
            state.sequence,
            state.captured_at,
            state.frame_size,
            state.generation,
        ) != (
            self.history[-1].state.sequence,
            self.history[-1].state.captured_at,
            self.history[-1].state.frame_size,
            self.history[-1].state.generation,
        )

    def prepare(self, state: Observation) -> None:
        if state.visible_joints < 4 and state.face is None:
            self.reset()
        if self.history:
            old = self.history[-1].state
            if (
                state.captured_at <= old.captured_at
                or state.captured_at - old.captured_at > 0.6
                or state.sequence < old.sequence
                or state.frame_size != old.frame_size
                or state.generation != old.generation
            ):
                self.reset()

    def push(self, state: Observation, globals_, morphs, active, received_at: float) -> None:
        rotations = []
        for index, node in enumerate(self.asset.nodes):
            parent = rotation_only(globals_[node.parent]) if node.parent >= 0 else np.eye(3)
            rotations.append(matrix_quaternion(parent.T @ rotation_only(globals_[index])))
        rotations = np.asarray(rotations)
        previous_active = self.history[-1].active if self.history else set()
        for name, index in self.asset.bones.items():
            if name in active:
                if (
                    name not in previous_active
                    and self.last_output is not None
                    and name in self.last_good
                ):
                    self.reacquiring[name] = (received_at, self.last_output[index].copy())
                self.last_good[name] = (state.captured_at, rotations[index].copy())
            else:
                if name in previous_active and self.last_output is not None:
                    self.last_good[name] = (self.last_good[name][0], self.last_output[index].copy())
                self.reacquiring.pop(name, None)
        self.history.append(_Pose(state, received_at, rotations, morphs, set(active)))

    def sample(self, now: float):
        current = self.history[-1]
        states = {name: "UNAVAILABLE" for name in self.asset.bones}
        active = set(current.active)
        # Interpolate on the arrival-adjusted clock, not ahead of delayed inference samples.
        latency = max(0, current.received_at - current.state.captured_at)
        time = now - latency - self.options.interpolation_delay
        if self.playhead is not None:
            time = max(time, self.playhead)
        self.playhead = time = min(time, current.state.captured_at)
        before = after = self.history[0]
        for pose in self.history:
            if pose.state.captured_at <= time:
                before = after = pose
            else:
                after = pose
                break
        span = after.state.captured_at - before.state.captured_at
        factor = float(np.clip((time - before.state.captured_at) / span, 0, 1)) if span > 0 else 1.0
        rotations = np.array(
            [slerp(a, b, factor) for a, b in zip(before.rotations, after.rotations, strict=True)]
        )
        # Missing face controls clear immediately; short blinks use the latest sample.
        morphs = current.morphs
        joints = list(current.state.joints)
        for i in range(len(joints)):
            a, b = before.state.joint(i), after.state.joint(i)
            if a is not None and b is not None and current.state.joint(i) is not None:
                joints[i] = replace(
                    joints[i],
                    x=a.x * (1 - factor) + b.x * factor,
                    y=a.y * (1 - factor) + b.y * factor,
                    z=a.z * (1 - factor) + b.z * factor,
                )
        if current.state.age(now) > 0.6 or (
            current.state.visible_joints < 4 and current.state.face is None
        ):
            active.clear()
        else:
            for name, index in self.asset.bones.items():
                if name in active:
                    if name not in before.active or name not in after.active:
                        rotations[index] = current.rotations[index]
                    states[name] = "TRACKED"
                    if self.options.relax_missing and name in self.reacquiring:
                        started, original = self.reacquiring[name]
                        weight = float(
                            np.clip((now - started) / self.options.transition_seconds, 0, 1)
                        )
                        rotations[index] = slerp(original, rotations[index], weight)
                        states[name] = "REACQUIRING" if weight < 1 else "TRACKED"
                        if weight >= 1:
                            del self.reacquiring[name]
                    if current.state.face is None and name in ("head", "eye_left", "eye_right"):
                        # Do not interpolate an old face rotation onto a pose-derived head.
                        # Current local rest offsets still follow the interpolated neck/body.
                        rotations[index] = current.rotations[index]
                elif self.options.relax_missing and name in self.last_good:
                    seen_at, rotation = self.last_good[name]
                    age = max(0, now - seen_at)
                    weight = float(
                        np.clip(
                            (age - self.options.hold_seconds) / self.options.transition_seconds,
                            0,
                            1,
                        )
                    )
                    rotations[index] = slerp(rotation, self.asset.nodes[index].rotation, weight)
                    states[name] = (
                        "HELD"
                        if age <= self.options.hold_seconds
                        else ("RETURNING" if weight < 1 else "REST")
                    )
                    active.add(name)
        self.last_output = rotations.copy()
        overrides = {i: {"rotation": rotation} for i, rotation in enumerate(rotations)}
        return (
            global_transforms(self.asset, overrides),
            morphs,
            active,
            states,
            replace(current.state, joints=tuple(joints)),
        )
