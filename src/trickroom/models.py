"""Checksum-pinned official models; downloads are explicit and atomic."""

from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Model:
    filename: str
    url: str
    sha256: str


MODELS = (
    Model(
        "pose_landmarker_lite.task",
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
        "pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
        "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
    ),
    Model(
        "face_landmarker.task",
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task",
        "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
    ),
)


def default_model_directory() -> Path:
    return Path(os.environ.get("TRICKROOM_MODELS", Path(__file__).resolve().parents[2] / "models"))


def verify(path: Path, model: Model) -> None:
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {model.filename}. Run: python -m trickroom --download-models"
        )
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != model.sha256:
        raise ValueError(f"Checksum mismatch for {model.filename}; remove it and download again.")


def ensure_models(directory: Path, *, download: bool = False) -> tuple[Path, Path]:
    paths: list[Path] = []
    for model in MODELS:
        path = directory / model.filename
        if not path.exists() and download:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=directory, suffix=".download", delete=False
            ) as out:
                temporary = Path(out.name)
                try:
                    with urllib.request.urlopen(model.url, timeout=30) as response:
                        total = 0
                        while chunk := response.read(65536):
                            total += len(chunk)
                            if total > 40 * 1024 * 1024:
                                raise ValueError("Model download exceeded the expected size bound.")
                            out.write(chunk)
                    out.flush()
                except (OSError, urllib.error.URLError, ValueError):
                    out.close()
                    temporary.unlink(missing_ok=True)
                    raise
            try:
                verify(temporary, model)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        verify(path, model)
        paths.append(path)
    return paths[0], paths[1]
