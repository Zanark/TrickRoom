"""Immutable asset records. Local paths and source pixels never enter tracking observations."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from trickroom.assets.profile import RigProfile


@dataclass(frozen=True)
class Node:
    name: str
    parent: int
    translation: np.ndarray
    rotation: np.ndarray
    scale: np.ndarray
    mesh: int | None = None
    skin: int | None = None
    weights: np.ndarray | None = None


@dataclass(frozen=True)
class Skin:
    joints: tuple[int, ...]
    inverse_bind: np.ndarray


@dataclass(frozen=True)
class Texture:
    rgba: np.ndarray
    digest: str
    min_filter: int = 9729
    mag_filter: int = 9729
    wrap_s: int = 10497
    wrap_t: int = 10497


@dataclass(frozen=True)
class Material:
    name: str
    factor: tuple[float, float, float, float] = (1, 1, 1, 1)
    texture: int | None = None
    alpha_mode: str = "OPAQUE"
    alpha_cutoff: float = 0.5
    double_sided: bool = False
    unlit: bool = False


@dataclass(frozen=True)
class Primitive:
    node: int
    positions: np.ndarray
    normals: np.ndarray | None
    uv: np.ndarray
    colors: np.ndarray
    indices: np.ndarray
    material: int
    joints: np.ndarray | None
    weights: np.ndarray | None
    morph_positions: np.ndarray
    morph_normals: np.ndarray
    target_names: tuple[str, ...]
    default_weights: np.ndarray


@dataclass(frozen=True)
class Channel:
    node: int
    path: str
    interpolation: str
    times: np.ndarray
    values: np.ndarray


@dataclass(frozen=True)
class Clip:
    name: str
    channels: tuple[Channel, ...]
    duration: float


@dataclass
class Asset:
    name: str
    digest: str
    nodes: tuple[Node, ...]
    order: tuple[int, ...]
    rest_globals: np.ndarray
    skins: tuple[Skin, ...]
    materials: tuple[Material, ...]
    textures: tuple[Texture, ...]
    primitives: tuple[Primitive, ...]
    clips: tuple[Clip, ...]
    profile: RigProfile
    bones: dict[str, int]
    driver_for_node: tuple[str | None, ...]
    warnings: tuple[str, ...] = ()
    bounds: np.ndarray = field(default_factory=lambda: np.zeros((2, 3)))

    def report(self):
        return {
            "name": self.name,
            "sha256": self.digest,
            "profile_version": self.profile.schema_version,
            "nodes": len(self.nodes),
            "skins": len(self.skins),
            "vertices": sum(len(p.positions) for p in self.primitives),
            "triangles": sum(len(p.indices) for p in self.primitives),
            "primitives": len(self.primitives),
            "textures": len(self.textures),
            "bones": self.bones,
            "shapes": sorted({name for p in self.primitives for name in p.target_names}),
            "clips": [{"name": c.name, "duration": c.duration} for c in self.clips],
            "bounds": self.bounds.tolist(),
            "warnings": list(self.warnings),
            "ready_for_live": True,
        }
