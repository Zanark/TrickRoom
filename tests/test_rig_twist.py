"""Limb frames must preserve authored roll when observations rigidly rotate the whole body."""

from dataclasses import replace

import numpy as np
import pytest
from glb_helpers import FIXTURE

from trickroom.assets.animation import deform, global_transforms
from trickroom.assets.gltf import load_asset
from trickroom.assets.math3d import rotation_only
from trickroom.assets.motion import MotionOptions
from trickroom.assets.retarget import AvatarInstance, retarget
from trickroom.demo import demo_observation
from trickroom.state import Expression, Point

JOINT_ROLES = {
    11: "upper_arm_left",
    12: "upper_arm_right",
    13: "lower_arm_left",
    14: "lower_arm_right",
    15: "hand_left",
    16: "hand_right",
    23: "upper_leg_left",
    24: "upper_leg_right",
    25: "lower_leg_left",
    26: "lower_leg_right",
    27: "foot_left",
    28: "foot_right",
    31: "toes_left",
    32: "toes_right",
}


@pytest.fixture
def bent_asset():
    asset = load_asset(FIXTURE)
    nodes = list(asset.nodes)
    for role in ("lower_arm_left", "lower_arm_right", "lower_leg_left", "lower_leg_right"):
        index = asset.bones[role]
        node = nodes[index]
        delta = (0, -0.035, 0.025) if "arm" in role else (0, 0, 0.045)
        offset = rotation_only(asset.rest_globals[node.parent]).T @ np.asarray(delta)
        nodes[index] = replace(node, translation=node.translation + offset)
    changed = replace(asset, nodes=tuple(nodes))
    rest = global_transforms(changed)
    skins = tuple(
        replace(
            skin,
            inverse_bind=np.linalg.inv(rest[list(skin.joints)])
            @ asset.rest_globals[list(skin.joints)]
            @ skin.inverse_bind,
        )
        for skin in asset.skins
    )
    return replace(changed, rest_globals=rest, skins=skins)


def body_rotation(yaw, roll=0, pitch=0):
    y, r, p = np.radians((yaw, roll, pitch))
    ry = np.array(((np.cos(y), 0, np.sin(y)), (0, 1, 0), (-np.sin(y), 0, np.cos(y))))
    rz = np.array(((np.cos(r), -np.sin(r), 0), (np.sin(r), np.cos(r), 0), (0, 0, 1)))
    rx = np.array(((1, 0, 0), (0, np.cos(p), -np.sin(p)), (0, np.sin(p), np.cos(p))))
    return rz @ ry @ rx


def rest_observation(asset, yaw, roll=0, pitch=0, *, captured_at=10):
    rotation = body_rotation(yaw, roll, pitch)
    center = asset.rest_globals[asset.bones["hips"], :3, 3]
    points = np.tile(center, (33, 1))
    for index, role in JOINT_ROLES.items():
        points[index] = asset.rest_globals[asset.bones[role], :3, 3]
    points[0] = asset.rest_globals[asset.bones["head"], :3, 3]
    for side, wrist, index, pinky in (("left", 15, 19, 17), ("right", 16, 20, 18)):
        direction = rotation_only(asset.rest_globals[asset.bones["hand_" + side]]) @ (
            0,
            1,
            0,
        )
        points[index] = points[wrist] + direction * 0.09
        points[pinky] = points[wrist] + direction * 0.07
    points = (points - center) @ rotation.T + center
    image = tuple(Point(0.5 + p[0] * 0.32, 0.94 - p[1] * 0.35, -p[2] * 0.32) for p in points)
    world = tuple(Point(p[0], -p[1], -p[2]) for p in points)
    state = demo_observation(0, captured_at)
    return replace(
        state,
        sequence=round(captured_at * 30),
        joints=image,
        world_joints=world,
        face=replace(state.face, yaw=yaw, roll=roll, pitch=pitch, expression=Expression()),
    )


