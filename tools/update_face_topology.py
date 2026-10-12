"""Generate licensed static connectivity without importing the native MediaPipe runtime."""

import ast
import hashlib
import json
from importlib.metadata import distribution
from pathlib import Path


def generate():
    root = Path(__file__).resolve().parents[1]
    package = distribution("mediapipe")
    source = Path(package.locate_file("mediapipe/tasks/python/vision/face_landmarker.py"))
    text = source.read_text(encoding="utf-8")
    node = next(
        n
        for n in ast.parse(text).body
        if isinstance(n, ast.ClassDef) and n.name == "FaceLandmarksConnections"
    )
    tables = {}
    for member in node.body:
        if not isinstance(member, ast.AnnAssign) or not isinstance(member.value, ast.List):
            continue
        pairs = []
        for call in member.value.elts:
            assert isinstance(call, ast.Call)
            values = [ast.literal_eval(arg) for arg in call.args]
            if not values:
                values = [
                    ast.literal_eval(next(k.value for k in call.keywords if k.arg == name))
                    for name in ("start", "end")
                ]
            assert len(values) == 2 and all(type(v) is int and 0 <= v < 478 for v in values)
            pairs.append(tuple(sorted(values)))
        tables[member.target.id] = pairs
    contours = (
        "LIPS",
        "LEFT_EYE",
        "RIGHT_EYE",
        "LEFT_EYEBROW",
        "RIGHT_EYEBROW",
        "FACE_OVAL",
        "NOSE",
    )
    data = {
        "source": "MediaPipe Authors: tasks/python/vision/face_landmarker.py",
        "source_version": package.version,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "license": "Apache-2.0; see face_topology.LICENSE",
        "mesh": sorted(set(tables["FACE_LANDMARKS_TESSELATION"])),
        "contours": sorted(
            {edge for name in contours for edge in tables[f"FACE_LANDMARKS_{name}"]}
        ),
        "irises": sorted(
            set(tables["FACE_LANDMARKS_LEFT_IRIS"] + tables["FACE_LANDMARKS_RIGHT_IRIS"])
        ),
    }
    destination = root / "src" / "trickroom"
    (destination / "face_topology.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    license_path = next(p for p in package.files if str(p).endswith("licenses/LICENSE"))
    (destination / "face_topology.LICENSE").write_bytes(
        Path(package.locate_file(license_path)).read_bytes()
    )
    print({name: len(data[name]) for name in ("mesh", "contours", "irises")})


if __name__ == "__main__":
    generate()
