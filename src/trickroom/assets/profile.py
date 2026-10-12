"""The versioned authoring contract consumed by the importer and Blender tooling."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_BONES = {
    "hips": "Hips",
    "spine": "Spine",
    "chest": "Chest",
    "neck": "Neck",
    "head": "Head",
    "upper_arm_left": "UpperArm.L",
    "lower_arm_left": "LowerArm.L",
    "hand_left": "Hand.L",
    "upper_arm_right": "UpperArm.R",
    "lower_arm_right": "LowerArm.R",
    "hand_right": "Hand.R",
    "upper_leg_left": "UpperLeg.L",
    "lower_leg_left": "LowerLeg.L",
    "foot_left": "Foot.L",
    "upper_leg_right": "UpperLeg.R",
    "lower_leg_right": "LowerLeg.R",
    "foot_right": "Foot.R",
}
OPTIONAL_BONES = {
    "shoulder_left": "Shoulder.L",
    "shoulder_right": "Shoulder.R",
    "toes_left": "Toes.L",
    "toes_right": "Toes.R",
    "eye_left": "Eye.L",
    "eye_right": "Eye.R",
}
SHAPES = {
    "blink_left": "TR_Blink_L",
    "blink_right": "TR_Blink_R",
    "jaw_open": "TR_Jaw_Open",
    "smile": "TR_Smile",
    "brow_up_left": "TR_Brow_Up_L",
    "brow_up_right": "TR_Brow_Up_R",
    "brow_down_left": "TR_Brow_Down_L",
    "brow_down_right": "TR_Brow_Down_R",
    "look_left": "TR_Look_Left",
    "look_right": "TR_Look_Right",
    "look_up": "TR_Look_Up",
    "look_down": "TR_Look_Down",
}
PARENTS = {
    "spine": "hips",
    "chest": "spine",
    "neck": "chest",
    "head": "neck",
    "upper_arm_left": "chest",
    "lower_arm_left": "upper_arm_left",
    "hand_left": "lower_arm_left",
    "upper_arm_right": "chest",
    "lower_arm_right": "upper_arm_right",
    "hand_right": "lower_arm_right",
    "upper_leg_left": "hips",
    "lower_leg_left": "upper_leg_left",
    "foot_left": "lower_leg_left",
    "upper_leg_right": "hips",
    "lower_leg_right": "upper_leg_right",
    "foot_right": "lower_leg_right",
    "shoulder_left": "chest",
    "shoulder_right": "chest",
    "toes_left": "foot_left",
    "toes_right": "foot_right",
    "eye_left": "head",
    "eye_right": "head",
}
LIMITS = {
    "file_bytes": 64 * 1024 * 1024,
    "json_bytes": 4 * 1024 * 1024,
    "nodes": 256,
    "joints_per_skin": 128,
    "primitives": 64,
    "vertices": 80000,
    "triangles": 100000,
    "morph_targets": 32,
    "textures": 8,
    "image_dimension": 4096,
    "decoded_image_pixels": 8 * 1024 * 1024,
    "decoded_array_bytes": 128 * 1024 * 1024,
    "clips": 16,
    "animation_keys": 100000,
}


class AssetError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class RigProfile:
    schema_version: int = 1
    bones: dict[str, str] = field(default_factory=lambda: {**REQUIRED_BONES, **OPTIONAL_BONES})
    shapes: dict[str, str] = field(default_factory=lambda: dict(SHAPES))
    gaze_mode: str = "morph"

    @classmethod
    def load(cls, path: Path | None) -> RigProfile:
        if path is None:
            return cls()
        if not path.is_file() or path.stat().st_size > 64 * 1024:
            raise AssetError("PROFILE_FILE", "Mapping profile is missing or exceeds 64 KiB.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise AssetError("PROFILE_JSON", "Mapping profile is not valid UTF-8 JSON.") from error
        if not isinstance(data, dict) or set(data) - {
            "schema_version",
            "bones",
            "shapes",
            "gaze_mode",
        }:
            raise AssetError(
                "PROFILE_KEYS", "Use only schema_version, bones, shapes and gaze_mode."
            )
        if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise AssetError("PROFILE_VERSION", "Only profile schema_version 1 is supported.")
        base = cls()
        mappings = {}
        for key, defaults in (("bones", base.bones), ("shapes", base.shapes)):
            overrides = data.get(key, {})
            if not isinstance(overrides, dict) or set(overrides) - set(defaults):
                raise AssetError(
                    "PROFILE_MAPPING", f"Unknown logical {key} keys in mapping profile."
                )
            if any(
                not isinstance(v, str) or not 1 <= len(v) <= 128 or any(ord(c) < 32 for c in v)
                for v in overrides.values()
            ):
                raise AssetError(
                    "PROFILE_NAME", "Mapped names must be printable strings of 1-128 chars."
                )
            merged = {**defaults, **overrides}
            if len(set(merged.values())) != len(merged):
                raise AssetError(
                    "PROFILE_DUPLICATE", f"Two logical {key} cannot map to the same name."
                )
            mappings[key] = merged
        gaze = data.get("gaze_mode", "morph")
        if gaze not in ("morph", "bones"):
            raise AssetError("PROFILE_GAZE", "gaze_mode must be morph or bones.")
        return cls(1, mappings["bones"], mappings["shapes"], gaze)

    def to_dict(self):
        return {
            "schema_version": self.schema_version,
            "bones": self.bones,
            "shapes": self.shapes,
            "gaze_mode": self.gaze_mode,
        }
