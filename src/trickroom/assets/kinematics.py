"""Bounded two-bone posing; targets are estimates, never measured contacts."""

import math

import numpy as np

from trickroom.assets.math3d import normalize


def aim_rotation(rest_direction, target_direction, rest_normal, target_normal):
    def basis(direction, normal):
        along = normalize(direction)
        side = np.asarray(normal) - along * np.dot(normal, along)
        if np.linalg.norm(side) < 1e-7:
            axis = np.eye(3)[np.argmin(np.abs(along))]
            side = axis - along * np.dot(axis, along)
        side = normalize(side)
        return np.column_stack((along, side, np.cross(along, side)))

    return basis(target_direction, target_normal) @ basis(rest_direction, rest_normal).T


def solve_limb(start, middle, end, upper_length, lower_length, previous_normal=None):
    upper, lower, target = middle - start, end - middle, end - start
    measured = np.linalg.norm(upper) + np.linalg.norm(lower)
    distance = float(np.linalg.norm(target))
    if min(upper_length, lower_length, measured, distance) <= 1e-7:
        return None
    forward = target / distance
    normal = np.cross(forward, upper)
    # A nearly straight limb cannot supply a stable bend plane.
    if np.linalg.norm(normal) < np.linalg.norm(upper) * 0.04:
        normal = np.asarray(previous_normal if previous_normal is not None else (0, 0, 1))
    normal = normal - forward * np.dot(normal, forward)
    if np.linalg.norm(normal) < 1e-7:
        normal = np.cross(forward, np.eye(3)[np.argmin(np.abs(forward))])
    normal = normalize(normal)
    bend = normalize(np.cross(normal, forward))
    reach = distance * (upper_length + lower_length) / measured
    minimum = math.sqrt(
        upper_length**2
        + lower_length**2
        + 2 * upper_length * lower_length * math.cos(math.radians(170))
    )
    reach = float(np.clip(reach, max(1e-6, minimum), upper_length + lower_length))
    along = (upper_length**2 + reach**2 - lower_length**2) / (2 * reach)
    across = math.sqrt(max(0, upper_length**2 - along**2))
    elbow = forward * along + bend * across
    return normalize(elbow), normalize(forward * reach - elbow), normal