def assert_frame_rotations(asset, globals_, rotation):
    for role in (
        "hips",
        "spine",
        "chest",
        "upper_arm_left",
        "lower_arm_left",
        "upper_arm_right",
        "lower_arm_right",
        "upper_leg_left",
        "lower_leg_left",
        "upper_leg_right",
        "lower_leg_right",
        "hand_left",
        "hand_right",
        "foot_left",
        "foot_right",
    ):
        index = asset.bones[role]
        expected = rotation @ rotation_only(asset.rest_globals[index])
        assert rotation_only(globals_[index]) == pytest.approx(expected, abs=2e-6), role
    for index, node in enumerate(asset.nodes):
        if node.parent >= 0:
            before = asset.rest_globals[index, :3, 3] - asset.rest_globals[node.parent, :3, 3]
            after = globals_[index, :3, 3] - globals_[node.parent, :3, 3]
            assert np.linalg.norm(after) == pytest.approx(np.linalg.norm(before), abs=1e-6)


@pytest.mark.parametrize("constraints", (False, True))
@pytest.mark.parametrize(
    "yaw,roll,pitch",
    [
        (0, 0, 0),
        (45, 0, 0),
        (90, 0, 0),
        (135, 0, 0),
        (180, 0, 0),
        (270, 0, 0),
        (0, 25, 0),
        (0, -25, 0),
        (0, 0, -25),
        (180, 20, -15),
    ],
)
def test_body_turn_preserves_limb_roll_and_blended_skin(bent_asset, constraints, yaw, roll, pitch):
    asset = bent_asset
    state = rest_observation(asset, yaw, roll, pitch)
    rotation = body_rotation(yaw, roll, pitch)
    globals_, _, _ = retarget(asset, state, space="world", constraints=constraints, bend_normals={})
    assert_frame_rotations(asset, globals_, rotation)
    for skin in asset.skins:
        actual = globals_[list(skin.joints), :3, :3] @ skin.inverse_bind[:, :3, :3]
        expected = rotation @ (
            asset.rest_globals[list(skin.joints), :3, :3] @ skin.inverse_bind[:, :3, :3]
        )
        # Adjacent body/thigh transforms must not oppose each other and crush their blend.
        for role in ("hips", "upper_leg_left", "upper_leg_right"):
            slot = skin.joints.index(asset.bones[role])
            assert actual[slot] == pytest.approx(expected[slot], abs=2e-6)


@pytest.mark.parametrize("yaw", (0, 90, 180, 270))
def test_nearly_straight_limb_seed_rotates_with_body(yaw):
    asset = load_asset(FIXTURE)
    state = rest_observation(asset, yaw)
    globals_, _, _ = retarget(asset, state, space="world", constraints=True, bend_normals={})
    assert_frame_rotations(asset, globals_, body_rotation(yaw))


def test_temporal_bend_plane_follows_turn_instead_of_staying_camera_fixed():
    asset = load_asset(FIXTURE)
    instance = AvatarInstance(asset)
    instance.configure_motion(
        MotionOptions(enabled=True, interpolation_delay=0, constrain_limbs=True)
    )
    for index, yaw in enumerate(range(0, 361, 30)):
        time = 10 + index / 30
        state = rest_observation(asset, yaw, captured_at=time)
        evaluation = instance.evaluate(state, time)
        assert_frame_rotations(asset, evaluation.globals, body_rotation(yaw))


def test_rest_observation_keeps_the_bound_mesh(bent_asset):
    asset = bent_asset
    state = rest_observation(asset, 0)
    globals_, morphs, _ = retarget(asset, state, space="world", constraints=True, bend_normals={})
    actual = deform(asset, globals_, morphs)
    expected = deform(asset, asset.rest_globals, {})
    for a, b in zip(actual, expected, strict=True):
        assert a.positions == pytest.approx(b.positions, abs=2e-6)
