"""A personal model can be the default without its path entering the repository."""

from __future__ import annotations

import pytest

from trickroom.cli import apply_default_avatar, default_avatar, parser


def args_for(argv):
    return parser().parse_args(argv)


def test_unset_means_the_built_in_character(monkeypatch):
    monkeypatch.delenv("TRICKROOM_AVATAR", raising=False)
    assert default_avatar() is None


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_is_treated_as_unset(monkeypatch, value):
    monkeypatch.setenv("TRICKROOM_AVATAR", value)
    assert default_avatar() is None


def test_a_configured_model_is_used(monkeypatch, tmp_path):
    model = tmp_path / "Character.glb"
    model.write_bytes(b"glTF")
    monkeypatch.setenv("TRICKROOM_AVATAR", str(model))
    args = args_for(["--demo"])
    apply_default_avatar(args)
    assert args.avatar == model


def test_the_sidecar_profile_is_picked_up_when_present(monkeypatch, tmp_path):
    model = tmp_path / "Character.glb"
    model.write_bytes(b"glTF")
    sidecar = tmp_path / "Character.trickroom.json"
    sidecar.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TRICKROOM_AVATAR", str(model))
    args = args_for(["--demo"])
    apply_default_avatar(args)
    assert args.avatar_profile == sidecar


def test_a_missing_sidecar_is_not_invented(monkeypatch, tmp_path):
    model = tmp_path / "Character.glb"
    model.write_bytes(b"glTF")
    monkeypatch.setenv("TRICKROOM_AVATAR", str(model))
    args = args_for(["--demo"])
    apply_default_avatar(args)
    assert args.avatar_profile is None


def test_an_explicit_avatar_always_wins(monkeypatch, tmp_path):
    default = tmp_path / "Default.glb"
    default.write_bytes(b"glTF")
    chosen = tmp_path / "Chosen.glb"
    chosen.write_bytes(b"glTF")
    monkeypatch.setenv("TRICKROOM_AVATAR", str(default))
    args = args_for(["--demo", "--avatar", str(chosen)])
    apply_default_avatar(args)
    assert args.avatar == chosen


def test_an_explicit_profile_is_not_overwritten(monkeypatch, tmp_path):
    model = tmp_path / "Character.glb"
    model.write_bytes(b"glTF")
    (tmp_path / "Character.trickroom.json").write_text("{}", encoding="utf-8")
    chosen = tmp_path / "Mine.json"
    chosen.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TRICKROOM_AVATAR", str(model))
    args = args_for(["--demo", "--avatar-profile", str(chosen)])
    apply_default_avatar(args)
    assert args.avatar_profile == chosen


def test_a_stale_path_is_reported_rather_than_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("TRICKROOM_AVATAR", str(tmp_path / "gone.glb"))
    with pytest.raises(ValueError, match="TRICKROOM_AVATAR"):
        default_avatar()


def test_a_directory_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("TRICKROOM_AVATAR", str(tmp_path))
    with pytest.raises(ValueError, match="TRICKROOM_AVATAR"):
        default_avatar()


def test_the_error_names_the_variable_not_a_guess(monkeypatch, tmp_path):
    missing = tmp_path / "nope.glb"
    monkeypatch.setenv("TRICKROOM_AVATAR", str(missing))
    with pytest.raises(ValueError) as error:
        default_avatar()
    assert "TRICKROOM_AVATAR" in str(error.value)
    assert str(missing) in str(error.value)
