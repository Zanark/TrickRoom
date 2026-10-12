"""Preflight and export the currently loaded authoring scene; never save over the .blend."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preflight import validate  # noqa: E402

from trickroom.assets.profile import RigProfile  # noqa: E402


def export(output: Path, profile_path: Path | None = None, *, overwrite=False) -> dict:
    if output.suffix.lower() != ".glb":
        raise ValueError("Choose an output filename ending in .glb.")
    if output.exists() and not overwrite:
        raise FileExistsError(
            "Output exists; choose a new revision name or explicitly --overwrite."
        )
    profile = RigProfile.load(profile_path)
    previous_frame = bpy.context.scene.frame_current
    selection = list(bpy.context.selected_objects)
    previous_active = bpy.context.view_layer.objects.active
    try:
        bpy.context.scene.frame_set(bpy.context.scene.frame_start)
        report = validate(profile)
        if report["errors"]:
            print(json.dumps(report, indent=2))
            raise RuntimeError("Source preflight failed. No export was written.")
        output.parent.mkdir(parents=True, exist_ok=True)
        for obj in bpy.context.scene.objects:
            obj.select_set(obj.type in ("MESH", "ARMATURE"))
        result = bpy.ops.export_scene.gltf(
            filepath=str(output),
            export_format="GLB",
            use_selection=True,
            export_yup=True,
            export_animations=True,
            export_force_sampling=True,
            export_animation_mode="ACTIONS",
            export_anim_slide_to_zero=True,
            export_skins=True,
            export_influence_nb=4,
            export_all_influences=False,
            export_morph=True,
            export_morph_normal=True,
            export_extras=True,
            export_def_bones=False,
            export_leaf_bone=False,
            export_apply=False,
            export_draco_mesh_compression_enable=False,
        )
        if result != {"FINISHED"} or not output.is_file():
            raise RuntimeError("Blender exporter did not produce a completed GLB.")
        mapping = output.with_suffix(".trickroom.json")
        mapping.write_text(json.dumps(profile.to_dict(), indent=2) + "\n", encoding="utf-8")
        report.update(
            {
                "glb": output.name,
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "profile": mapping.name,
                "profile_sha256": hashlib.sha256(mapping.read_bytes()).hexdigest(),
                "exported": True,
                "source_blend_modified_on_disk": False,
            }
        )
        output.with_suffix(".export.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        return report
    finally:
        bpy.context.scene.frame_set(previous_frame)
        for obj in bpy.context.scene.objects:
            obj.select_set(obj in selection)
        bpy.context.view_layer.objects.active = previous_active


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    print(
        json.dumps(export(args.output.resolve(), args.profile, overwrite=args.overwrite), indent=2)
    )
