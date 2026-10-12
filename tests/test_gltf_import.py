import json

import numpy as np
import pytest
from glb_helpers import FIXTURE, changed_glb

from trickroom.assets.gltf import LIMITS, Accessors, load_asset
from trickroom.assets.profile import AssetError, RigProfile


def test_actual_blender_export_loads_complete_contract():
    asset = load_asset(FIXTURE)
    report = asset.report()
    assert report["ready_for_live"] and report["skins"] == 1
    assert report["vertices"] > 500 and report["triangles"] > 300
    assert len(report["bones"]) == 23 and len(report["shapes"]) == 12
    assert {c["name"] for c in report["clips"]} == {"ConformanceWave", "ConformanceFace"}
    assert report["textures"] == 1
    assert 0.1 < report["bounds"][1][1] - report["bounds"][0][1] < 3
    assert not asset.primitives[0].positions.flags.writeable


@pytest.mark.parametrize(
    "mutate,code",
    [
        (
            lambda d: d["buffers"][0].update(uri="https://example.invalid/private.bin"),
            "EXTERNAL_RESOURCE",
        ),
        (
            lambda d: d.update(extensionsRequired=["KHR_draco_mesh_compression"]),
            "REQUIRED_EXTENSION",
        ),
        (lambda d: d["bufferViews"][0].update(byteLength=2_000_000), "BUFFER_BOUNDS"),
        (lambda d: d["materials"][0].update(alphaMode="BLEND"), "ALPHA_BLEND"),
        (lambda d: d["materials"][0].update(normalTexture={"index": 0}), "MATERIAL_MAP"),
        (lambda d: d["images"][0].update(uri="file:///private.png"), "IMAGE"),
        (lambda d: d["nodes"][-1].update(scale=[-1, 1, 1]), "SCALE"),
        (lambda d: d["nodes"][-1].update(scale=[1, 2, 1]), "SCALE"),
        (lambda d: d["meshes"][0]["primitives"][0].update(mode=1), "PRIMITIVE"),
        (lambda d: d["meshes"][0]["primitives"][0]["attributes"].update(JOINTS_1=0), "INFLUENCES"),
        (lambda d: d["meshes"][0]["extras"].update(targetNames=[]), "MORPH_NAMES"),
        (
            lambda d: d["animations"][0]["samplers"][0].update(interpolation="CUBICSPLINE"),
            "ANIMATION_INTERPOLATION",
        ),
        (lambda d: d["animations"][0].update(name="bind"), "CLIP_NAME"),
        (
            lambda d: next(n for n in d["nodes"] if n["name"] == "Hips").update(name="WrongHips"),
            "RIG_BONE",
        ),
        (lambda d: d["nodes"][0].update(children=[0]), "HIERARCHY"),
    ],
)
def test_unsupported_or_malformed_assets_fail_explicitly(tmp_path, mutate, code):
    path = changed_glb(tmp_path, mutate)
    with pytest.raises(AssetError) as error:
        load_asset(path)
    assert error.value.code == code


def test_joint_accessor_normalization_is_rejected(tmp_path):
    def mutate(document):
        index = document["meshes"][0]["primitives"][0]["attributes"]["JOINTS_0"]
        document["accessors"][index]["normalized"] = True

    with pytest.raises(AssetError, match="INTEGER_NORMALIZED"):
        load_asset(changed_glb(tmp_path, mutate))


def test_header_and_format_errors_are_actionable(tmp_path):
    path = tmp_path / "bad.glb"
    path.write_bytes(b"not a model" * 10)
    with pytest.raises(AssetError, match="HEADER"):
        load_asset(path)
    with pytest.raises(AssetError, match="FORMAT"):
        load_asset(tmp_path / "character.blend")


def test_profile_can_remap_bone_and_shape_names(tmp_path):
    def mutate(document):
        next(n for n in document["nodes"] if n["name"] == "Hips")["name"] = "customPelvis"
        names = document["meshes"][0]["extras"]["targetNames"]
        names[names.index("TR_Smile")] = "customSmile"

    path = changed_glb(tmp_path, mutate)
    profile = tmp_path / "mapping.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bones": {"hips": "customPelvis"},
                "shapes": {"smile": "customSmile"},
            }
        )
    )
    asset = load_asset(path, profile)
    assert asset.nodes[asset.bones["hips"]].name == "customPelvis"
    assert asset.profile.shapes["smile"] == "customSmile"


def test_bone_gaze_requires_actual_eye_binding(tmp_path):
    profile = tmp_path / "mapping.json"
    profile.write_text(json.dumps({"schema_version": 1, "gaze_mode": "bones"}))
    with pytest.raises(AssetError, match="EYE_BINDING"):
        load_asset(FIXTURE, profile)


@pytest.mark.parametrize(
    "mapping",
    [
        {"schema_version": 9},
        {"schema_version": 1, "unexpected": True},
        {"schema_version": 1, "bones": {"hips": ""}},
        {"schema_version": 1, "bones": {"hips": "Head"}},
        {"schema_version": 1, "gaze_mode": "invent"},
    ],
)
def test_profile_validation(tmp_path, mapping):
    profile = tmp_path / "bad.json"
    profile.write_text(json.dumps(mapping))
    with pytest.raises(AssetError):
        RigProfile.load(profile)


def test_sparse_and_zero_initialized_accessors():
    values = np.array((1.0, 2.0, 3.0), "<f4").tobytes()
    document = {
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 4},
            {"buffer": 0, "byteOffset": 4, "byteLength": 12},
        ],
        "accessors": [
            {"componentType": 5126, "count": 3, "type": "VEC3"},
            {
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "sparse": {
                    "count": 1,
                    "indices": {"bufferView": 0, "componentType": 5121},
                    "values": {"bufferView": 1},
                },
            },
        ],
    }
    reader = Accessors(document, bytes((1, 0, 0, 0)) + values)
    assert np.array_equal(reader.read(0), np.zeros((3, 3)))
    result = reader.read(1)
    assert np.array_equal(result[1], (1, 2, 3))
    assert np.array_equal(result[[0, 2]], np.zeros((2, 3)))


def test_interleaved_accessors_obey_stride():
    values = np.array(((1, 2, 3, 99), (4, 5, 6, 99)), "<f4")
    reader = Accessors(
        {
            "bufferViews": [{"buffer": 0, "byteLength": values.nbytes, "byteStride": 16}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "type": "VEC3", "count": 2}],
        },
        values.tobytes(),
    )
    assert np.array_equal(reader.read(0), ((1, 2, 3), (4, 5, 6)))


def test_animation_budget_counts_all_channels_not_only_one_sampler(monkeypatch):
    asset = load_asset(FIXTURE)
    largest = max(len(channel.times) for clip in asset.clips for channel in clip.channels)
    total = sum(len(channel.times) for clip in asset.clips for channel in clip.channels)
    assert total > largest + 1
    monkeypatch.setitem(LIMITS, "animation_keys", largest + 1)
    with pytest.raises(AssetError, match="ANIMATION_BUDGET"):
        load_asset(FIXTURE)
