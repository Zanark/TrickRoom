import copy
import json
import struct
from pathlib import Path

from trickroom.assets.gltf import read_glb

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "blender" / "TrickRoom-Conformance.glb"


def changed_glb(tmp_path, mutate):
    document, binary, _ = read_glb(FIXTURE)
    document = copy.deepcopy(document)
    mutate(document)
    encoded = json.dumps(document, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    binary += b"\0" * (-len(binary) % 4)
    result = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(encoded) + 8 + len(binary))
    result += struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    result += struct.pack("<II", len(binary), 0x004E4942) + binary
    path = tmp_path / "changed.glb"
    path.write_bytes(result)
    return path
