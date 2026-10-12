"""Rest-aware rig posing with explicit optional interpolation and loss-state presentation."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from trickroom.assets.animation import deform, global_transforms, sample_clip
from trickroom.assets.kinematics import aim_rotation, solve_limb
from trickroom.assets.math3d import (
    compose,
    matrix_quaternion,
    normalize,
    rotation_between,
    rotation_only,
)
from trickroom.assets.motion import MotionOptions, RigMotion
from trickroom.assets.profile import AssetError
from trickroom.assets.types import Asset
from trickroom.filters import OneEuro
from trickroom.state import Observation

SEGMENTS = {
    "upper_arm_left": (11, 13, "lower_arm_left"),
    "lower_arm_left": (13, 15, "hand_left"),
    "upper_arm_right": (12, 14, "lower_arm_right"),
    "lower_arm_right": (14, 16, "hand_right"),
    "upper_leg_left": (23, 25, "lower_leg_left"),
    "lower_leg_left": (25, 27, "foot_left"),
    "upper_leg_right": (24, 26, "lower_leg_right"),
    "lower_leg_right": (26, 28, "foot_right"),
}
NEEDED = {
    "hips": (23, 24),
    "spine": (11, 12, 23, 24),
    "chest": (11, 12, 23, 24),
    "neck": (11, 12, 0),
    "shoulder_left": (11,),
    "shoulder_right": (12,),
    "upper_arm_left": (11, 13),
    "lower_arm_left": (13, 15),
    "hand_left": (15,),
    "upper_arm_right": (12, 14),
    "lower_arm_right": (14, 16),
    "hand_right": (16,),
    "upper_leg_left": (23, 25),
    "lower_leg_left": (25, 27),
    "foot_left": (27, 31),
    "upper_leg_right": (24, 26),
    "lower_leg_right": (26, 28),
    "foot_right": (28, 32),
    "toes_left": (27, 31),
    "toes_right": (28, 32),
}


def observed_points(state: Observation, space: str = "image"):
    if space == "world":
        return {
            i: np.array((p.x, -p.y, -p.z))
            for i in range(len(state.joints))
            if (p := state.world_joint(i)) is not None
        }
    if space != "image":
        raise ValueError("Rig coordinates must be image or world.")
    width, height = state.frame_size
    return {
        i: np.array((p.x * width, -p.y * height, -p.z * width))
        for i in range(len(state.joints))
        if (p := state.joint(i)) is not None
    }


def availability(state: Observation, points=None):
    points = observed_points(state) if points is None else points
    result = {name for name, needed in NEEDED.items() if all(i in points for i in needed)}
    if state.face is not None or 0 in points:
        result.update(("head", "eye_left", "eye_right"))
    return result


def body_basis(points):
    if not all(i in points for i in (11, 12, 23, 24)):
        return None
    up = normalize((points[11] + points[12] - points[23] - points[24]) / 2, (0, 1, 0))
    side = points[23] - points[24]
    side = normalize(side - up * np.dot(side, up), (1, 0, 0))
    front = normalize(np.cross(side, up), (0, 0, 1))
    return np.column_stack((side, up, front))


def face_rotation(face):
    pitch, yaw, roll = np.radians((face.pitch, face.yaw, face.roll))
    cp, sp, cy, sy, cr, sr = (
        np.cos(pitch),
        np.sin(pitch),
        np.cos(yaw),
        np.sin(yaw),
        np.cos(roll),
        np.sin(roll),
    )
    return (
        np.array(((cr, -sr, 0), (sr, cr, 0), (0, 0, 1)))
        @ np.array(((cy, 0, sy), (0, 1, 0), (-sy, 0, cy)))
        @ np.array(((1, 0, 0), (0, cp, -sp), (0, sp, cp)))
    )


def expression_weights(asset: Asset, state: Observation):
    values = {name: 0.0 for name in asset.profile.shapes}
    if state.face is not None:
        ex = state.face.expression
        values.update(
            {
                "blink_left": ex.blink_left,
                "blink_right": ex.blink_right,
                "jaw_open": ex.jaw_open,
                "smile": ex.smile,
                "brow_up_left": max(0, ex.brow_left),
                "brow_up_right": max(0, ex.brow_right),
                "brow_down_left": max(0, -ex.brow_left),
                "brow_down_right": max(0, -ex.brow_right),
                "look_left": max(0, ex.gaze_x),
                "look_right": max(0, -ex.gaze_x),
                "look_up": max(0, -ex.gaze_y),
                "look_down": max(0, ex.gaze_y),
            }
        )
    result = {}
    for primitive in asset.primitives:
        weights = primitive.default_weights.copy()
        names = {name: i for i, name in enumerate(primitive.target_names)}
        for logical, target in asset.profile.shapes.items():
            if target in names:
                value = values[logical]
                if asset.profile.gaze_mode == "bones" and logical.startswith("look_"):
                    value = 0
                weights[names[target]] = np.clip(value, 0, 1)
        result[primitive.node] = weights
    return result


def retarget(
    asset: Asset,
    state: Observation,
    *,
    space: str = "image",
    constraints: bool = False,
    bend_normals: dict | None = None,
):
    points = observed_points(state, space)
    active = availability(state, points)
    bones, rest = asset.bones, asset.rest_globals
    desired = {}
    basis = body_basis(points)
    if basis is not None:
        # The exported contract is upright Y-up, anatomical left +X, facing +Z.
        for logical in ("hips", "spine", "chest", "shoulder_left", "shoulder_right"):
            if logical in bones and logical in active:
                index = bones[logical]
                desired[index] = basis @ rotation_only(rest[index])

    def reference_rotation(index):
        parent = asset.nodes[index].parent
        while parent >= 0:
            if parent in desired:
                return desired[parent] @ rotation_only(rest[parent]).T @ rotation_only(rest[index])
            parent = asset.nodes[parent].parent
        return rotation_only(rest[index])

    for logical, (start, end, child) in SEGMENTS.items():
        if logical not in active:
            continue
        index = bones[logical]
        direction = rest[bones[child], :3, 3] - rest[index, :3, 3]
        if np.linalg.norm(direction) > 1e-7 and np.linalg.norm(points[end] - points[start]) > 1e-7:
            reference = reference_rotation(index)
            direction = reference @ rotation_only(rest[index]).T @ direction
            desired[index] = rotation_between(direction, points[end] - points[start]) @ reference
    if constraints:
        for upper_name, lower_name, end_name, a, b, c in (
            ("upper_arm_left", "lower_arm_left", "hand_left", 11, 13, 15),
            ("upper_arm_right", "lower_arm_right", "hand_right", 12, 14, 16),
            ("upper_leg_left", "lower_leg_left", "foot_left", 23, 25, 27),
            ("upper_leg_right", "lower_leg_right", "foot_right", 24, 26, 28),
        ):
            if not all(i in points for i in (a, b, c)):
                continue
            upper, lower, end = (bones[name] for name in (upper_name, lower_name, end_name))
            rest_upper = rest[lower, :3, 3] - rest[upper, :3, 3]
            rest_lower = rest[end, :3, 3] - rest[lower, :3, 3]
            # solve_limb uses cross(end - start, middle - start), i.e. lower x upper.
            rest_normal = np.cross(rest_lower, rest_upper)
            if np.linalg.norm(rest_normal) < 1e-7:
                rest_normal = np.array((0, 0, 1))
            frame_delta = reference_rotation(upper) @ rotation_only(rest[upper]).T
            previous_normal = (
                bend_normals.get(upper_name, rest_normal)
                if bend_normals is not None
                else rest_normal
            )
            solved = solve_limb(
                points[a],
                points[b],
                points[c],
                np.linalg.norm(rest_upper),
                np.linalg.norm(rest_lower),
                frame_delta @ previous_normal,
            )
            if solved is None:
                continue
            upper_direction, lower_direction, normal = solved
            if bend_normals is not None:
                # Retain the bend plane in the body frame so turns do not leave it camera-fixed.
                bend_normals[upper_name] = frame_delta.T @ normal
            for index, direction, target in (
                (upper, rest_upper, upper_direction),
                (lower, rest_lower, lower_direction),
            ):
                desired[index] = aim_rotation(
                    direction, target, rest_normal, normal
                ) @ rotation_only(rest[index])
    for logical, wrist, index_tip, pinky in (
        ("hand_left", 15, 19, 17),
        ("hand_right", 16, 20, 18),
    ):
        if all(i in points for i in (wrist, index_tip, pinky)):
            index = bones[logical]
            target = (points[index_tip] + points[pinky]) / 2 - points[wrist]
            reference = reference_rotation(index)
            direction = reference @ np.array((0, 1, 0))
            if np.linalg.norm(target) > 1e-7:
                desired[index] = rotation_between(direction, target) @ reference
    for logical, ankle, toe, child in (
        ("foot_left", 27, 31, "toes_left"),
        ("foot_right", 28, 32, "toes_right"),
    ):
        if logical in active and child in bones:
            index = bones[logical]
            direction = rest[bones[child], :3, 3] - rest[index, :3, 3]
            target = points[toe] - points[ankle]
            if np.linalg.norm(direction) > 1e-7 and np.linalg.norm(target) > 1e-7:
                reference = reference_rotation(index)
                direction = reference @ rotation_only(rest[index]).T @ direction
                desired[index] = rotation_between(direction, target) @ reference
    if "neck" in active:
        index = bones["neck"]
        direction = rest[bones["head"], :3, 3] - rest[index, :3, 3]
        target = points[0] - (points[11] + points[12]) / 2
        if np.linalg.norm(direction) > 1e-7 and np.linalg.norm(target) > 1e-7:
            reference = reference_rotation(index)
            direction = reference @ rotation_only(rest[index]).T @ direction
            desired[index] = rotation_between(direction, target) @ reference
    if state.face is not None:
        index = bones["head"]
        desired[index] = face_rotation(state.face) @ rotation_only(rest[index])
    globals_ = np.tile(np.eye(4), (len(asset.nodes), 1, 1))
    overrides = {}
    for index in asset.order:
        node = asset.nodes[index]
        rotation = node.rotation
        if index in desired:
            parent = rotation_only(globals_[node.parent]) if node.parent >= 0 else np.eye(3)
            rotation = matrix_quaternion(parent.T @ desired[index])
        elif (
            asset.profile.gaze_mode == "bones"
            and index
            in (
                bones.get("eye_left"),
                bones.get("eye_right"),
            )
            and state.face is not None
        ):
            ex = state.face.expression
            horizontal, vertical = np.radians((ex.gaze_x * 20, ex.gaze_y * 15))
            yaw = np.array(
                (
                    (np.cos(horizontal), 0, np.sin(horizontal)),
                    (0, 1, 0),
                    (-np.sin(horizontal), 0, np.cos(horizontal)),
                )
            )
            pitch = np.array(
                (
                    (1, 0, 0),
                    (0, np.cos(vertical), -np.sin(vertical)),
                    (0, np.sin(vertical), np.cos(vertical)),
                )
            )
            head = bones["head"]
            head_delta = rotation_only(globals_[head]) @ rotation_only(rest[head]).T
            desired_eye = head_delta @ yaw @ pitch @ rotation_only(rest[index])
            parent = rotation_only(globals_[node.parent]) if node.parent >= 0 else np.eye(3)
            rotation = matrix_quaternion(parent.T @ desired_eye)
        local = compose(node.translation, rotation, node.scale)
        globals_[index] = globals_[node.parent] @ local if node.parent >= 0 else local
        overrides[index] = rotation
    return globals_, expression_weights(asset, state), active


@dataclass
class Evaluation:
    primitives: tuple
    globals: np.ndarray
    active: set[str]
    visible: tuple[np.ndarray, ...]
    mode: str
    tracking_states: dict[str, str] | None = None
    placement: Observation | None = None


class AvatarInstance:
    def __init__(self, asset: Asset) -> None:
        self.asset = asset
        self.mode = "live"
        self.started_at = 0.0
        self._key = None
        self._evaluation = None
        self.calibrated_scale: float | None = None
        self.scale_frame: tuple[int, int] | None = None
        self._scale_key: tuple[int, float, tuple[int, int]] | None = None
        self._scale_filter = OneEuro(2.0, 0.1)
        self.motion = RigMotion(asset)
        self._roles = tuple(asset.bones)
        role_ids = {role: index for index, role in enumerate(self._roles)}
        self._drivers = []
        for primitive in asset.primitives:
            node = asset.nodes[primitive.node]
            if node.skin is None:
                drivers = [asset.driver_for_node[primitive.node]] * len(primitive.positions)
            else:
                skin = asset.skins[node.skin]
                dominant = primitive.joints[
                    np.arange(len(primitive.positions)), np.argmax(primitive.weights, axis=1)
                ]
                drivers = [asset.driver_for_node[skin.joints[i]] for i in dominant]
            if any(driver is None for driver in drivers):
                raise AssetError(
                    "UNDRIVEN_VERTEX", "Dominant weights must descend from a mapped humanoid bone."
                )
            indices = np.array([role_ids[driver] for driver in drivers], dtype=np.intp)
            indices.flags.writeable = False
            self._drivers.append(indices)
        head_roles = np.array([role in ("head", "eye_left", "eye_right") for role in self._roles])
        self._head_masks = tuple(
            head_roles[drivers][primitive.indices].all(axis=1)
            for primitive, drivers in zip(asset.primitives, self._drivers, strict=True)
        )
        self._foot_masks = {
            side: tuple(
                np.array([role in (f"foot_{side}", f"toes_{side}") for role in self._roles])[
                    drivers
                ]
                for drivers in self._drivers
            )
            for side in ("left", "right")
        }
        for mask in (*self._head_masks, *self._foot_masks["left"], *self._foot_masks["right"]):
            mask.flags.writeable = False

    def set_mode(self, mode: str, now: float) -> None:
        if mode not in ("live", "bind") and mode not in {c.name for c in self.asset.clips}:
            raise AssetError("PREVIEW_MODE", "Select live, bind or an exported animation clip.")
        self.mode, self.started_at = mode, now
        self._key = None
        self.motion.reset()

    def configure_motion(self, options: MotionOptions) -> None:
        if options != self.motion.options:
            self.motion.configure(options)
            self._key = None

    @property
    def preview(self):
        return self.mode != "live"

    def reset_calibration(self) -> None:
        self.calibrated_scale = None
        self._scale_key = None
        self._scale_filter = OneEuro(2.0, 0.1)
        self._key = None
        self.motion.reset()

    def update_scale(self, state: Observation, measurement: float | None) -> float | None:
        if measurement is not None and (not math.isfinite(measurement) or measurement <= 0):
            raise ValueError("Presentation scale must be finite and positive.")
        key = (state.sequence, state.captured_at, state.frame_size)
        if key != self._scale_key:
            if self._scale_key is not None and (
                state.frame_size != self.scale_frame
                or state.captured_at <= self._scale_key[1]
                or state.captured_at - self._scale_key[1] > 0.6
                or state.sequence < self._scale_key[0]
            ):
                self.calibrated_scale = None
                self._scale_filter = OneEuro(2.0, 0.1)
            self._scale_key = key
            self.scale_frame = state.frame_size
            if measurement is not None:
                self.calibrated_scale = math.exp(
                    self._scale_filter.update(math.log(measurement), state.captured_at)
                )
            elif (
                self._scale_filter.time is not None
                and state.captured_at - self._scale_filter.time > 0.6
            ):
                self.calibrated_scale = None
                self._scale_filter = OneEuro(2.0, 0.1)
        return self.calibrated_scale

    def evaluate(self, state: Observation | None, now: float) -> Evaluation:
        key = (
            id(state),
            state.sequence if state else None,
            state.captured_at if state else None,
            self.mode,
            now
            if (self.preview and self.mode != "bind")
            or (self.mode == "live" and self.motion.options.enabled)
            else 0,
        )
        if key == self._key:
            return self._evaluation
        asset = self.asset
        tracking_states = None
        placement = state
        if self.mode == "live":
            if state is None:
                raise AssetError(
                    "NO_OBSERVATION", "Live avatar evaluation requires a current observation."
                )
            if self.motion.options.enabled:
                if self.motion.is_new(state):
                    self.motion.prepare(state)
                    globals_, morphs, active = retarget(
                        asset,
                        state,
                        space=self.motion.options.space,
                        constraints=self.motion.options.constrain_limbs,
                        bend_normals=self.motion.bend_normals,
                    )
                    self.motion.push(state, globals_, morphs, active, now)
                globals_, morphs, active, tracking_states, placement = self.motion.sample(now)
            else:
                globals_, morphs, active = retarget(asset, state)
        elif self.mode == "bind":
            globals_, morphs, active = asset.rest_globals, {}, set(asset.bones)
        else:
            clip = next(c for c in asset.clips if c.name == self.mode)
            trs, morphs = sample_clip(clip, now - self.started_at)
            globals_, active = global_transforms(asset, trs), set(asset.bones)
        geometry = deform(asset, globals_, morphs)
        active_roles = np.array([role in active for role in self._roles])
        visible = tuple(
            active_roles[drivers][p.source.indices].all(axis=1)
            for p, drivers in zip(geometry, self._drivers, strict=True)
        )
        self._evaluation = Evaluation(
            geometry, globals_, active, visible, self.mode, tracking_states, placement
        )
        self._key = key
        return self._evaluation

    def head_triangles(self, primitive_index):
        return self._head_masks[primitive_index]

    def foot_vertices(self, primitive_index, side: str):
        return self._foot_masks[side][primitive_index]
