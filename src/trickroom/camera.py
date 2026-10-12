"""Bounded camera ingestion; raw pixels may also reach an explicitly enabled private debug view."""

from __future__ import annotations

import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, repr=False)
class Source:
    kind: str
    location: str | int = field(repr=False)
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)

    def __repr__(self) -> str:
        return f"Source(kind={self.kind!r}, location=<private>)"

    @classmethod
    def parse(cls, text: str, username: str = "", password: str = "") -> Source:
        text = text.strip()
        if not text:
            raise ValueError("Enter the IP Webcam video URL or choose Demo. No camera was opened.")
        if any(ord(character) < 32 or ord(character) == 127 for character in text):
            raise ValueError("Camera sources cannot contain control characters.")
        if re.fullmatch(r"\d{1,3}", text):
            return cls("device", int(text))
        if "://" in text:
            try:
                parts = urllib.parse.urlsplit(text)
                if parts.scheme not in ("http", "https") or not parts.hostname or parts.fragment:
                    raise ValueError
                _ = parts.port
                host = parts.hostname.encode("idna").decode("ascii")
                if ":" in host:
                    host = f"[{host}]"
                if parts.port is not None:
                    host += f":{parts.port}"
                username = username or urllib.parse.unquote(parts.username or "")
                password = password or urllib.parse.unquote(parts.password or "")
                path = "/video" if parts.path in ("", "/") else parts.path
                url = urllib.parse.urlunsplit((parts.scheme, host, path, parts.query, ""))
                return cls("mjpeg", url, username, password)
            except (ValueError, UnicodeError) as error:
                raise ValueError(
                    "Use an HTTP/HTTPS IP Webcam /video URL, device number or existing video file."
                ) from error
        path = Path(text).expanduser()
        if path.is_file():
            return cls("file", str(path.resolve()))
        raise ValueError("Source is not an HTTP/HTTPS URL, device number or existing video file.")


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    sequence: int
    captured_at: float
    image: NDArray[np.uint8] = field(repr=False)
    media_time: float | None = None
    generation: int = 0


@dataclass(frozen=True, slots=True)
class CaptureStatus:
    state: str = "STOPPED"
    frames: int = 0
    fps: float = 0.0
    reconnects: int = 0
    message: str = ""
    size: tuple[int, int] = (0, 0)
    position_seconds: float = 0.0
    duration_seconds: float = 0.0
    paused: bool = False
    generation: int = 0


class ReplayError(RuntimeError):
    """Source-private recorded-video transport failure."""


