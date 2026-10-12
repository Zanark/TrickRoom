import json
import os

import pytest

from trickroom.credentials import Credentials, load_defaults, save_defaults


@pytest.mark.skipif(os.name != "nt", reason="Windows user-bound DPAPI")
def test_local_defaults_are_encrypted_and_roundtrip(tmp_path):
    path = tmp_path / "camera-auth.dpapi"
    credentials = Credentials("unit-fixture-user", "unit-fixture-password")
    save_defaults(credentials, path)
    assert load_defaults(path, environment=False) == credentials
    ciphertext = path.read_bytes()
    assert b"unit-fixture-user" not in ciphertext
    assert b"unit-fixture-password" not in ciphertext
    assert b'"username"' not in ciphertext
    assert "unit-fixture" not in repr(credentials)
    with pytest.raises((UnicodeDecodeError, json.JSONDecodeError)):
        json.loads(ciphertext)


def test_missing_optional_defaults_leave_fields_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("TRICKROOM_CAMERA_USER", raising=False)
    monkeypatch.delenv("TRICKROOM_CAMERA_PASSWORD", raising=False)
    assert load_defaults(tmp_path / "absent") == Credentials()


def test_environment_overrides_do_not_need_to_decrypt_local_file(tmp_path, monkeypatch):
    path = tmp_path / "broken"
    path.write_bytes(b"not a credential file")
    monkeypatch.setenv("TRICKROOM_CAMERA_USER", "explicit-test")
    monkeypatch.setenv("TRICKROOM_CAMERA_PASSWORD", "explicit-test-secret")
    assert load_defaults(path) == Credentials("explicit-test", "explicit-test-secret")


@pytest.mark.skipif(os.name != "nt", reason="Windows user-bound DPAPI")
def test_bad_ciphertext_is_an_explicit_nonsecret_error(tmp_path):
    path = tmp_path / "bad"
    path.write_bytes(b"unit-fixture-sensitive-garbage")
    with pytest.raises(RuntimeError) as error:
        load_defaults(path, environment=False)
    assert "unit-fixture" not in str(error.value)
