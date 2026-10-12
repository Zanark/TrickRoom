"""glTF TRS/morph sampling and linear blend skinning, independently testable from graphics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from trickroom.assets.math3d import compose, slerp, transform_points
from trickroom.assets.types import Asset, Clip, Primitive


@dataclass(frozen=True)
class DeformedPrimitive:
    source: Primitive
    positions: np.ndarray
    normals: np.ndarray | None


def sample_clip(clip: Clip, seconds: float, *, loop: bool = True):
    time = max(0.0, seconds)
    if loop and clip.duration > 0:
        time %= clip.duration
    trs, weights = {}, {}
    for channel in clip.channels:
        times, values = channel.times, channel.values
        right = int(np.searchsorted(times, time, side="right"))
        if right == 0:
            value = values[0].copy()
        elif right >= len(times):
            value = values[-1].copy()
        else:
            left = right - 1
            factor = (time - times[left]) / (times[right] - times[left])
            if channel.interpolation == "STEP":
                value = values[left].copy()
            elif channel.path == "rotation":
                value = slerp(values[left], values[right], factor)
            else:
                value = values[left] * (1 - factor) + values[right] * factor
        if channel.path == "weights":
            weights[channel.node] = value
        else:
            trs.setdefault(channel.node, {})[channel.path] = value
    return trs, weights


def global_transforms(asset: Asset, overrides=None):
    overrides = overrides or {}
    result = np.tile(np.eye(4), (len(asset.nodes), 1, 1))
    for index in asset.order:
        node = asset.nodes[index]
        values = overrides.get(index, {})
        local = compose(
            values.get("translation", node.translation),
            values.get("rotation", node.rotation),
            values.get("scale", node.scale),
        )
        result[index] = result[node.parent] @ local if node.parent >= 0 else local
    return result


def deform(asset: Asset, globals_: np.ndarray, morph_weights: dict[int, np.ndarray]):
    joint_matrices = [globals_[list(skin.joints)] @ skin.inverse_bind for skin in asset.skins]
    joint_normals = [np.linalg.inv(m[:, :3, :3]).transpose(0, 2, 1) for m in joint_matrices]
    result = []
    for primitive in asset.primitives:
        weights = morph_weights.get(primitive.node, primitive.default_weights)
        positions = primitive.positions.copy()
        normals = primitive.normals.copy() if primitive.normals is not None else None
        if len(weights):
            positions += np.einsum("t,tvc->vc", weights, primitive.morph_positions)
            if normals is not None:
                normals += np.einsum("t,tvc->vc", weights, primitive.morph_normals)
        skin = asset.nodes[primitive.node].skin
        if skin is None:
            matrix = globals_[primitive.node]
            positions = transform_points(positions, matrix)
            if normals is not None:
                normals = normals @ np.linalg.inv(matrix[:3, :3])
        else:
            matrices, normal_matrices = joint_matrices[skin], joint_normals[skin]
            skinned = np.zeros_like(positions)
            normal_result = np.zeros_like(normals) if normals is not None else None
            for slot in range(4):
                joints = primitive.joints[:, slot]
                influence = primitive.weights[:, slot, None]
                matrix = matrices[joints]
                skinned += (
                    np.einsum("vij,vj->vi", matrix[:, :3, :3], positions) + matrix[:, :3, 3]
                ) * influence
                if normals is not None:
                    normal_result += (
                        np.einsum("vij,vj->vi", normal_matrices[joints], normals) * influence
                    )
            positions, normals = skinned, normal_result
        if normals is not None:
            lengths = np.linalg.norm(normals, axis=1, keepdims=True)
            normals = normals / np.maximum(lengths, 1e-9)
        result.append(DeformedPrimitive(primitive, positions, normals))
    return tuple(result)
