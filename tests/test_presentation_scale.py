from dataclasses import replace

import numpy as np
import pytest
from glb_helpers import FIXTURE

from trickroom.assets.gltf import load_asset
from trickroom.assets.motion import MotionOptions
from trickroom.assets.presentation import calibration_ratio, present
from trickroom.assets.retarget import AvatarInstance, Evaluation
from trickroom.render import viewport
from trickroom.state import Observation, Point

MAPPED_JOINTS = {
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
def asset():
    return load_asset(FIXTURE)


def projected_observation(asset, scale=200.0, now=1.0, globals_=None):
    globals_ = asset.rest_globals if globals_ is None else globals_
    joints = [Point(0, 0, visibility=0, presence=0) for _ in range(33)]
    world = list(joints)
    for i, name in MAPPED_JOINTS.items():
        x, y, z = globals_[asset.bones[name], :3, 3]
        joints[i] = Point((500 + x * scale) / 1000, (800 - y * scale) / 1000, -z * scale / 1000)
        world[i] = Point(x, -y, -z)
    return Observation(round(now * 100), now, now, (1000, 1000), tuple(joints), tuple(world))


def evaluation(asset, globals_=None):
    return Evaluation(
        (), asset.rest_globals if globals_ is None else globals_, set(asset.bones), (), "live"
    )


def test_projected_rig_scale_matches_image_measurements(asset):
    instance = AvatarInstance(asset)
    state = projected_observation(asset)
    assert calibration_ratio(instance, state, evaluation(asset)) == pytest.approx(0.2)


def test_depth_noise_cannot_inflate_the_image_scale_measurement(asset):
    instance = AvatarInstance(asset)
    state = projected_observation(asset)
    noisy = replace(
        state, joints=tuple(replace(p, z=i * 100.0) for i, p in enumerate(state.joints))
    )
    assert calibration_ratio(instance, noisy, evaluation(asset)) == pytest.approx(0.2)


@pytest.mark.parametrize("factor", [0.01, 1.0, 100.0])
def test_export_unit_scale_cancels_out_of_final_projected_size(asset, factor):
    state = projected_observation(asset)
    globals_ = asset.rest_globals.copy()
    globals_[:, :3, 3] *= factor
    scaled = replace(asset, rest_globals=globals_)
    ratio = calibration_ratio(AvatarInstance(scaled), state, evaluation(scaled))
    assert ratio * factor == pytest.approx(0.2)


def test_end_on_limbs_are_excluded_without_losing_other_scale_evidence(asset):
    rotation = np.array(((0.0, 0, 1), (0, 1, 0), (-1, 0, 0)))
    globals_ = asset.rest_globals.copy()
    globals_[:, :3, 3] = globals_[:, :3, 3] @ rotation.T
    state = projected_observation(asset, globals_=globals_)
    assert calibration_ratio(
        AvatarInstance(asset), state, evaluation(asset, globals_)
    ) == pytest.approx(0.2)


def test_two_partial_spans_do_not_establish_scale(asset):
    state = projected_observation(asset)
    state = replace(
        state,
        joints=tuple(
            p if i in (11, 12, 13) else replace(p, visibility=0) for i, p in enumerate(state.joints)
        ),
    )
    assert calibration_ratio(AvatarInstance(asset), state, evaluation(asset)) is None


def test_world_mode_does_not_calibrate_using_missing_world_detections(asset):
    instance = AvatarInstance(asset)
    instance.configure_motion(MotionOptions(enabled=True))
    state = replace(projected_observation(asset), world_joints=())
    assert calibration_ratio(instance, state, evaluation(asset)) is None


def test_initial_closeup_does_not_lock_scale_for_later_frames(asset):
    instance = AvatarInstance(asset)
    closeup = projected_observation(asset, scale=400.0)
    instance.update_scale(closeup, 1.46)
    values = []
    for i in range(1, 31):
        state = projected_observation(asset, scale=200.0, now=1 + i / 30)
        values.append(instance.update_scale(state, 0.2))
    assert 0.2 < values[0] < 1.46
    assert values[-1] == pytest.approx(0.2, rel=0.01)


def test_scale_updates_only_once_per_detection_not_per_window(asset):
    instance = AvatarInstance(asset)
    first = projected_observation(asset, now=1)
    second = projected_observation(asset, now=1.03)
    instance.update_scale(first, 0.4)
    scale = instance.update_scale(second, 0.2)
    for _ in range(10):
        assert instance.update_scale(replace(second), 0.2) == scale
    assert instance._scale_filter.time == second.captured_at


@pytest.mark.parametrize("change", ("rewind", "resize", "gap"))
def test_new_source_timing_or_dimensions_cannot_reuse_old_scale(asset, change):
    instance = AvatarInstance(asset)
    first = projected_observation(asset, now=10)
    instance.update_scale(first, 1.46)
    second = replace(first, sequence=1100, captured_at=10.1)
    if change == "rewind":
        second = replace(second, sequence=1, captured_at=1)
    elif change == "resize":
        second = replace(second, frame_size=(500, 1000))
    else:
        second = replace(second, captured_at=11)
    assert instance.update_scale(second, None) is None
    assert instance.update_scale(
        replace(second, sequence=1200, captured_at=12), 0.2
    ) == pytest.approx(0.2)


def test_missing_scale_evidence_is_held_only_briefly(asset):
    instance = AvatarInstance(asset)
    instance.update_scale(projected_observation(asset, now=1), 0.2)
    for i in range(1, 6):
        assert instance.update_scale(
            projected_observation(asset, now=1 + i / 10), None
        ) == pytest.approx(0.2)
    assert instance.update_scale(projected_observation(asset, now=1.7), None) is None


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_scale_measurement_is_reported(asset, value):
    with pytest.raises(ValueError, match="finite and positive"):
        AvatarInstance(asset).update_scale(projected_observation(asset), value)


def test_reset_scale_discards_smoothing_history(asset):
    instance = AvatarInstance(asset)
    state = projected_observation(asset)
    instance.update_scale(state, 1.46)
    instance.reset_calibration()
    assert instance.update_scale(state, 0.2) == pytest.approx(0.2)


def test_real_presentation_recovers_size_without_changing_bone_lengths(asset):
    instance = AvatarInstance(asset)
    view = viewport((640, 480), (1000, 1000), False)
    first = projected_observation(asset, scale=350.0, now=1.0)
    present(instance, first, view, 1)
    for i in range(1, 31):
        state = projected_observation(asset, scale=150.0, now=1 + i / 30)
        frame = present(instance, state, view, state.captured_at)
    assert frame is not None
    assert instance.calibrated_scale == pytest.approx(0.15, rel=0.03)
    for i, node in enumerate(asset.nodes):
        if node.parent >= 0:
            rest = np.linalg.norm(
                asset.rest_globals[i, :3, 3] - asset.rest_globals[node.parent, :3, 3]
            )
            current = np.linalg.norm(
                frame.evaluation.globals[i, :3, 3] - frame.evaluation.globals[node.parent, :3, 3]
            )
            assert current == pytest.approx(rest, abs=1e-6)
