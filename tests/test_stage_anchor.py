"""Base-distance anchoring: the first full body fixes stage scale for the session."""

from __future__ import annotations

import math

import pytest

from trickroom.placement import MIN_SPAN, SPAN_JOINTS, StageAnchor, body_span
from trickroom.state import Observation, Point

FRAME = (640, 480)


def observation(top: float, bottom: float, *, frame=FRAME, missing=(), sequence=1):
    """A body whose required joints span `top`..`bottom` in normalized height."""
    joints = []
    for index in range(33):
        if index in missing:
            joints.append(Point(0.5, 0.5, visibility=0.1, presence=0.1))
        elif index in SPAN_JOINTS:
            y = (
                top
                if index in (11, 12)
                else bottom
                if index in (27, 28, 31, 32)
                else (top + bottom) / 2
            )
            joints.append(Point(0.5, y))
        else:
            joints.append(Point(0.5, (top + bottom) / 2))
    return Observation(sequence, 0.0, 0.0, frame, tuple(joints))


def test_body_span_measures_required_joint_extent():
    state = observation(0.1, 0.9)
    assert body_span(state) == pytest.approx(0.8 * FRAME[1])


@pytest.mark.parametrize("missing", [(27,), (11,), (31, 32), (23, 24)])
def test_incomplete_body_has_no_span(missing):
    assert body_span(observation(0.1, 0.9, missing=missing)) is None


def test_degenerate_span_is_rejected():
    assert body_span(observation(0.5, 0.5 + (MIN_SPAN - 2) / FRAME[1])) is None


def test_first_full_body_anchors_and_renders_at_target_height():
    anchor = StageAnchor(target_height=0.7)
    assert not anchor.anchored
    placement = anchor.observe(observation(0.1, 0.9))
    assert anchor.anchored
    assert placement.scale_ratio == pytest.approx(1.0)
    assert placement.height_fraction == pytest.approx(0.7)
    assert placement.depth == pytest.approx(anchor.base_depth)


def test_partial_body_before_any_full_body_does_not_anchor():
    anchor = StageAnchor()
    assert anchor.observe(observation(0.1, 0.9, missing=(27, 28))) is None
    assert not anchor.anchored


def test_stepping_back_shrinks_and_recedes():
    anchor = StageAnchor(target_height=0.7, base_depth=3.0)
    anchor.observe(observation(0.1, 0.9))
    far = anchor.observe(observation(0.3, 0.7))
    assert far.scale_ratio == pytest.approx(0.5)
    assert far.depth == pytest.approx(6.0)
    assert far.height_fraction == pytest.approx(0.35)


def test_stepping_closer_grows_beyond_base():
    anchor = StageAnchor(target_height=0.6, base_depth=4.0)
    anchor.observe(observation(0.3, 0.7))
    near = anchor.observe(observation(0.1, 0.9))
    assert near.scale_ratio == pytest.approx(2.0)
    assert near.depth == pytest.approx(2.0)
    assert near.height_fraction == pytest.approx(1.2)


def test_scale_follows_inverse_depth():
    anchor = StageAnchor(base_depth=3.0)
    anchor.observe(observation(0.1, 0.9))
    for top, bottom in ((0.2, 0.8), (0.25, 0.75), (0.35, 0.65)):
        placement = anchor.observe(observation(top, bottom))
        assert placement.scale_ratio == pytest.approx(anchor.base_depth / placement.depth)


def test_depth_is_clamped_to_the_room_and_reported():
    anchor = StageAnchor(base_depth=3.0, near=0.6, back=8.4)
    anchor.observe(observation(0.1, 0.9))
    far = anchor.observe(observation(0.47, 0.53))
    assert far.clamped
    assert far.depth == pytest.approx(8.4)
    assert far.scale_ratio == pytest.approx(3.0 / 8.4)


def test_anchor_persists_across_a_partial_body_and_reacquisition():
    anchor = StageAnchor()
    first = anchor.observe(observation(0.1, 0.9))
    assert anchor.observe(observation(0.1, 0.9, missing=(27, 28))) is None
    again = anchor.observe(observation(0.1, 0.9))
    assert anchor.base_span == pytest.approx(0.8 * FRAME[1])
    assert again.scale_ratio == pytest.approx(first.scale_ratio)


def test_source_frame_size_change_recaptures():
    anchor = StageAnchor()
    anchor.observe(observation(0.1, 0.9))
    base = anchor.base_span
    placement = anchor.observe(observation(0.3, 0.7, frame=(478, 850)))
    assert anchor.base_span != pytest.approx(base)
    assert anchor.frame_size == (478, 850)
    assert placement.scale_ratio == pytest.approx(1.0)


def test_explicit_reset_recalibrates_on_the_next_full_body():
    anchor = StageAnchor()
    anchor.observe(observation(0.1, 0.9))
    anchor.reset()
    assert not anchor.anchored
    placement = anchor.observe(observation(0.3, 0.7))
    assert placement.scale_ratio == pytest.approx(1.0)
    assert anchor.base_span == pytest.approx(0.4 * FRAME[1])


def test_capture_reports_whether_it_anchored():
    anchor = StageAnchor()
    assert anchor.capture(300.0, FRAME) is True
    assert anchor.capture(120.0, FRAME) is False
    assert anchor.base_span == pytest.approx(300.0)


@pytest.mark.parametrize("span", [0.0, -5.0, float("nan"), float("inf"), MIN_SPAN - 1])
def test_capture_rejects_unusable_spans(span):
    with pytest.raises(ValueError):
        StageAnchor().capture(span, FRAME)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_height": 0.0},
        {"target_height": 1.5},
        {"base_depth": 0.0},
        {"base_depth": float("inf")},
        {"near": 0.0},
        {"near": 9.0},
        {"base_depth": 20.0},
    ],
)
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        StageAnchor(**kwargs)


def test_placement_without_an_anchor_is_none():
    assert StageAnchor().placement(300.0) is None


def test_placement_rejects_an_unusable_measurement():
    anchor = StageAnchor()
    anchor.capture(300.0, FRAME)
    with pytest.raises(ValueError):
        anchor.placement(float("nan"))


def test_anchor_is_session_only_state():
    anchor = StageAnchor()
    anchor.observe(observation(0.1, 0.9))
    assert math.isfinite(anchor.base_span)
    anchor.reset()
    assert anchor.base_span is None and anchor.frame_size is None