class JPEGStream:
    def __init__(self, max_bytes: int = 8 * 1024 * 1024) -> None:
        self.buffer = bytearray()
        self.max_bytes = max_bytes

    def feed(self, chunk: bytes) -> bytes | None:
        if len(self.buffer) + len(chunk) > self.max_bytes:
            self.buffer.clear()
            raise ValueError("MJPEG frame exceeded the 8 MiB safety limit.")
        self.buffer.extend(chunk)
        latest = None
        while True:
            start = self.buffer.find(b"\xff\xd8")
            if start < 0:
                self.buffer[:] = self.buffer[-1:]
                break
            if start:
                del self.buffer[:start]
            end = self.buffer.find(b"\xff\xd9", 2)
            if end < 0:
                break
            latest = bytes(self.buffer[: end + 2])
            del self.buffer[: end + 2]
        return latest


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if (old.scheme, old.hostname, old.port) != (new.scheme, new.hostname, new.port):
            raise ValueError("Camera redirects to another origin are not allowed.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def camera_error(error: BaseException) -> str:
    if isinstance(error, urllib.error.HTTPError):
        if error.code in (401, 403):
            return "Camera authentication failed. Check the app username/password."
        if error.code == 404:
            return "Camera endpoint not found. Use the app's /video endpoint."
        return f"Camera returned HTTP {error.code}."
    if isinstance(error, (TimeoutError, urllib.error.URLError, ConnectionError)):
        return "Camera unavailable or timed out. Check the app, tethering/Wi-Fi and address."
    return "Camera input failed. Check the source, JPEG stream and image size."


def rotate_frame(image: NDArray[np.uint8], rotation: str) -> NDArray[np.uint8]:
    codes = {
        "left": cv2.ROTATE_90_COUNTERCLOCKWISE,
        "right": cv2.ROTATE_90_CLOCKWISE,
        "180": cv2.ROTATE_180,
    }
    if rotation == "none":
        return image
    if rotation not in codes:
        raise ValueError("Rotation must be none, left, right or 180.")
    return cv2.rotate(image, codes[rotation])


class Camera:
    def __init__(
        self,
        source: Source,
        rotation: str = "none",
        *,
        start_position: float = 0.0,
        paused: bool = False,
    ) -> None:
        if rotation not in ("none", "left", "right", "180"):
            raise ValueError("Invalid camera rotation.")
        self.source = source
        self.rotation = rotation
        self._stop = threading.Event()
        self._changed = threading.Condition()
        self._frame: CapturedFrame | None = None
        self._status = CaptureStatus()
        self._thread: threading.Thread | None = None
        self._sequence = 0
        self._last_capture = 0.0
        self._fps = 0.0
        self._reconnects = 0
        if not math.isfinite(start_position) or start_position < 0 or type(paused) is not bool:
            raise ValueError("Replay start position must be finite and nonnegative.")
        if source.kind != "file" and (start_position or paused):
            raise ValueError("Playback controls require a local recording.")
        self._paused = paused
        self._generation = 0
        self._pending_seek: tuple[int, float] | None = (
            (0, start_position) if start_position else None
        )

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Create a new camera session to restart capture.")
        self._thread = threading.Thread(target=self._run, name="trickroom-capture", daemon=True)
        self._thread.start()

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def status(self) -> CaptureStatus:
        with self._changed:
            return self._status

    def next_frame(self, after: int, timeout: float = 0.1) -> CapturedFrame | None:
        with self._changed:
            self._changed.wait_for(
                lambda: (
                    self._stop.is_set()
                    or (self._frame is not None and self._frame.sequence > after)
                ),
                timeout,
            )
            if self._stop.is_set():
                return None
            return self._frame if self._frame is not None and self._frame.sequence > after else None

    def stop(self) -> None:
        self._stop.set()
        with self._changed:
            self._changed.notify_all()

    def join(self, timeout: float = 4.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def set_paused(self, paused: bool) -> None:
        if self.source.kind != "file" or type(paused) is not bool:
            raise ValueError("Pause requires a local recording and a boolean state.")
        with self._changed:
            self._paused = paused
            self._status = replace(self._status, paused=paused)
            self._changed.notify_all()

    def seek(self, seconds: float, generation: int) -> bool:
        if self.source.kind != "file" or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Seeking requires a finite nonnegative recording position.")
        with self._changed:
            if self._status.duration_seconds <= 0 or seconds > self._status.duration_seconds:
                raise ValueError("Seek position is outside the recording's known duration.")
            if generation <= self._generation:
                raise ValueError("Replay seek generations must increase.")
            if self._status.state == "ENDED":
                return False
            if self._stop.is_set() or self._status.state in ("ERROR", "STOPPED"):
                raise ReplayError("The recording is no longer available for seeking.")
            self._generation = generation
            self._pending_seek = (generation, seconds)
            self._frame = None
            self._status = replace(
                self._status,
                state="SEEKING",
                generation=generation,
                message="Seeking recorded input.",
            )
            self._changed.notify_all()
            return True

    def _set_status(self, state: str, message: str = "") -> None:
        with self._changed:
            self._status = replace(
                self._status,
                state=state,
                frames=self._sequence,
                fps=self._fps,
                reconnects=self._reconnects,
                message=message,
            )
            if state != "STREAMING":
                self._frame = None
            self._changed.notify_all()

    def _publish(
        self, image: NDArray[np.uint8], *, media_time: float | None = None, generation: int = 0
    ) -> bool:
        if image.ndim != 3 or image.shape[2] != 3 or image.size == 0:
            raise ValueError("Camera did not provide a BGR image.")
        if image.shape[0] * image.shape[1] > 20_000_000:
            raise ValueError("Camera image exceeds the 20 megapixel limit.")
        image = rotate_frame(image, self.rotation)
        now = time.perf_counter()
        if self._last_capture:
            measured = 1.0 / max(now - self._last_capture, 0.001)
            self._fps = measured if self._fps == 0 else self._fps * 0.9 + measured * 0.1
        self._last_capture = now
        with self._changed:
            if generation != self._generation:
                return False
            self._sequence += 1
            self._frame = CapturedFrame(self._sequence, now, image, media_time, generation)
            self._status = replace(
                self._status,
                state="PAUSED" if self._paused else "STREAMING",
                frames=self._sequence,
                fps=self._fps,
                reconnects=self._reconnects,
                size=(image.shape[1], image.shape[0]),
                position_seconds=media_time if media_time is not None else 0.0,
                paused=self._paused,
                generation=generation,
                message="",
            )
            self._changed.notify_all()
            return True

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._set_status("CONNECTING" if self._reconnects == 0 else "RECONNECTING")
                try:
                    if self.source.kind == "mjpeg":
                        self._read_mjpeg()
                    else:
                        self._read_native()
                    if self.source.kind == "file":
                        self._set_status("ENDED", "Replay reached the end of the file.")
                        return
                except (
                    OSError,
                    urllib.error.URLError,
                    ValueError,
                    cv2.error,
                    ReplayError,
                ) as error:
                    self._set_status(
                        "ERROR",
                        str(error) if isinstance(error, ReplayError) else camera_error(error),
                    )
                    if self.source.kind == "file":
                        return
                if not self._stop.is_set():
                    self._reconnects += 1
                    self._last_capture = 0.0
                    self._stop.wait(1.0)
        finally:
            if self._stop.is_set():
                self._set_status("STOPPED")
            elif self.status.state not in ("ERROR", "ENDED"):
                self._set_status(
                    "ERROR", "Capture worker ended unexpectedly. Reconnect the source."
                )

    def _read_mjpeg(self) -> None:
        passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        if self.source.username or self.source.password:
            passwords.add_password(
                None,
                str(self.source.location),
                self.source.username,
                self.source.password,
            )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _SameOriginRedirect(),
            urllib.request.HTTPBasicAuthHandler(passwords),
            urllib.request.HTTPDigestAuthHandler(passwords),
        )
        request = urllib.request.Request(
            str(self.source.location),
            headers={"User-Agent": "TrickRoom/0.1"},
        )
        parser = JPEGStream()
        last_image = time.perf_counter()
        with opener.open(request, timeout=3.0) as response:
            while not self._stop.is_set():
                chunk = response.read1(32768)
                if not chunk:
                    raise ConnectionError("MJPEG stream closed.")
                jpeg = parser.feed(chunk)
                if jpeg is not None:
                    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                    if image is None:
                        raise ValueError("Invalid MJPEG image.")
                    self._publish(image)
                    last_image = time.perf_counter()
                if time.perf_counter() - last_image > 5.0:
                    raise TimeoutError("No valid JPEG frames received.")

    def _read_native(self) -> None:
        backend = cv2.CAP_DSHOW if self.source.kind == "device" else cv2.CAP_ANY
        capture = cv2.VideoCapture(self.source.location, backend)
        try:
            if not capture.isOpened():
                raise OSError("Capture did not open.")
            if self.source.kind == "file":
                self._read_recording(capture)
                return
            if self.source.kind == "device":
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                capture.set(cv2.CAP_PROP_FPS, 30)
            while not self._stop.is_set():
                ok, image = capture.read()
                if not ok:
                    raise OSError("Camera read failed.")
                self._publish(image)
        finally:
            capture.release()

    def _read_recording(self, capture: cv2.VideoCapture) -> None:
        rate, count = capture.get(cv2.CAP_PROP_FPS), capture.get(cv2.CAP_PROP_FRAME_COUNT)
        known_duration = (
            math.isfinite(rate) and 1 <= rate <= 120 and math.isfinite(count) and count >= 1
        )
        fps = rate if math.isfinite(rate) and 1 <= rate <= 120 else 30.0
        duration = int(count) / fps if known_duration else 0.0
        with self._changed:
            self._status = replace(self._status, duration_seconds=duration, paused=self._paused)
        index, generation = 0, 0
        deadline = time.perf_counter()
        while not self._stop.is_set():
            with self._changed:
                if self._paused and self._pending_seek is None and self._frame is not None:
                    self._status = replace(self._status, state="PAUSED", paused=True)
                    self._changed.wait_for(
                        lambda: (
                            self._stop.is_set()
                            or not self._paused
                            or self._pending_seek is not None
                        )
                    )
                    deadline = time.perf_counter()
                    self._last_capture = 0.0
                if self._stop.is_set():
                    return
                pending, self._pending_seek = self._pending_seek, None
            if pending is not None:
                generation, seconds = pending
                if duration <= 0 or seconds > duration:
                    raise ReplayError("The requested seek exceeds the recording's usable duration.")
                index = min(math.floor(seconds * fps + 1e-6), int(count) - 1)
                if not capture.set(cv2.CAP_PROP_POS_FRAMES, index):
                    raise ReplayError("The video decoder could not seek to the selected frame.")
                actual = capture.get(cv2.CAP_PROP_POS_FRAMES)
                if not math.isfinite(actual) or abs(actual - index) > 0.5:
                    raise ReplayError("The video decoder did not reach the selected frame.")
                deadline = time.perf_counter()
                self._last_capture = 0.0
            ok, image = capture.read()
            if not ok:
                with self._changed:
                    if generation != self._generation:
                        continue
                    if index == 0 or (known_duration and index < int(count)):
                        raise ReplayError("The recording ended before its expected frame.")
                    self._status = replace(
                        self._status,
                        state="ENDED",
                        position_seconds=duration or index / fps,
                        message="Replay reached the end of the file.",
                    )
                return
            self._publish(image, media_time=index / fps, generation=generation)
            index += 1
            deadline += 1 / fps
            with self._changed:
                self._changed.wait_for(
                    lambda: self._stop.is_set() or self._paused or self._pending_seek is not None,
                    timeout=max(0, deadline - time.perf_counter()),
                )
