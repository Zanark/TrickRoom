"""Optional per-user camera defaults, encrypted locally with Windows DPAPI."""

from __future__ import annotations

import ctypes
import json
import os
import sys
import tempfile
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, repr=False)
class Credentials:
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)

    def __repr__(self):
        return "Credentials(<private>)"


def defaults_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".local" / "camera-auth.dpapi"


def _protect(data: bytes, decrypt: bool = False) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError(
            "Encrypted camera defaults require Windows DPAPI; use explicit fields instead."
        )

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, result = Blob(len(data), buffer), Blob()
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise RuntimeError(
            "Camera defaults could not be decrypted for this Windows user."
            if decrypt
            else "Camera defaults could not be encrypted."
        )
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)
        ctypes.memset(buffer, 0, len(data))


def save_defaults(credentials: Credentials, path: Path | None = None) -> None:
    path = path or defaults_path()
    if not isinstance(credentials.username, str) or not isinstance(credentials.password, str):
        raise ValueError("Camera credentials must be strings.")
    data = json.dumps({"username": credentials.username, "password": credentials.password}).encode()
    if len(data) > 8192:
        raise ValueError("Camera credentials exceed the supported local configuration size.")
    encrypted = _protect(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, suffix=".encrypted", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(encrypted)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_defaults(path: Path | None = None, *, environment: bool = True) -> Credentials:
    path = path or defaults_path()
    if environment and all(
        key in os.environ for key in ("TRICKROOM_CAMERA_USER", "TRICKROOM_CAMERA_PASSWORD")
    ):
        return Credentials(
            os.environ["TRICKROOM_CAMERA_USER"], os.environ["TRICKROOM_CAMERA_PASSWORD"]
        )
    credentials = Credentials()
    if path.exists():
        if not path.is_file() or path.stat().st_size > 16384:
            raise RuntimeError(
                "Encrypted camera-default file is invalid; reconfigure local defaults."
            )
        try:
            data = json.loads(_protect(path.read_bytes(), decrypt=True).decode("utf-8"))
            if (
                not isinstance(data, dict)
                or set(data) != {"username", "password"}
                or any(not isinstance(value, str) for value in data.values())
            ):
                raise ValueError("Invalid credential record")
            credentials = Credentials(data["username"], data["password"])
        except (ValueError, OSError) as error:
            raise RuntimeError(
                "Encrypted camera defaults are invalid; reconfigure them locally."
            ) from error
    if environment:
        return Credentials(
            os.environ.get("TRICKROOM_CAMERA_USER", credentials.username),
            os.environ.get("TRICKROOM_CAMERA_PASSWORD", credentials.password),
        )
    return credentials
