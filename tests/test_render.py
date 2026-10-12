from dataclasses import replace

import numpy as np
import pytest

from trickroom.demo import demo_observation
from trickroom.render import Renderer, StageOptions, Viewport, _head_anchor, draw_head, viewport


def clean_options(mirror=False):
    return StageOptions(
        mirror=mirror, outline=True, skeleton=True, grid=False, head_detail=False, hud=False
    )


def test_clean_mirror_is_exactly_presentation_only():
    state = demo_observation(1, 10)
    renderer = Renderer()
    normal = renderer.render(state, (640, 480), now=10, options=clean_options(False))
    mirrored = renderer.render(state, (640, 480), now=10, options=clean_options(True))
    assert np.array_equal(mirrored, normal[:, ::-1])
    assert state.joint(11).x > state.joint(12).x


def test_landmark_motion_reaches_output():
    renderer = Renderer()
    first = renderer.render(demo_observation(0, 10), now=10)
    second = renderer.render(demo_observation(1, 10), now=10)
    assert np.count_nonzero(np.any(first != second, axis=2)) > 3000


def test_stale_observations_no_longer_render_the_body():
    state = demo_observation(0, 10)
    renderer = Renderer()
    fresh = renderer.render(state, now=10, options=clean_options())
    expired = renderer.render(state, now=11, options=clean_options())
    assert np.count_nonzero(np.any(fresh != expired, axis=2)) > 3000
    # Changing all stale body/face geometry must not affect the stale output.
    changed = demo_observation(2, 10)
    assert np.array_equal(expired, renderer.render(changed, now=11, options=clean_options()))


def test_missing_face_still_has_pose_attached_head_but_no_expressions():
    state = replace(demo_observation(0, 10), face=None)
    anchor = _head_anchor(state, Viewport(0, 0, 900, 1200))
    assert anchor is not None and anchor[3] is None
    result = Renderer().render(state, now=10)
    assert result.dtype == np.uint8 and result.shape == (720, 960, 3)


@pytest.mark.parametrize("size", [(320, 240), (960, 720), (640, 960), (1600, 300)])
def test_stage_fits_portrait_landscape_and_cropped_input(size):
    state = demo_observation(1, 10, cropped=True)
    image = Renderer().render(state, size, now=10)
    assert image.shape == (size[1], size[0], 3)
    assert state.joint(27) is None


def test_viewport_preserves_camera_aspect():
    view = viewport((640, 480), (900, 1200), True)
    assert view.width / view.height == pytest.approx(900 / 1200)


def test_head_blinks_are_independent_and_mouth_reacts():
    neutral = replace(demo_observation(0, 10).face, pitch=0, yaw=0, roll=0)
    images = []
    for name in ("blink_left", "blink_right", "jaw_open", "smile", "brow_left"):
        image = np.zeros((240, 240, 3), np.uint8)
        face = replace(neutral, expression=replace(neutral.expression, **{name: 1.0}))
        draw_head(image, (120, 115), 150, 180, face)
        images.append(image)
    assert all(not np.array_equal(images[0], image) for image in images[1:])
    assert all(np.count_nonzero(image) > 1000 for image in images)


@pytest.mark.parametrize("pitch,yaw,roll", [(-40, 60, 20), (40, -60, -20), (0, 100, 0)])
def test_head_turns_render_finite_valid_pixels(pitch, yaw, roll):
    state = demo_observation(0, 10)
    state = replace(state, face=replace(state.face, pitch=pitch, yaw=yaw, roll=roll))
    image = Renderer().render(state, now=10)
    assert image.dtype == np.uint8
    assert image.min() >= 0 and image.max() <= 255
