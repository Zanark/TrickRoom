from dataclasses import replace

import pytest

from trickroom.demo import demo_observation
from trickroom.filters import MotionSmoother, OneEuro
from trickroom.state import Point


@pytest.mark.parametrize(
    "point",
    [
        Point(-0.01, 0.5),
        Point(0.5, 1.01),
        Point(float("nan"), 0.5),
        Point(0.5, 0.5, float("inf")),
        Point(0.5, 0.5, visibility=0.49),
        Point(0.5, 0.5, presence=0.49),
    ],
)
def test_unobserved_joint_is_unusable(point):
    assert not point.usable()


def test_visible_joint_requires_both_visibility_and_presence():
    assert Point(0.0, 1.0, visibility=0.5, presence=0.5).usable()


def test_full_cropped_and_stale_states_are_distinct():
    full = demo_observation(0, 10)
    cropped = demo_observation(0, 10, cropped=True)
    assert full.visible_joints == 33
    assert full.body_status(10) == "FULL BODY"
    assert cropped.body_status(10) == "PARTIAL BODY"
    assert cropped.joint(27) is None
    assert cropped.joint(25) is not None
    assert full.body_status(10.61) == "STALE"
    assert full.joint(-1) is None
    assert full.joint(40) is None


def test_hidden_wrist_also_makes_body_partial():
    state = demo_observation(0, 10)
    state = replace(
        state,
        joints=tuple(
            replace(p, visibility=0.1) if i == 15 else p for i, p in enumerate(state.joints)
        ),
    )
    assert state.body_status(10) == "PARTIAL BODY"


def test_one_euro_smooths_but_resets_after_a_gap():
    filt = OneEuro()
    assert filt.update(0.2, 1) == 0.2
    assert 0.2 < filt.update(0.8, 1.03) < 0.8
    assert filt.update(0.9, 2) == 0.9
    with pytest.raises(ValueError):
        filt.update(float("nan"), 3)


def test_filter_preserves_short_blinks_and_raw_confidence():
    smoother = MotionSmoother()
    first = demo_observation(0, 1)
    smoother.apply(first)
    wink = replace(first.face.expression, blink_left=1.0, blink_right=0.0)
    next_frame = replace(
        first,
        captured_at=1.03,
        face=replace(first.face, expression=wink),
        joints=tuple(
            replace(p, visibility=0.1) if i == 15 else p for i, p in enumerate(first.joints)
        ),
    )
    filtered = smoother.apply(next_frame)
    assert filtered.face.expression == wink
    assert filtered.joint(15) is None
    assert filtered.joints[15].visibility == 0.1


def test_reacquired_joint_does_not_smooth_from_old_hidden_position():
    smoother = MotionSmoother()
    state = demo_observation(0, 1)
    smoother.apply(state)
    lost = replace(
        state,
        captured_at=1.03,
        joints=tuple(
            replace(p, visibility=0.1) if i == 15 else p for i, p in enumerate(state.joints)
        ),
    )
    smoother.apply(lost)
    found = replace(
        state,
        captured_at=1.06,
        joints=tuple(replace(p, x=0.45) if i == 15 else p for i, p in enumerate(state.joints)),
    )
    assert smoother.apply(found).joint(15).x == 0.45


def test_head_angle_wrap_takes_short_path():
    smoother = MotionSmoother()
    state = demo_observation(0, 1)
    smoother.apply(replace(state, face=replace(state.face, yaw=179)))
    changed = replace(state, captured_at=1.03, face=replace(state.face, yaw=-179))
    assert 179 < smoother.apply(changed).face.yaw < 182
