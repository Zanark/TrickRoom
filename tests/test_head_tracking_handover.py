"""Face loss must not display the previous facial head rotation on a pose-derived body."""

from dataclasses import replace

import numpy as np
import pytest
from glb_helpers import FIXTURE
from test_rig_twist import body_rotation, rest_observation

from trickroom.assets.gltf import load_asset
from trickroom.assets.math3d import rotation_only
from trickroom.assets.motion import MotionOptions
from trickroom.assets.retarget import AvatarInstance, face_rotation, retarget


@pytest.mark.parametrize("relax_missing", (False, True))
@pytest.mark.parametrize("body_yaw", (0, 90, 180, 270))
def test_face_loss_immediately_uses_pose_derived_head(body_yaw, relax_missing):
    asset = load_asset(FIXTURE)
    instance = AvatarInstance(asset)
    instance.configure_motion(
        MotionOptions(
            enabled=True,
            space="world",
            interpolation_delay=0.05,
            relax_missing=relax_missing,
        )
    )
    first = rest_observation(asset, body_yaw, captured_at=10)
    first = replace(first, face=replace(first.face, yaw=15))
    instance.evaluate(first, 10)
    lost = replace(first, face=None, sequence=first.sequence + 1, captured_at=10.03)
    expected, _, _ = retarget(asset, lost, space="world", constraints=True, bend_normals={})
    actual = instance.evaluate(lost, 10.03)
    head = asset.bones["head"]
    assert rotation_only(actual.globals[head]) == pytest.approx(
        rotation_only(expected[head]), abs=1e-6
    )
    assert lost.face is None
    assert all(not np.any(weights) for weights in instance.motion.history[-1].morphs.values())


def test_one_frame_face_reacquisition_does_not_leak_into_next_face_loss():
    asset = load_asset(FIXTURE)
    instance = AvatarInstance(asset)
    instance.configure_motion(MotionOptions(enabled=True, interpolation_delay=1 / 30))
    rear = rest_observation(asset, 180, captured_at=10)
    rear = replace(rear, face=None)
    instance.evaluate(rear, 10)
    glimpse = replace(
        rest_observation(asset, 180, captured_at=10.033),
        face=rest_observation(asset, 0).face,
    )
    instance.evaluate(glimpse, glimpse.captured_at)
    lost = replace(rear, sequence=glimpse.sequence + 1, captured_at=10.066)
    actual = instance.evaluate(lost, lost.captured_at)
    head = asset.bones["head"]
    expected = body_rotation(180) @ rotation_only(asset.rest_globals[head])
    assert rotation_only(actual.globals[head]) == pytest.approx(expected, abs=1e-6)
    assert "head" in actual.active
    assert actual.placement.face is None


@pytest.mark.parametrize("body_yaw,head_yaw", [(0, 55), (100, 35), (180, 110)])
def test_visible_face_keeps_independent_head_rotation(body_yaw, head_yaw):
    asset = load_asset(FIXTURE)
    instance = AvatarInstance(asset)
    instance.configure_motion(MotionOptions(enabled=True))
    state = rest_observation(asset, body_yaw)
    state = replace(state, face=replace(state.face, yaw=head_yaw))
    actual = instance.evaluate(state, state.captured_at)
    head = asset.bones["head"]
    expected = face_rotation(state.face) @ rotation_only(asset.rest_globals[head])
    assert rotation_only(actual.globals[head]) == pytest.approx(expected, abs=1e-6)
    assert not np.allclose(
        expected, body_rotation(body_yaw) @ rotation_only(asset.rest_globals[head])
    )


def test_face_loss_without_eligible_head_points_does_not_reactivate_head():
    asset = load_asset(FIXTURE)
    instance = AvatarInstance(asset)
    instance.configure_motion(MotionOptions(enabled=True, relax_missing=False))
    state = rest_observation(asset, 180)
    instance.evaluate(state, state.captured_at)
    joints = list(state.joints)
    for i in range(11):
        joints[i] = replace(joints[i], visibility=0)
    lost = replace(
        state,
        face=None,
        joints=tuple(joints),
        sequence=state.sequence + 1,
        captured_at=state.captured_at + 0.03,
    )
    actual = instance.evaluate(lost, lost.captured_at)
    assert "head" not in actual.active
    assert actual.tracking_states["head"] == "UNAVAILABLE"
