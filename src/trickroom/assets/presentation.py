"""Project a skinned imported character without changing its authored bone lengths."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from trickroom.assets.retarget import SEGMENTS, AvatarInstance, Evaluation, observed_points
from trickroom.avatar import Footprint
from trickroom.raster import TexturedBatch
from trickroom.state import Observation


@dataclass(frozen=True)
class ModelPresentation:
    batches: list[TexturedBatch]
    footprints: list[Footprint]
    evaluation: Evaluation


def calibration_ratio(
    instance: AvatarInstance, state: Observation, evaluation: Evaluation
) -> float | None:
    asset = instance.asset
    points = observed_points(state)
    ratios = []

    def add_span(image_delta, posed_delta, rest_delta):
        projected = float(np.linalg.norm(posed_delta[:2]))
        measured = float(np.linalg.norm(image_delta[:2]))
        rest_length = float(np.linalg.norm(rest_delta))
        # Near end-on bones do not provide a reliable screen-space scale measurement.
        if rest_length > 1e-9 and projected > rest_length * 0.15 and measured > 4:
            ratios.append(measured / projected)

    pairs = [(logical, child, start, end) for logical, (start, end, child) in SEGMENTS.items()] + [
        ("upper_arm_left", "upper_arm_right", 11, 12),
        ("upper_leg_left", "upper_leg_right", 23, 24),
    ]
    for logical, child, start, end in pairs:
        if not all(i in points for i in (start, end)):
            continue
        if instance.motion.options.enabled and instance.motion.options.space == "world":
            if state.world_joint(start) is None or state.world_joint(end) is None:
                continue
        a, b = asset.bones[logical], asset.bones[child]
        add_span(
            points[end] - points[start],
            evaluation.globals[b, :3, 3] - evaluation.globals[a, :3, 3],
            asset.rest_globals[b, :3, 3] - asset.rest_globals[a, :3, 3],
        )
    torso = (11, 12, 23, 24)
    if all(i in points for i in torso) and (
        not instance.motion.options.enabled
        or instance.motion.options.space == "image"
        or all(state.world_joint(i) is not None for i in torso)
    ):
        shoulders = [asset.bones[name] for name in ("upper_arm_left", "upper_arm_right")]
        hips = [asset.bones[name] for name in ("upper_leg_left", "upper_leg_right")]
        add_span(
            (points[11] + points[12] - points[23] - points[24]) / 2,
            evaluation.globals[shoulders, :3, 3].mean(0) - evaluation.globals[hips, :3, 3].mean(0),
            asset.rest_globals[shoulders, :3, 3].mean(0) - asset.rest_globals[hips, :3, 3].mean(0),
        )
    if len(ratios) < 3:
        return None
    return float(np.median(ratios)) / max(state.frame_size)


def _head_bounds(instance, evaluation):
    points = []
    for i, primitive in enumerate(evaluation.primitives):
        indices = primitive.source.indices[instance.head_triangles(i)]
        if len(indices):
            points.append(primitive.positions[indices].reshape(-1, 3))
    if not points:
        index = instance.asset.bones["head"]
        center = evaluation.globals[index, :3, 3]
        return np.array((center - 0.1, center + 0.1))
    all_points = np.vstack(points)
    return np.array((all_points.min(axis=0), all_points.max(axis=0)))


def _batches(instance, evaluation, scale, offset, *, head_only=False, face_unavailable=False):
    batches, footprints = [], []
    asset = instance.asset
    flip = np.array((1.0, -1.0, 1.0))
    for i, deformed in enumerate(evaluation.primitives):
        primitive = deformed.source
        visible = evaluation.visible[i].copy()
        if head_only:
            visible &= instance.head_triangles(i)
        indices = primitive.indices[visible]
        if not len(indices):
            continue
        points = deformed.positions * flip * scale + offset
        if deformed.normals is None:
            triangles = deformed.positions[indices]
            normal = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
            normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-9)
            normals = np.repeat((normal * flip)[:, None, :], 3, axis=1)
        else:
            normals = (deformed.normals * flip)[indices]
        colors = primitive.colors[indices].copy()
        if face_unavailable:
            colors[instance.head_triangles(i)[visible], :, :3] *= 0.62
        material = asset.materials[primitive.material]
        texture = asset.textures[material.texture] if material.texture is not None else None
        batches.append(
            TexturedBatch(
                points[indices], normals, primitive.uv[indices], colors, material, texture
            )
        )
        if not head_only:
            for side in ("left", "right"):
                if f"foot_{side}" not in evaluation.active:
                    continue
                mask = instance.foot_vertices(i, side)
                used = np.zeros(len(points), bool)
                used[indices.ravel()] = True
                foot = points[mask & used]
                if len(foot):
                    low, high = foot.min(axis=0), foot.max(axis=0)
                    footprints.append(
                        Footprint(
                            (float((low[0] + high[0]) / 2), float(high[1])), float(high[0] - low[0])
                        )
                    )
    return batches, footprints


def present(
    instance: AvatarInstance,
    state: Observation | None,
    view,
    now: float,
) -> ModelPresentation | None:
    evaluation = instance.evaluate(state, now)
    asset = instance.asset
    if instance.preview:
        dimensions = asset.bounds[1] - asset.bounds[0]
        scale = min(
            view.width * 0.9 / max(dimensions[0], 0.01),
            view.height * 0.92 / max(dimensions[1], 0.01),
        )
        center_x = (asset.bounds[0, 0] + asset.bounds[1, 0]) / 2
        offset = np.array(
            (
                view.x + view.width / 2 - center_x * scale,
                view.y + view.height * 0.98 + asset.bounds[0, 1] * scale,
                0,
            )
        )
    else:
        if state is None:
            return None
        placement = evaluation.placement or state
        normalized = instance.update_scale(
            state, calibration_ratio(instance, placement, evaluation)
        )
        points = observed_points(placement)
        if normalized is not None and all(i in points for i in (23, 24)):
            anchor = (points[23] + points[24]) / 2
            model_anchor = evaluation.globals[asset.bones["hips"], :3, 3]
        elif normalized is not None and all(i in points for i in (11, 12)):
            anchor = (points[11] + points[12]) / 2
            model_anchor = (
                evaluation.globals[asset.bones["upper_arm_left"], :3, 3]
                + evaluation.globals[asset.bones["upper_arm_right"], :3, 3]
            ) / 2
        elif state.face is not None:
            face = state.face
            bounds = _head_bounds(instance, evaluation)
            model_anchor = bounds.mean(axis=0)
            normalized = (
                face.height
                * state.frame_size[1]
                / max(
                    bounds[1, 1] - bounds[0, 1],
                    0.05,
                )
                / max(state.frame_size)
            )
            anchor = np.array(
                (face.center.x * state.frame_size[0], -face.center.y * state.frame_size[1], 0)
            )
        else:
            return None
        source_scale = view.width / state.frame_size[0]
        scale = normalized * max(state.frame_size) * source_scale
        pixel_anchor = np.array(
            (view.x + anchor[0] * source_scale, view.y - anchor[1] * source_scale, 0)
        )
        offset = pixel_anchor - model_anchor * np.array((1, -1, 1)) * scale
    batches, footprints = _batches(
        instance,
        evaluation,
        scale,
        offset,
        face_unavailable=not instance.preview and state.face is None,
    )
    return ModelPresentation(batches, footprints, evaluation)


def head_presentation(instance: AvatarInstance, evaluation: Evaluation, width: int, height: int):
    bounds = _head_bounds(instance, evaluation)
    dimensions = bounds[1] - bounds[0]
    scale = min(width * 0.9 / max(dimensions[0], 0.01), height * 0.88 / max(dimensions[1], 0.01))
    offset = np.array((width / 2, height / 2, 0)) - bounds.mean(axis=0) * (1, -1, 1) * scale
    batches, _ = _batches(instance, evaluation, scale, offset, head_only=True)
    return batches
