from dataclasses import replace

import numpy as np
import pytest
from glb_helpers import FIXTURE

from trickroom.assets.gltf import load_asset
from trickroom.assets.kinematics import solve_limb
from trickroom.assets.math3d import matrix_quaternion, quaternion_matrix, rotation_only, slerp
from trickroom.assets.motion import MotionOptions
from trickroom.assets.retarget import AvatarInstance, observed_points, retarget
from trickroom.demo import demo_observation
from trickroom.filters import MotionSmoother
from trickroom.state import Point


@pytest.fixture
def asset():
    return load_asset(FIXTURE)


def assert_lengths(asset, globals_):
    for index, node in enumerate(asset.nodes):
        if node.parent < 0:
            continue
        expected = np.linalg.norm(
            asset.rest_globals[index, :3, 3] - asset.rest_globals[node.parent, :3, 3]
        )
        actual = np.linalg.norm(globals_[index, :3, 3] - globals_[node.parent, :3, 3])
        assert actual == pytest.approx(expected, abs=1e-6)


def test_world_points_accept_negative_coordinates_but_require_image_eligibility():
    state = demo_observation(0, 10)
    assert state.world_joint(0).y < 0
    assert len(observed_points(state, "world")) == 33
    joints = list(state.joints)
    joints[15] = replace(joints[15], x=-0.01)
    hidden = replace(state, joints=tuple(joints))
    assert hidden.world_joint(15) is None
    assert 15 not in observed_points(hidden, "world")
    assert state.world_joint(15) is not None


def test_world_filter_is_separate_and_does_not_clamp_to_image_bounds():
    smoother = MotionSmoother()
    state = demo_observation(0, 1)
    world = tuple(Point(-2, -3, 4) for _ in range(33))
    initial = smoother.apply(replace(state, world_joints=world))
    changed = smoother.apply(
        replace(state, captured_at=1.03, world_joints=tuple(Point(-1, -2, 3) for _ in range(33)))
    )
    assert initial.world_joint(15).x == -2
    assert -2 < changed.world_joint(15).x < -1
    assert changed.joints == initial.joints


def test_world_retarget_uses_world_directions_not_screen_placement(asset):
    state = demo_observation(0, 10)
    world = list(state.world_joints)
    world[13] = replace(world[13], z=world[13].z - 0.4)
    changed = replace(state, world_joints=tuple(world))
    assert np.array_equal(retarget(asset, state)[0], retarget(asset, changed)[0])
    before = retarget(asset, state, space="world")[0]
    after = retarget(asset, changed, space="world")[0]
    assert not np.allclose(before, after)
    assert_lengths(asset, after)


def test_world_mode_never_silently_uses_image_coordinates(asset):
    state = replace(demo_observation(0, 10), world_joints=())
    _, _, active = retarget(asset, state, space="world")
    assert "upper_arm_left" not in active
    assert "head" in active
    with pytest.raises(ValueError, match="coordinates"):
        observed_points(state, "unknown")


@pytest.mark.parametrize("t", [0, 0.8, 2.2, 4.0])
def test_constrained_world_rig_preserves_lengths_and_finite_transforms(asset, t):
    globals_, _, active = retarget(
        asset, demo_observation(t, 10), space="world", constraints=True, bend_normals={}
    )
    assert "hand_left" in active and np.isfinite(globals_).all()
    assert_lengths(asset, globals_)
    for matrix in globals_:
        assert np.linalg.det(rotation_only(matrix)) == pytest.approx(1, abs=1e-6)


def test_two_bone_solver_reach_and_straight_plane_are_bounded():
    a, b, c = np.array((0.0, 0, 0)), np.array((1.0, 0, 0)), np.array((1.0, 1, 0))
    upper, lower, normal = solve_limb(a, b, c, 1.0, 1.0)
    assert upper + lower == pytest.approx(c)
    straight = solve_limb(a, b, np.array((2.0, 0, 0)), 1.0, 1.0, normal)
    assert np.isfinite(np.array(straight)).all()
    assert straight[0] + straight[1] == pytest.approx((2, 0, 0), abs=1e-6)
    assert solve_limb(a, a, a, 1.0, 1.0) is None


def test_display_interpolation_changes_pose_without_a_new_detection(asset):
    instance = AvatarInstance(asset)
    instance.configure_motion(
        MotionOptions(enabled=True, space="image", interpolation_delay=0.05, constrain_limbs=False)
    )
    a, b = demo_observation(0, 1), demo_observation(1, 1.1)
    first = instance.evaluate(a, 1)
    halfway = instance.evaluate(b, 1.1)
    complete = instance.evaluate(b, 1.2)
    bone = asset.bones["upper_arm_left"]
    parent = asset.nodes[bone].parent
    qa = matrix_quaternion(
        rotation_only(first.globals[parent]).T @ rotation_only(first.globals[bone])
    )
    qb = matrix_quaternion(
        rotation_only(complete.globals[parent]).T @ rotation_only(complete.globals[bone])
    )
    actual = rotation_only(halfway.globals[parent]).T @ rotation_only(halfway.globals[bone])
    assert actual == pytest.approx(quaternion_matrix(slerp(qa, qb, 0.5)), abs=1e-6)
    assert_lengths(asset, halfway.globals)
    assert len(instance.motion.history) == 2


