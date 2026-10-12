"""Owned native worker, bounded snapshot IPC and a separate opt-in private input preview."""

from __future__ import annotations

import logging
import math
import multiprocessing
import threading
import time
from dataclasses import dataclass, replace
from multiprocessing.connection import Connection
from pathlib import Path

import cv2

from trickroom.camera import Camera, CapturedFrame, CaptureStatus, ReplayError, Source
from trickroom.state import Observation
from trickroom.tracking import Tracker
from trickroom.worker_lifetime import WorkerJob

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    state: str = "READY"
    message: str = ""
    frames: int = 0
    fps: float = 0.0
    dropped: int = 0
    body_frames: int = 0
    face_frames: int = 0
    mean_inference_ms: float = 0.0
    worker_pid: int | None = None
    worker_exit_code: int | None = None
    forced_shutdown: bool = False


@dataclass(frozen=True)
class _Snapshot:
    status: RuntimeStatus
    capture: CaptureStatus
    observation: Observation | None
    preview: CapturedFrame | None = None
    finished: bool = False


@dataclass(frozen=True)
class _PlaybackCommand:
    seek_seconds: float | None = None
    paused: bool | None = None
    generation: int = 0


def _tracking_worker(
    connection: Connection,
    stop,
    preview_enabled,
    source,
    models,
    rotation,
    tracking_size,
    smooth,
    start_position,
    paused,
    owner_ready,
) -> None:
    camera = Camera(source, rotation, start_position=start_position, paused=paused)
    tracker = None
    observation = frame = None
    status = RuntimeStatus("LOADING")
    frames = body_frames = face_frames = dropped = last_sequence = 0
    mean_ms = fps = previous = last_preview = 0.0
    generation = 0

    def snapshot(*, finished=False):
        nonlocal last_preview
        raw = None
        now = time.perf_counter()
        capture = camera.status
        current = observation
        if current is not None and current.generation != capture.generation:
            current = None
        if (
            not finished
            and preview_enabled.is_set()
            and frame is not None
            and observation is not None
            and current is not None
            and now - frame.captured_at <= 0.6
            and now - last_preview >= 1 / 15
        ):
            raw = frame
            last_preview = now
        current_status = status
        if not finished and status.state == "RUNNING":
            current_status = replace(
                status, state="PAUSED" if capture.paused and current is not None else "RUNNING"
            )
        return _Snapshot(current_status, capture, current, raw, finished)

    try:
        if not owner_ready.wait(5):
            raise RuntimeError("The tracking owner did not establish child ownership.")
        if not stop.is_set():
            tracker = Tracker(models, tracking_size, smooth)
        if not stop.is_set():
            camera.start()
            status = RuntimeStatus("RUNNING")
            connection.send(snapshot())
        while not stop.is_set():
            if connection.poll():
                command = connection.recv()
                if isinstance(command, _PlaybackCommand):
                    if command.paused is not None:
                        camera.set_paused(command.paused)
                    if command.seek_seconds is not None:
                        if not camera.seek(command.seek_seconds, command.generation):
                            status = replace(status, state="ENDED", message=camera.status.message)
                            break
                        observation = frame = None
                elif command != "snapshot":
                    raise ValueError("Invalid worker control message.")
                connection.send(snapshot())
            incoming = camera.next_frame(last_sequence, timeout=0.02)
            if incoming is None:
                capture = camera.status
                if capture.state == "ENDED":
                    status = replace(status, state="ENDED", message=capture.message)
                    break
                if capture.state == "ERROR" and (source.kind == "file" or not camera.alive):
                    raise ReplayError(capture.message)
                continue
            dropped += max(0, incoming.sequence - last_sequence - 1)
            last_sequence = incoming.sequence
            if incoming.generation != generation:
                tracker.close()
                tracker = None
                tracker = Tracker(models, tracking_size, smooth)
                generation = incoming.generation
                previous = fps = 0.0
            observation = tracker.process(incoming)
            frame = incoming
            now = time.perf_counter()
            frames += 1
            body_frames += observation.visible_joints >= 4
            face_frames += observation.face is not None
            mean_ms += (observation.inference_ms - mean_ms) / frames
            if previous:
                rate = 1 / max(now - previous, 0.001)
                fps = rate if fps == 0 else fps * 0.85 + rate * 0.15
            previous = now
            status = RuntimeStatus(
                "RUNNING", "", frames, fps, dropped, body_frames, face_frames, mean_ms
            )
        if stop.is_set():
            status = replace(status, state="STOPPED")
    except FileNotFoundError as error:
        status = replace(status, state="ERROR", message=str(error))
    except ReplayError as error:
        status = replace(status, state="ERROR", message=str(error))
    except (ValueError, RuntimeError, OSError, ImportError, cv2.error) as error:
        status = replace(
            status,
            state="ERROR",
            message=f"Tracking stopped ({type(error).__name__}). "
            "Check local models, dependencies and the input; output remains synthetic.",
        )
    finally:
        final = snapshot(finished=True)
        camera.stop()
        try:
            if tracker is not None:
                tracker.close()
        finally:
            camera.join()
        try:
            connection.send(final)
        except (BrokenPipeError, EOFError, OSError):
            LOGGER.warning("Tracking worker's owner connection closed during shutdown.")
        connection.close()


