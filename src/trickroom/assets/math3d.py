"""Column-vector glTF transforms; quaternions are always x, y, z, w."""

from __future__ import annotations

import math

import numpy as np


def normalize(vector, fallback=None):
    vector = np.asarray(vector, dtype=float)
    length = float(np.linalg.norm(vector))
    if length <= 1e-9:
        if fallback is None:
            raise ValueError("Cannot normalize a zero-length vector.")
        return np.asarray(fallback, dtype=float).copy()
    return vector / length


def quaternion_matrix(quaternion):
    x, y, z, w = normalize(quaternion)
    return np.array(
        (
            (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
        )
    )


def matrix_quaternion(rotation):
    matrix = np.asarray(rotation, dtype=float)
    # Eigenvector form remains stable near a 180-degree rotation.
    m00, m01, m02 = matrix[0]
    m10, m11, m12 = matrix[1]
    m20, m21, m22 = matrix[2]
    k = (
        np.array(
            (
                (m00 - m11 - m22, m01 + m10, m02 + m20, m21 - m12),
                (m01 + m10, m11 - m00 - m22, m12 + m21, m02 - m20),
                (m02 + m20, m12 + m21, m22 - m00 - m11, m10 - m01),
                (m21 - m12, m02 - m20, m10 - m01, m00 + m11 + m22),
            )
        )
        / 3
    )
    _, vectors = np.linalg.eigh(k)
    q = vectors[:, -1]
    return -q if q[3] < 0 else q


def compose(translation, rotation, scale):
    result = np.eye(4)
    result[:3, :3] = quaternion_matrix(rotation) @ np.diag(scale)
    result[:3, 3] = translation
    return result


def decompose(matrix):
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError("Transform must be a finite 4x4 matrix.")
    if not np.allclose(matrix[3], (0, 0, 0, 1), atol=1e-6):
        raise ValueError("Perspective node matrices are not supported.")
    scale = np.linalg.norm(matrix[:3, :3], axis=0)
    if np.any(scale < 1e-7) or np.linalg.det(matrix[:3, :3]) <= 0:
        raise ValueError("Apply zero/negative scales in Blender before export.")
    rotation = matrix[:3, :3] / scale
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-4):
        raise ValueError(
            "Sheared node transforms are not supported; apply transforms before export."
        )
    return matrix[:3, 3].copy(), matrix_quaternion(rotation), scale


def rotation_between(source, target):
    a, b = normalize(source), normalize(target)
    cosine = float(np.clip(np.dot(a, b), -1, 1))
    if cosine > 1 - 1e-9:
        return np.eye(3)
    if cosine < -1 + 1e-7:
        axis = normalize(np.cross(a, (1, 0, 0)) if abs(a[0]) < 0.8 else np.cross(a, (0, 1, 0)))
        return 2 * np.outer(axis, axis) - np.eye(3)
    cross = np.cross(a, b)
    skew = np.array(((0, -cross[2], cross[1]), (cross[2], 0, -cross[0]), (-cross[1], cross[0], 0)))
    return np.eye(3) + skew + skew @ skew / (1 + cosine)


def slerp(a, b, factor):
    a, b = normalize(a), normalize(b)
    dot = float(np.dot(a, b))
    if dot < 0:
        b, dot = -b, -dot
    if dot > 0.9995:
        return normalize(a + factor * (b - a))
    angle = math.acos(np.clip(dot, -1, 1))
    return (math.sin((1 - factor) * angle) * a + math.sin(factor * angle) * b) / math.sin(angle)


def transform_points(points, matrix):
    return np.asarray(points) @ matrix[:3, :3].T + matrix[:3, 3]


def rotation_only(matrix):
    return matrix[:3, :3] / np.linalg.norm(matrix[:3, :3], axis=0)