def test_real_inference_latency_does_not_eliminate_intermediate_display_poses(asset):
    instance = AvatarInstance(asset)
    instance.configure_motion(
        MotionOptions(enabled=True, space="image", interpolation_delay=0.05, constrain_limbs=False)
    )
    a, b = demo_observation(0, 1), demo_observation(1, 1.1)
    instance.evaluate(a, 1.09)
    arrival = instance.evaluate(b, 1.19)
    middle = instance.evaluate(b, 1.215)
    final = instance.evaluate(b, 1.25)
    assert not np.allclose(arrival.globals, middle.globals)
    assert not np.allclose(middle.globals, final.globals)
    assert instance.motion.playhead <= b.captured_at
    assert_lengths(asset, middle.globals)


def test_sample_timing_jitter_cannot_rewind_the_presentation_clock(asset):
    instance = AvatarInstance(asset)
    instance.configure_motion(MotionOptions(enabled=True))
    instance.evaluate(demo_observation(0, 1), 1.01)
    instance.evaluate(demo_observation(0.1, 1.1), 1.11)
    instance.evaluate(demo_observation(0.1, 1.1), 1.2)
    previous = instance.motion.playhead
    instance.evaluate(demo_observation(0.2, 1.2), 1.55)
    assert instance.motion.playhead >= previous


def test_opt_in_loss_states_never_change_raw_eligibility_and_stale_clears(asset):
    instance = AvatarInstance(asset)
    instance.configure_motion(MotionOptions(enabled=True, relax_missing=True))
    instance.evaluate(demo_observation(0, 10), 10)
    cropped = demo_observation(0.1, 10.1, cropped=True)
    held = instance.evaluate(cropped, 10.1)
    assert cropped.joint(27) is None
    assert held.tracking_states["lower_leg_left"] == "HELD"
    assert "lower_leg_left" in held.active
    resting = instance.evaluate(cropped, 10.5)
    assert resting.tracking_states["lower_leg_left"] == "REST"
    assert resting.placement.joint(27) is None
    stale = instance.evaluate(cropped, 10.8)
    assert not stale.active
    assert not any(mask.any() for mask in stale.visible)


def test_strict_loss_and_never_seen_parts_remain_unavailable(asset):
    for relaxed in (False, True):
        instance = AvatarInstance(asset)
        instance.configure_motion(MotionOptions(enabled=True, relax_missing=relaxed))
        state = demo_observation(0, 10, cropped=True)
        evaluation = instance.evaluate(state, 10)
        assert evaluation.tracking_states["lower_leg_left"] == "UNAVAILABLE"
        assert "lower_leg_left" not in evaluation.active


def test_full_loss_and_source_rewind_discard_previous_pose_history(asset):
    instance = AvatarInstance(asset)
    instance.configure_motion(MotionOptions(enabled=True, relax_missing=True))
    full = demo_observation(0, 10)
    instance.evaluate(full, 10)
    empty = replace(full, sequence=2, captured_at=10.1, joints=(), world_joints=(), face=None)
    assert not instance.evaluate(empty, 10.1).active
    rewound = demo_observation(0, 1, cropped=True)
    assert "lower_leg_left" not in instance.evaluate(rewound, 1).active


def test_seek_generation_clears_history_even_when_other_frame_keys_match(asset):
    instance = AvatarInstance(asset)
    instance.configure_motion(MotionOptions(enabled=True, relax_missing=True))
    state = demo_observation(0, 10)
    instance.evaluate(state, 10)
    seek = replace(demo_observation(0, 10, cropped=True), generation=1)
    result = instance.evaluate(seek, 10)
    assert len(instance.motion.history) == 1
    assert instance.motion.history[-1].state.generation == 1
    assert "lower_leg_left" not in result.active
    assert result.tracking_states["lower_leg_left"] == "UNAVAILABLE"


def test_held_pose_starts_at_displayed_pose_and_reacquires_gradually(asset):
    instance = AvatarInstance(asset)
    instance.configure_motion(
        MotionOptions(
            enabled=True,
            relax_missing=True,
            space="image",
            constrain_limbs=False,
            interpolation_delay=0.05,
        )
    )
    a = demo_observation(0, 1)
    b = demo_observation(1, 1.1)
    instance.evaluate(a, 1)
    shown = instance.evaluate(b, 1.1)
    missing = list(b.joints)
    missing[13] = replace(missing[13], visibility=0)
    lost = replace(b, joints=tuple(missing), sequence=90, captured_at=1.11)
    held = instance.evaluate(lost, 1.11)
    bone = asset.bones["upper_arm_left"]
    parent = asset.nodes[bone].parent

    def local(evaluation):
        return rotation_only(evaluation.globals[parent]).T @ rotation_only(evaluation.globals[bone])

    assert local(held) == pytest.approx(local(shown), abs=1e-6)
    fresh = replace(b, sequence=91, captured_at=1.12)
    reacquired = instance.evaluate(fresh, 1.12)
    assert reacquired.tracking_states["upper_arm_left"] == "REACQUIRING"
    assert local(reacquired) == pytest.approx(local(held), abs=1e-6)