class _CaptureView:
    def __init__(self, runtime: Runtime, source: Source) -> None:
        self._runtime = runtime
        self.source = source

    @property
    def status(self) -> CaptureStatus:
        with self._runtime._lock:
            return self._runtime._capture_status

    @property
    def alive(self) -> bool:
        return self._runtime.alive and self.status.state in (
            "CONNECTING",
            "STREAMING",
            "PAUSED",
            "SEEKING",
        )


class Runtime:
    def __init__(
        self,
        source: Source,
        model_directory: Path,
        rotation: str = "none",
        tracking_size: int = 768,
        smooth: bool = True,
        *,
        start_position: float = 0.0,
        paused: bool = False,
    ) -> None:
        self.camera = _CaptureView(self, source)
        self.model_directory = model_directory
        self.rotation = rotation
        self.tracking_size = tracking_size
        self.smooth = smooth
        if not math.isfinite(start_position) or start_position < 0 or type(paused) is not bool:
            raise ValueError("Replay start position must be finite and nonnegative.")
        if source.kind != "file" and (start_position or paused):
            raise ValueError("Playback controls require a local recording.")
        self.start_position, self.initial_paused = start_position, paused
        self._lock = threading.Lock()
        self._observation: Observation | None = None
        self._status = RuntimeStatus()
        self._context = multiprocessing.get_context("spawn")
        self._stop = self._context.Event()
        self._preview_enabled = self._context.Event()
        self._process = None
        self._job: WorkerJob | None = None
        self._connection: Connection | None = None
        self._thread: threading.Thread | None = None
        self._capture_status = CaptureStatus()
        self._input_preview_enabled = False
        self._input_preview: CapturedFrame | None = None
        self._preview_observation: Observation | None = None
        self.startup_timeout = 20.0
        self.response_timeout = 5.0
        self._playback_command: _PlaybackCommand | None = None
        self._seek_generation = 0

    def set_paused(self, paused: bool) -> None:
        if self.camera.source.kind != "file" or type(paused) is not bool:
            raise ValueError("Pause is only available for recorded-video playback.")
        if not self.alive or self._stop.is_set():
            raise RuntimeError("The replay worker is not running.")
        with self._lock:
            command = self._playback_command or _PlaybackCommand(generation=self._seek_generation)
            self._playback_command = replace(command, paused=paused)

    def seek(self, seconds: float) -> None:
        if self.camera.source.kind != "file" or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Seek requires a finite nonnegative recorded-video position.")
        if not self.alive or self._stop.is_set():
            raise RuntimeError("The replay worker is not running.")
        with self._lock:
            duration = self._capture_status.duration_seconds
            if duration <= 0 or seconds > duration:
                raise ValueError("Select a position within the recording's known duration.")
            self._seek_generation += 1
            paused = self._playback_command.paused if self._playback_command else None
            self._playback_command = _PlaybackCommand(seconds, paused, self._seek_generation)
            self._observation = self._input_preview = self._preview_observation = None
            self._capture_status = replace(
                self._capture_status,
                state="SEEKING",
                generation=self._seek_generation,
                position_seconds=seconds,
                message="Seeking recorded input.",
            )

    def enable_input_preview(self, enabled: bool) -> None:
        with self._lock:
            self._input_preview_enabled = enabled
            if enabled:
                self._preview_enabled.set()
            else:
                self._preview_enabled.clear()
            if not enabled:
                self._input_preview = None
                self._preview_observation = None

    @property
    def input_preview(self) -> CapturedFrame | None:
        with self._lock:
            self._expire_input_unlocked()
            return self._input_preview if self._input_preview_enabled else None

    @property
    def debug_snapshot(self) -> tuple[Observation | None, CapturedFrame | None]:
        with self._lock:
            self._expire_input_unlocked()
            if self._status.state not in ("RUNNING", "PAUSED") or self._stop.is_set():
                return None, None
            if self._input_preview_enabled and self._input_preview is not None:
                return self._preview_observation, self._input_preview
            return self._observation, None

    def _expire_input_unlocked(self) -> None:
        if (
            self._input_preview is not None
            and time.perf_counter() - self._input_preview.captured_at > 0.6
        ):
            self._input_preview = None
            self._preview_observation = None

    def _publish(
        self, observation: Observation | None, frame: CapturedFrame | None, status: RuntimeStatus
    ) -> None:
        with self._lock:
            if observation is None or observation.generation < self._seek_generation:
                observation = frame = None
            self._observation = observation
            self._status = status
            if self._input_preview_enabled and not self._stop.is_set() and frame is not None:
                image = frame.image.copy()
                image.flags.writeable = False
                self._input_preview = replace(frame, image=image)
                self._preview_observation = observation
            elif not self._input_preview_enabled or self._stop.is_set():
                self._input_preview = None
                self._preview_observation = None
            self._expire_input_unlocked()
            if status.state == "ERROR":
                self._observation = self._input_preview = self._preview_observation = None

    @property
    def observation(self) -> Observation | None:
        with self._lock:
            return self._observation

    @property
    def status(self) -> RuntimeStatus:
        with self._lock:
            return self._status

    @property
    def alive(self) -> bool:
        return (self._process is not None and self._process.is_alive()) or (
            self._thread is not None and self._thread.is_alive()
        )

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Create a new runtime for a new session.")
        if self._stop.is_set():
            self._set_status(RuntimeStatus("STOPPED"))
            return
        self._set_status(RuntimeStatus("LOADING", "Loading and verifying local tracking models."))
        self._connection, worker_connection = self._context.Pipe()
        owner_ready = self._context.Event()
        self._process = self._context.Process(
            target=_tracking_worker,
            args=(
                worker_connection,
                self._stop,
                self._preview_enabled,
                self.camera.source,
                self.model_directory,
                self.rotation,
                self.tracking_size,
                self.smooth,
                self.start_position,
                self.initial_paused,
                owner_ready,
            ),
            name="trickroom-tracking",
            daemon=True,
        )
        try:
            self._process.start()
            self._job = WorkerJob(self._process.sentinel)
            owner_ready.set()
        except (OSError, RuntimeError):
            if self._process.pid is not None and self._process.is_alive():
                self._process.terminate()
                self._process.join(1)
            if self._job is not None:
                self._job.close()
            self._connection.close()
            worker_connection.close()
            self._process = None
            self._set_status(RuntimeStatus("ERROR", "Could not start the tracking worker."))
            raise
        worker_connection.close()
        self._thread = threading.Thread(
            target=self._run, name="trickroom-worker-monitor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.enable_input_preview(False)

    def join(self, timeout: float = 6.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout)
        if self._process is not None:
            if self._stop.is_set() and self._process.is_alive():
                self._abort("Tracking worker exceeded the shutdown deadline.")
            self._process.join(0.2)
        if self._thread is not None and self._stop.is_set():
            self._thread.join(1)

    def _set_status(self, status: RuntimeStatus) -> None:
        with self._lock:
            self._status = status

    def _abort(self, message: str) -> None:
        LOGGER.error(message)
        self._publish(
            None,
            None,
            replace(self.status, state="ERROR", message=message, forced_shutdown=True),
        )
        self._stop.set()
        self.enable_input_preview(False)
        if self._process is not None and self._process.is_alive():
            self._process.terminate()
            self._process.join(1)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(1)

    def _run(self) -> None:
        connection = self._connection
        process = self._process
        last_response = time.perf_counter()
        requested = True
        final_received = False
        stopped_at = None
        next_request_at = 0.0
        try:
            while True:
                if self.status.forced_shutdown:
                    break
                now = time.perf_counter()
                if connection.poll(0.01):
                    packet = connection.recv()
                    if not isinstance(packet, _Snapshot):
                        self._abort("Invalid tracking worker response.")
                        break
                    last_response = now
                    requested = False
                    with self._lock:
                        if packet.capture.generation >= self._seek_generation:
                            self._capture_status = packet.capture
                    status = replace(packet.status, worker_pid=process.pid)
                    self._publish(packet.observation, packet.preview, status)
                    finished = packet.finished
                    packet = None
                    if finished:
                        final_received = True
                        break
                elif not process.is_alive():
                    break
                if self._stop.is_set():
                    stopped_at = stopped_at or now
                    if now - stopped_at > self.response_timeout:
                        self._abort("Tracking worker did not acknowledge shutdown.")
                        break
                    continue
                limit = (
                    self.startup_timeout
                    if self.status.state == "LOADING"
                    else self.response_timeout
                )
                if now - last_response > limit:
                    self._abort("Tracking worker stopped responding; output cleared safely.")
                    break
                if not requested and now >= next_request_at:
                    with self._lock:
                        command, self._playback_command = self._playback_command, None
                    connection.send(command or "snapshot")
                    requested = True
                    next_request_at = now + 1 / 30
        except (EOFError, BrokenPipeError, OSError):
            if self.status.state != "ERROR" and not final_received:
                LOGGER.error("Tracking worker IPC closed before a final response.")
        finally:
            connection.close()
            process.join(self.response_timeout if final_received else 0.2)
            if final_received and process.is_alive():
                self._abort("Tracking worker did not exit after its final response.")
            if not final_received and self.status.state != "ERROR":
                message = f"Tracking worker exited unexpectedly (code {process.exitcode})."
                if process.is_alive():
                    self._abort(message)
                else:
                    LOGGER.error(message)
                    self._publish(None, None, replace(self.status, state="ERROR", message=message))
            if not process.is_alive() and self._job is not None:
                self._job.close()
            self.enable_input_preview(False)
            self._set_status(
                replace(self.status, worker_pid=process.pid, worker_exit_code=process.exitcode)
            )
