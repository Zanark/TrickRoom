import math
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from trickroom.demo import demo_observation
from trickroom.tracking import bounded_image, expressions, head_crop, normalize_face, silhouette


def category(name, score):
    return SimpleNamespace(category_name=name, score=score)


def fake_face_result():
    return SimpleNamespace(
        face_landmarks=[
            [
                SimpleNamespace(
                    x=0.5 + 0.2 * math.cos(i / 468 * math.tau),
                    y=0.5 + 0.3 * math.sin(i / 468 * math.tau),
                    z=0,
                )
                for i in range(478)
            ]
        ],
        face_blendshapes=[
            [
                category("eyeBlinkLeft", 0.9),
                category("eyeBlinkRight", 0.1),
                category("jawOpen", 0.6),
            ]
        ],
        facial_transformation_matrixes=[np.eye(4)],
    )


def test_expressions_preserve_anatomical_sides():
    ex = expressions(
        [
            category("eyeBlinkLeft", 0.9),
            category("eyeBlinkRight", 0.1),
            category("jawOpen", 0.7),
            category("mouthSmileLeft", 0.4),
            category("mouthSmileRight", 0.8),
            category("browOuterUpLeft", 0.7),
        ]
    )
    assert ex.blink_left == 0.9 and ex.blink_right == 0.1
    assert ex.jaw_open == 0.7 and ex.smile == pytest.approx(0.6)
    assert ex.brow_left == 0.7 and ex.brow_right == 0


def test_expressions_reject_non_finite_scores():
    with pytest.raises(ValueError):
        expressions([category("jawOpen", float("nan"))])


def test_pose_guided_face_crop_is_bounded_and_uses_input_pixels():
    joints = demo_observation(0, 1).joints
    crop = head_crop(joints, (900, 1200))
    x1, y1, x2, y2 = crop
    nose = joints[0]
    assert 0 <= x1 < nose.x * 900 < x2 <= 900
    assert 0 <= y1 < nose.y * 1200 < y2 <= 1200
    assert x2 - x1 >= 64
    missing = tuple(replace(p, visibility=0) if i < 11 else p for i, p in enumerate(joints))
    assert head_crop(missing, (900, 1200)) is None
    assert head_crop((), (900, 1200)) is None


def test_face_crop_mapping_returns_global_not_crop_coordinates():
    result = fake_face_result()
    face = normalize_face(result, (200, 100, 400, 300), (1000, 800), cropped=True)
    assert face is not None and face.crop_used
    assert all(0.2 <= p.x <= 0.4 and 0.125 <= p.y <= 0.375 for p in face.landmarks)
    assert face.width < 0.1
    assert face.expression.blink_left == 0.9
    assert face.pitch == face.yaw == face.roll == 0


def test_missing_face_is_not_a_neutral_detection():
    result = fake_face_result()
    result.face_landmarks = []
    assert normalize_face(result, (0, 0, 100, 100), (100, 100), cropped=False) is None


def test_invalid_face_matrix_is_rejected():
    result = fake_face_result()
    result.facial_transformation_matrixes = [np.full((4, 4), np.nan)]
    with pytest.raises(ValueError):
        normalize_face(result, (0, 0, 100, 100), (100, 100), cropped=False)


def test_silhouette_is_geometry_not_source_color():
    mask = np.zeros((100, 80), np.float32)
    mask[10:90, 20:60] = 0.9
    outlines = silhouette(mask)
    assert len(outlines) == 1
    assert all(p.usable() for p in outlines[0])
    assert len(outlines[0]) <= 8
    assert silhouette(np.zeros_like(mask)) == ()
    assert silhouette(mask[:, :, np.newaxis]) == outlines
    with pytest.raises(ValueError):
        silhouette(np.full((10, 10), np.nan, np.float32))


def test_tracking_resize_preserves_aspect_and_does_not_upscale():
    image = np.full((1200, 900, 3), (10, 20, 30), np.uint8)
    result = bounded_image(image, 600)
    assert result.shape == (600, 450, 3)
    assert tuple(result[0, 0]) == (30, 20, 10)
    assert bounded_image(image[:100, :100], 600).shape == (100, 100, 3)
