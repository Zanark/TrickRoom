from dataclasses import replace

import pytest

from trickroom.demo import demo_observation
from trickroom.face_response import FaceResponse
from trickroom.state import Expression


def state_at(time, expression):
    state = demo_observation(time, time)
    return replace(state, face=replace(state.face, expression=expression))


def calibrate_neutral(response):
    response.begin("neutral", 1)
    for i in range(32):
        response.apply(state_at(1 + i / 30, Expression(jaw_open=0.12, smile=0.08)), 1 + i / 30)
    assert response.calibrated and response.enabled


def test_disabled_response_preserves_original_observation():
    response = FaceResponse()
    state = state_at(1, Expression(jaw_open=0.4))
    assert response.apply(state, 1) is state


def test_neutral_calibration_is_explicit_and_does_not_mutate_detector_values():
    response = FaceResponse()
    calibrate_neutral(response)
    state = state_at(3, Expression(jaw_open=0.12, smile=0.08))
    shaped = response.apply(state, 3)
    assert shaped.face.expression.jaw_open == 0
    assert shaped.face.expression.smile == 0
    assert state.face.expression.jaw_open == 0.12
    assert shaped.joints is state.joints and shaped.face.landmarks is state.face.landmarks


def test_single_frame_wink_survives_and_does_not_close_the_other_eye():
    response = FaceResponse()
    response.enabled = True
    response.apply(state_at(1, Expression()), 1)
    wink = response.apply(state_at(1.04, Expression(blink_left=1)), 1.04)
    assert wink.face.expression.blink_left == 1
    assert wink.face.expression.blink_right == 0
    opened = response.apply(state_at(1.08, Expression()), 1.08)
    assert opened.face.expression.blink_left == 0


def test_range_capture_changes_only_controls_with_observed_excursion():
    response = FaceResponse()
    with pytest.raises(ValueError, match="neutral"):
        response.begin("range", 1)
    calibrate_neutral(response)
    response.begin("range", 3)
    for i in range(92):
        time = 3 + i / 30
        response.apply(state_at(time, Expression(jaw_open=0.5)), time)
    shaped = response.apply(state_at(7, Expression(jaw_open=0.5)), 7)
    assert shaped.face.expression.jaw_open == pytest.approx(1)
    assert "Range captured" in response.message
    assert response.high[0] == 1


def test_lost_or_unstable_face_cancels_calibration_without_false_success():
    response = FaceResponse()
    response.begin("neutral", 1)
    response.apply(None, 1.2)
    assert not response.calibrated and response.collecting is None
    assert "cancelled" in response.message
    response.begin("neutral", 2)
    for i in range(32):
        time = 2 + i / 30
        response.apply(state_at(time, Expression(jaw_open=float(i % 2))), time)
    assert not response.calibrated
    assert "unstable" in response.message


def test_duplicate_render_updates_do_not_collect_duplicate_samples():
    response = FaceResponse()
    response.begin("neutral", 1)
    state = state_at(1, Expression())
    for _ in range(20):
        response.apply(state, 1)
        response.set_gain("smile", 1)
    assert len(response.samples) == 1


def test_loss_resets_response_filter_and_invalid_gain_is_explicit():
    response = FaceResponse()
    response.enabled = True
    response.apply(state_at(1, Expression()), 1)
    response.apply(None, 1.01)
    assert (
        response.apply(state_at(1.03, Expression(jaw_open=1)), 1.03).face.expression.jaw_open == 1
    )
    with pytest.raises(ValueError, match="gain"):
        response.set_gain("jaw_open", float("nan"))
