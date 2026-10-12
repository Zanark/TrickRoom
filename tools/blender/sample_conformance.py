"""Export numerical Blender-evaluated geometry for independent skin/morph comparison."""

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix


def sample(destination: Path):
    obj = bpy.data.objects["ConformanceBody"]
    rig = bpy.data.objects["TrickRoomRig"]
    scene = bpy.context.scene
    arm_action = rig.animation_data.action
    shape_action = obj.data.shape_keys.animation_data.action
    result = {"blender": bpy.app.version_string, "coordinate_conversion": "(x,z,-y)", "samples": {}}
    for name, frame, arm, face in (
        ("bind", 1, True, True),
        ("ConformanceWave", 16, True, False),
        ("ConformanceFace", 16, False, True),
    ):
        rig.animation_data.action = arm_action if arm else None
        obj.data.shape_keys.animation_data.action = shape_action if face else None
        for bone in rig.pose.bones:
            bone.matrix_basis = Matrix.Identity(4)
        for key in obj.data.shape_keys.key_blocks:
            key.value = 0
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        points = []
        for vertex in mesh.vertices:
            p = evaluated.matrix_world @ vertex.co
            points.append((p.x, p.z, -p.y))
        evaluated.to_mesh_clear()
        result["samples"][name] = points
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Saved numerical Blender samples: {destination.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    sample(args.output)
