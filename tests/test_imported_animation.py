from dataclasses import replace

import numpy as np
import pytest
from glb_helpers import FIXTURE

from trickroom.assets.animation import deform, global_transforms, sample_clip
from trickroom.assets.gltf import load_asset
from trickroom.assets.math3d import quaternion_matrix, rotation_between, transform_points
from trickroom.assets.retarget import AvatarInstance, expression_weights, retarget
from trickroom.assets.types import Channel, Clip
from trickroom.demo import demo_observation
from trickroom.render import Renderer, StageOptions


@pytest.fixture
def asset():
    return load_asset(FIXTURE)


def test_blender_inverse_bind_matrices_recover_exported_rest_geometry(asset):
    deformed = deform(asset, asset.rest_globals, {})
    for posed in deformed:
        expected = transform_points(posed.source.positions, asset.rest_globals[posed.source.node])
        assert posed.positions == pytest.approx(expected, abs=2e-6)


def test_live_retarget_preserves_every_parent_child_length(asset):
    state = demo_observation(1.2, 10)
    globals_, _, active = retarget(asset, state)
    assert len(active) >= 17
    for index, node in enumerate(asset.nodes):
        if node.parent < 0:
            continue
        before = np.linalg.norm(
            asset.rest_globals[index, :3, 3] - asset.rest_globals[node.parent, :3, 3]
        )
        after = np.linalg.norm(globals_[index, :3, 3] - globals_[node.parent, :3, 3])
        assert after == pytest.approx(before, abs=1e-6)


def test_real_exported_clip_deforms_weighted_vertices(asset):
    clip = next(c for c in asset.clips if c.name == "ConformanceWave")
    overrides, weights = sample_clip(clip, 0.52, loop=False)
    posed = deform(asset, global_transforms(asset, overrides), weights)
    rest = deform(asset, asset.rest_globals, {})
    differences = [
        np.max(np.linalg.norm(a.positions - b.positions, axis=1))
        for a, b in zip(posed, rest, strict=True)
    ]
    assert max(differences) > 0.08


def test_facial_morphs_are_independent_and_reset_on_loss(asset):
    state = demo_observation(0, 10)
    state = replace(
        state,
        face=replace(
            state.face,
            expression=replace(
                state.face.expression,
                blink_left=1,
                blink_right=0,
                jaw_open=0.8,
                smile=0,
            ),
        ),
    )
    weights = expression_weights(asset, state)
    primitive = asset.primitives[-1]
    names = {name: i for i, name in enumerate(primitive.target_names)}
    assert weights[primitive.node][names["TR_Blink_L"]] == 1
    assert weights[primitive.node][names["TR_Blink_R"]] == 0
    assert weights[primitive.node][names["TR_Jaw_Open"]] == 0.8
    lost = expression_weights(asset, replace(state, face=None))
    assert np.array_equal(lost[primitive.node], np.zeros(len(names)))


def test_cropped_lower_leg_triangles_are_hidden_not_animated_from_guesses(asset):
    instance = AvatarInstance(asset)
    full = instance.evaluate(demo_observation(0, 10), 10)
    cropped = instance.evaluate(demo_observation(0, 11, cropped=True), 11)
    assert "lower_leg_left" in full.active and "lower_leg_left" not in cropped.active
    assert sum(mask.sum() for mask in cropped.visible) < sum(mask.sum() for mask in full.visible)


def test_clip_preview_is_labelled_and_does_not_need_camera(asset):
    renderer = Renderer()
    instance = AvatarInstance(asset)
    instance.set_mode("bind", 10)
    renderer.set_model(instance)
    preview = renderer.render(None, now=10)
    assert preview.shape == (720, 960, 3)
    assert renderer._imported_frame is not None
    instance.set_mode("ConformanceFace", 10)
    talking = renderer.render(None, now=10.5)
    assert np.count_nonzero(preview != talking) > 100


def test_model_loading_failure_keeps_previous_model(tmp_path):
    renderer = Renderer()
    renderer.load_model(FIXTURE)
    previous = renderer.imported
    invalid = tmp_path / "bad.glb"
    invalid.write_bytes(b"bad")
    with pytest.raises(ValueError):
        renderer.load_model(invalid)
    assert renderer.imported is previous
    renderer.use_builtin()
    assert renderer.imported is None


def test_imported_rendering_respects_exact_presentation_mirror(asset):
    renderer = Renderer()
    renderer.set_model(AvatarInstance(asset))
    state = demo_observation(0.5, 10)
    options = StageOptions(mirror=False, hud=False, head_detail=False)
    normal = renderer.render(state, (640, 480), now=10, options=options)
    mirrored = renderer.render(state, (640, 480), now=10, options=replace(options, mirror=True))
    assert np.array_equal(normal[:, ::-1], mirrored)


def test_step_and_linear_clip_sampling_and_quaternion_shortest_path():
    times = np.array((0.0, 1.0))
    linear = Channel(0, "translation", "LINEAR", times, np.array(((0, 0, 0), (2, 0, 0))))
    step = Channel(1, "translation", "STEP", times, np.array(((0, 0, 0), (2, 0, 0))))
    quat = Channel(2, "rotation", "LINEAR", times, np.array(((0, 0, 0, 1), (0, 0, 0, -1))))
    values, _ = sample_clip(Clip("test", (linear, step, quat), 1), 0.5)
    assert values[0]["translation"] == pytest.approx((1, 0, 0))
    assert values[1]["translation"] == pytest.approx((0, 0, 0))
    assert quaternion_matrix(values[2]["rotation"]) == pytest.approx(np.eye(3))


def test_180_degree_bone_aim_is_finite():
    assert rotation_between((1, 0, 0), (-1, 0, 0)) @ (1, 0, 0) == pytest.approx((-1, 0, 0))
