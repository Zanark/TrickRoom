"""Same-frame pose and face inference, off the presentation thread."""

from __future__ import annotations

import math
import time
from contextlib import ExitStack
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from trickroom.camera import CapturedFrame
from trickroom.filters import MotionSmoother
from trickroom.models import ensure_models
from trickroom.state import Expression, Face, Observation, Point


def bounded_image(image: NDArray[np.uint8], max_side: int) -> NDArray[np.uint8]:
    h, w = image.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        image = cv2.resize(
            image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA
        )
    return np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


def head_crop(
    joints: tuple[Point, ...],
    size: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    if len(joints) != 33 or not joints[0].usable():
        return None
    head = [joints[i] for i in (0, 2, 5, 7, 8, 9, 10) if joints[i].usable()]
    if len(head) < 3:
        return None
    w, h = size
    xs, ys = [p.x * w for p in head], [p.y * h for p in head]
    shoulder_span = 0.0
    if joints[11].usable() and joints[12].usable():
        shoulder_span = math.hypot(
            (joints[11].x - joints[12].x) * w,
            (joints[11].y - joints[12].y) * h,
        )
    side = max((max(xs) - min(xs)) * 2.0, (max(ys) - min(ys)) * 3.0, shoulder_span * 0.70, 64.0)
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2 - side * 0.07
    x1, y1 = max(0, round(cx - side / 2)), max(0, round(cy - side / 2))
    x2, y2 = min(w, round(cx + side / 2)), min(h, round(cy + side / 2))
    return (x1, y1, x2, y2) if x2 - x1 >= 32 and y2 - y1 >= 32 else None


def _point(value: object) -> Point:
    return Point(
        float(value.x),
        float(value.y),
        float(value.z),
        float(value.visibility if value.visibility is not None else 1.0),
        float(value.presence if value.presence is not None else 1.0),
    )


def expressions(categories: list) -> Expression:
    scores: dict[str, float] = {}
    for category in categories:
        score = float(category.score)
        if not math.isfinite(score):
            raise ValueError("Face model produced a non-finite expression score.")
        scores[category.category_name] = max(0.0, min(1.0, score))

    def score(name: str) -> float:
        return scores.get(name, 0.0)

    return Expression(
        blink_left=score("eyeBlinkLeft"),
        blink_right=score("eyeBlinkRight"),
        jaw_open=score("jawOpen"),
        smile=(score("mouthSmileLeft") + score("mouthSmileRight")) / 2,
        brow_left=min(1.0, score("browInnerUp") + score("browOuterUpLeft")) - score("browDownLeft"),
        brow_right=min(1.0, score("browInnerUp") + score("browOuterUpRight"))
        - score("browDownRight"),
        gaze_x=(
            score("eyeLookInLeft")
            - score("eyeLookOutLeft")
            + score("eyeLookOutRight")
            - score("eyeLookInRight")
        )
        / 2,
        gaze_y=(
            score("eyeLookDownLeft")
            + score("eyeLookDownRight")
            - score("eyeLookUpLeft")
            - score("eyeLookUpRight")
        )
        / 2,
    )


def normalize_face(
    result: object,
    region: tuple[int, int, int, int],
    size: tuple[int, int],
    *,
    cropped: bool,
) -> Face | None:
    if not result.face_landmarks:
        return None
    raw = result.face_landmarks[0]
    if len(raw) < 468:
        raise ValueError("Face model returned an incomplete landmark set.")
    x1, y1, x2, y2 = region
    w, h = size
    points = tuple(
        Point(
            (x1 + point.x * (x2 - x1)) / w,
            (y1 + point.y * (y2 - y1)) / h,
            point.z * (x2 - x1) / w,
        )
        for point in raw
    )
    if not all(math.isfinite(v) for p in points for v in (p.x, p.y, p.z)):
        raise ValueError("Face model returned non-finite landmarks.")
    # Use the facial oval, not iris displacement, for head bounds.
    oval = (
        10,
        338,
        297,
        332,
        284,
        251,
        389,
        356,
        454,
        323,
        361,
        288,
        397,
        365,
        379,
        378,
        400,
        377,
        152,
        148,
        176,
        149,
        150,
        136,
        172,
        58,
        132,
        93,
        234,
        127,
        162,
        21,
        54,
        103,
        67,
        109,
    )
    xs, ys = [points[i].x for i in oval], [points[i].y for i in oval]
    center = Point((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    if not center.usable() or max(xs) - min(xs) < 0.003:
        return None
    if not result.facial_transformation_matrixes or not result.face_blendshapes:
        raise ValueError("Face model must return transformation matrices and blendshapes.")
    matrix = np.asarray(result.facial_transformation_matrixes[0], dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError("Face transformation matrix is invalid.")
    pitch, yaw, roll = cv2.RQDecomp3x3(matrix[:3, :3])[0]
    return Face(
        center,
        max(xs) - min(xs),
        max(ys) - min(ys),
        float(pitch),
        float(yaw),
        float(roll),
        expressions(result.face_blendshapes[0]),
        points,
        cropped,
    )


def silhouette(mask: NDArray[np.float32]) -> tuple[tuple[Point, ...], ...]:
    if mask.ndim == 3 and mask.shape[2] == 1:
        mask = mask[:, :, 0]
    if mask.ndim != 2 or not np.isfinite(mask).all():
        raise ValueError("Segmentation mask must be a finite two-dimensional array.")
    binary = np.uint8(mask >= 0.55) * 255
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    found, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = mask.shape
    contours = []
    for contour in sorted(found, key=cv2.contourArea, reverse=True)[:3]:
        if cv2.contourArea(contour) < w * h * 0.005:
            continue
        simple = cv2.approxPolyDP(contour, max(1.2, cv2.arcLength(contour, True) * 0.002), True)
        if len(simple) >= 3:
            contours.append(tuple(Point(float(p[0][0]) / w, float(p[0][1]) / h) for p in simple))
    return tuple(contours)


class Tracker:
    """Sequential VIDEO tasks in a worker: temporally paired, never blocking the UI."""

    def __init__(self, model_directory: Path, max_side: int = 768, smooth: bool = True) -> None:
        if not 256 <= max_side <= 1920:
            raise ValueError("Tracking size must be between 256 and 1920 pixels.")
        pose_path, face_path = ensure_models(model_directory)
        import mediapipe as mp

        self._mp = mp
        self.max_side = max_side
        self._timestamp = -1
        self._face_misses = 0
        self._smoother = MotionSmoother() if smooth else None
        self._resources = ExitStack()
        vision = mp.tasks.vision
        try:
            self._pose = self._resources.enter_context(
                vision.PoseLandmarker.create_from_options(
                    vision.PoseLandmarkerOptions(
                        base_options=mp.tasks.BaseOptions(model_asset_path=str(pose_path)),
                        running_mode=vision.RunningMode.VIDEO,
                        num_poses=1,
                        output_segmentation_masks=True,
                        min_pose_detection_confidence=0.5,
                        min_pose_presence_confidence=0.5,
                        min_tracking_confidence=0.5,
                    ),
                )
            )
            self._face = self._resources.enter_context(
                vision.FaceLandmarker.create_from_options(
                    vision.FaceLandmarkerOptions(
                        base_options=mp.tasks.BaseOptions(model_asset_path=str(face_path)),
                        running_mode=vision.RunningMode.VIDEO,
                        num_faces=1,
                        output_face_blendshapes=True,
                        output_facial_transformation_matrixes=True,
                        min_face_detection_confidence=0.5,
                        min_face_presence_confidence=0.5,
                        min_tracking_confidence=0.5,
                    ),
                )
            )
        except (RuntimeError, ValueError, OSError):
            self._resources.close()
            raise

    def close(self) -> None:
        self._resources.close()

    def process(self, frame: CapturedFrame) -> Observation:
        start = time.perf_counter()
        image = frame.image
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError("Tracking requires a uint8 BGR camera frame.")
        h, w = image.shape[:2]
        timestamp = max(self._timestamp + 1, round(frame.captured_at * 1000))
        self._timestamp = timestamp
        pose_result = self._pose.detect_for_video(
            self._mp.Image(
                image_format=self._mp.ImageFormat.SRGB,
                data=bounded_image(image, self.max_side),
            ),
            timestamp,
        )
        joints = (
            tuple(_point(p) for p in pose_result.pose_landmarks[0])
            if pose_result.pose_landmarks
            else ()
        )
        world = (
            tuple(_point(p) for p in pose_result.pose_world_landmarks[0])
            if pose_result.pose_world_landmarks
            else ()
        )
        if joints and len(joints) != 33:
            raise ValueError("Pose model returned an incomplete landmark set.")
        expected_crop = head_crop(joints, (w, h))
        # Periodically reacquire on the full frame after crop detection failures.
        region = expected_crop
        if self._face_misses > 0 and self._face_misses % 8 == 0:
            region = None
        region = region or (0, 0, w, h)
        x1, y1, x2, y2 = region
        cropped = region != (0, 0, w, h)
        face_result = self._face.detect_for_video(
            self._mp.Image(
                image_format=self._mp.ImageFormat.SRGB,
                data=bounded_image(image[y1:y2, x1:x2], 512 if cropped else 960),
            ),
            timestamp,
        )
        face = normalize_face(face_result, region, (w, h), cropped=cropped)
        if face is not None and expected_crop is not None:
            ex1, ey1, ex2, ey2 = expected_crop
            if not (ex1 <= face.center.x * w <= ex2 and ey1 <= face.center.y * h <= ey2):
                face = None
        self._face_misses = 0 if face is not None else self._face_misses + 1
        contours = ()
        if joints and pose_result.segmentation_masks:
            contours = silhouette(pose_result.segmentation_masks[0].numpy_view())
        observation = Observation(
            frame.sequence,
            frame.captured_at,
            time.perf_counter(),
            (w, h),
            joints,
            world,
            face,
            contours,
            (time.perf_counter() - start) * 1000,
            frame.media_time,
            frame.generation,
        )
        return self._smoother.apply(observation) if self._smoother is not None else observation
