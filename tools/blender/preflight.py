"""Blender-side preparation checks. The exported GLB must also pass runtime validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from trickroom.assets.profile import LIMITS, REQUIRED_BONES, RigProfile  # noqa: E402


def validate(profile: RigProfile) -> dict:
    errors, warnings = [], []
    rigs = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(rigs) != 1:
        errors.append("Keep exactly one export armature in the character scene.")
    if not meshes:
        errors.append("No character meshes found.")
    rig = rigs[0] if len(rigs) == 1 else None
    if rig:
        for logical in REQUIRED_BONES:
            if profile.bones[logical] not in rig.data.bones:
                errors.append(f"Missing bone {profile.bones[logical]} for {logical}.")
    present_shapes = set()
    source_vertices = triangles = 0
    for obj in [*rigs, *meshes]:
        if any(abs(value - 1) > 1e-5 for value in obj.scale):
            errors.append(f"{obj.name}: apply object scale in the export copy.")
        if obj.type != "MESH":
            continue
        source_vertices += len(obj.data.vertices)
        obj.data.calc_loop_triangles()
        triangles += len(obj.data.loop_triangles)
        modifiers = [modifier for modifier in obj.modifiers if modifier.show_viewport]
        armatures = [modifier for modifier in modifiers if modifier.type == "ARMATURE"]
        if any(modifier.type != "ARMATURE" for modifier in modifiers):
            errors.append(
                f"{obj.name}: apply non-armature modifiers before final shape keys/export."
            )
        if not armatures and not (obj.parent == rig and obj.parent_type == "BONE"):
            errors.append(f"{obj.name}: skin to the armature or bone-parent the rigid attachment.")
        if armatures and (len(armatures) != 1 or armatures[0].object != rig):
            errors.append(f"{obj.name}: use one modifier targeting the export armature.")
        if armatures and rig:
            names = {
                group.index: group.name
                for group in obj.vertex_groups
                if group.name in rig.data.bones and rig.data.bones[group.name].use_deform
            }
            for vertex in obj.data.vertices:
                weights = [
                    group.weight
                    for group in vertex.groups
                    if group.group in names and group.weight > 1e-6
                ]
                if not weights or len(weights) > 4 or abs(sum(weights) - 1) > 0.015:
                    errors.append(
                        f"{obj.name}: vertex {vertex.index} needs 1-4 normalized deform weights."
                    )
                    break
        if obj.data.shape_keys:
            blocks = obj.data.shape_keys.key_blocks
            if len(blocks) - 1 > LIMITS["morph_targets"]:
                errors.append(f"{obj.name}: more than32shape keys excluding Basis.")
            basis = blocks[0]
            for block in list(blocks)[1:]:
                if block.relative_key != basis:
                    errors.append(f"{obj.name}/{block.name}: use Basis as the relative key.")
                if any(
                    (point.co - original.co).length > 1e-7
                    for point, original in zip(block.data, basis.data, strict=True)
                ):
                    present_shapes.add(block.name)
                if abs(block.value) > 1e-5:
                    warnings.append(
                        f"{obj.name}/{block.name}: nonzero current value; "
                        "use a neutral export frame."
                    )
        for material in obj.data.materials:
            if material is None:
                errors.append(f"{obj.name}: remove empty material slots.")
                continue
            if not material.use_nodes:
                errors.append(f"{material.name}: use a Principled BSDF or supported unlit setup.")
                continue
            image_nodes = [n for n in material.node_tree.nodes if n.type == "TEX_IMAGE"]
            if image_nodes and not obj.data.uv_layers:
                errors.append(f"{obj.name}: textured materials require an active UV map.")
            for node in image_nodes:
                if node.image is None:
                    errors.append(f"{material.name}: an Image Texture node has no image.")
                elif max(node.image.size) > LIMITS["image_dimension"]:
                    errors.append(f"{material.name}: image exceeds4096pixels per side.")
            for node in material.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    for field in ("Normal", "Roughness", "Metallic"):
                        if node.inputs[field].is_linked:
                            errors.append(f"{material.name}: bake {field} maps into base color.")
                    if node.inputs["Metallic"].default_value > 0.001:
                        warnings.append(f"{material.name}: metallic reflections are not rendered.")
    for logical, target in profile.shapes.items():
        if profile.gaze_mode == "bones" and logical.startswith("look_"):
            continue
        if target not in present_shapes:
            errors.append(f"Missing nonzero facial shape {target} ({logical}).")
    if source_vertices > LIMITS["vertices"] or triangles > LIMITS["triangles"]:
        errors.append(
            "Source geometry exceeds runtime budget; exported seam splits may add more vertices."
        )
    if rig and any(bone.constraints for bone in rig.pose.bones):
        warnings.append(
            "Constraints are not evaluated by TrickRoom; bake clips and export a clean deform rig."
        )
    return {
        "blender_version": bpy.app.version_string,
        "source_meshes": len(meshes),
        "source_vertices": source_vertices,
        "source_triangles": triangles,
        "profile_version": 1,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "source_preflight_passed": not errors,
        "runtime_validation_still_required": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    result = validate(RigProfile.load(args.profile))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if result["errors"]:
        raise RuntimeError("Blender source preflight failed; correct the reported issues.")
