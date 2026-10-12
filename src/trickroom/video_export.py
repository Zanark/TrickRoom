"""Explicit, lossless-in-frame-count offline export; camera pixels never reach the renderer."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import multiprocessing
import os
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import cv2

from trickroom.assets.motion import MotionOptions
from trickroom.camera import CapturedFrame, Source, rotate_frame
from trickroom.raster import close_renderer
from trickroom.render import Renderer, StageOptions
from trickroom.state import Observation
from trickroom.tracking import Tracker
from trickroom.worker_lifetime import WorkerJob

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecordingInfo:
    fps: float
    source_frames: int
    start_frame: int
    selected_frames: int


@dataclass(frozen=True)
class ExportFailure:
    message: str


def recording_info(capture, start_seconds: float, seconds: float | None) -> RecordingInfo:
    fps, count = capture.get(cv2.CAP_PROP_FPS), capture.get(cv2.CAP_PROP_FRAME_COUNT)
    if not math.isfinite(fps) or not 1 <= fps <= 120 or not math.isfinite(count) or count < 1:
        raise ValueError("The recording needs usable FPS (1-120) and frame-count metadata.")
    count = int(count)
    if count / fps > 86400:
        raise ValueError("Video export supports recordings up to 24 hours.")
    start = math.floor(start_seconds * fps + 1e-6)
    if start >= count:
        raise ValueError("The export start position is outside the recording.")
    length = (
        count - start
        if seconds is None
        else min(count - start, max(1, math.ceil(seconds * fps - 1e-9)))
    )
    if length < 1:
        raise ValueError("The selected interval contains no frames.")
    return RecordingInfo(fps, count, start, length)


def _recording_worker(
    connection, stop, ready, source, models, rotation, tracking_size, start, seconds
):
    capture = tracker = None
    try:
        if not ready.wait(5):
            raise RuntimeError("The export owner did not establish child ownership.")
        if stop.is_set():
            return
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            raise ValueError("The selected recording could not be opened.")
        info = recording_info(capture, start, seconds)
        if info.start_frame:
            if not capture.set(cv2.CAP_PROP_POS_FRAMES, info.start_frame):
                raise ValueError("The decoder could not seek to the selected start frame.")
            actual = capture.get(cv2.CAP_PROP_POS_FRAMES)
            if not math.isfinite(actual) or abs(actual - info.start_frame) > 0.5:
                raise ValueError("The decoder did not reach the selected start frame.")
        tracker = Tracker(models, tracking_size)
        connection.send(info)
        count = 0
        while not stop.is_set():
            if not connection.poll(0.05):
                continue
            if connection.recv() != "next":
                raise ValueError("Invalid offline tracking request.")
            if count == info.selected_frames:
                if info.start_frame + count == info.source_frames and capture.read()[0]:
                    raise ValueError(
                        "The recording contains more frames than its metadata reports."
                    )
                connection.send(None)
                return
            ok, pixels = capture.read()
            if not ok:
                raise ValueError("The recording ended before the selected interval was decoded.")
            if pixels.shape[0] * pixels.shape[1] > 20_000_000:
                raise ValueError("The recording exceeds the 20 megapixel input limit.")
            media_time = (info.start_frame + count) / info.fps
            count += 1
            state = tracker.process(
                CapturedFrame(count, media_time, rotate_frame(pixels, rotation), media_time)
            )
            # Offline presentation uses source time, not elapsed export/arrival time.
            connection.send(replace(state, completed_at=media_time))
    except (EOFError, BrokenPipeError):
        LOGGER.warning("The offline export owner disconnected.")
    except (ValueError, RuntimeError, OSError, ImportError, cv2.error) as error:
        try:
            message = (
                str(error)
                if isinstance(error, (FileNotFoundError, ValueError))
                else (
                    f"Offline tracking failed ({type(error).__name__}); "
                    "check the recording and models."
                )
            )
            connection.send(ExportFailure(message))
        except (EOFError, BrokenPipeError, OSError):
            LOGGER.warning("The offline export owner connection closed.")
    finally:
        try:
            if tracker is not None:
                tracker.close()
        finally:
            if capture is not None:
                capture.release()
            connection.close()


class RecordingReader:
    def __init__(self, source, models, rotation, tracking_size, start, seconds) -> None:
        context = multiprocessing.get_context("spawn")
        self.connection, self._child_connection = context.Pipe()
        self.stop, self.ready = context.Event(), context.Event()
        self.process = context.Process(
            target=_recording_worker,
            args=(
                self._child_connection,
                self.stop,
                self.ready,
                source,
                models,
                rotation,
                tracking_size,
                start,
                seconds,
            ),
            name="trickroom-offline-tracking",
            daemon=True,
        )
        self.job = None
        self.startup_timeout = 20.0
        self.response_timeout = 5.0
        self.info: RecordingInfo | None = None
        self._started = False
        self._closed = False
        self.exit_code: int | None = None

    def __enter__(self):
        try:
            self.process.start()
            self._started = True
            self.job = WorkerJob(self.process.sentinel)
            self._child_connection.close()
            self.ready.set()
            self.info = self._receive(self.startup_timeout)
            if not isinstance(self.info, RecordingInfo):
                raise RuntimeError("The export worker did not return recording metadata.")
            return self
        except BaseException:
            self.close()
            raise

    def _receive(self, timeout):
        if not self.connection.poll(timeout):
            raise RuntimeError("The offline tracking worker stopped responding.")
        try:
            packet = self.connection.recv()
        except (EOFError, OSError) as error:
            raise RuntimeError(
                "The offline tracking worker exited without a complete response."
            ) from error
        if isinstance(packet, ExportFailure):
            raise RuntimeError(packet.message)
        return packet

    def __iter__(self):
        return self

    def __next__(self) -> Observation:
        try:
            self.connection.send("next")
        except (BrokenPipeError, OSError) as error:
            raise RuntimeError("The offline tracking worker connection closed.") from error
        packet = self._receive(self.response_timeout)
        if packet is None:
            raise StopIteration
        if not isinstance(packet, Observation):
            raise RuntimeError("The export worker returned invalid observation data.")
        return packet

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.stop.set()
        self.connection.close()
        self._child_connection.close()
        forced = False
        if self._started:
            self.process.join(self.response_timeout)
            if self.process.is_alive():
                forced = True
                self.process.terminate()
                self.process.join(1)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join(1)
            self.exit_code = self.process.exitcode
            if not self.process.is_alive():
                self.process.close()
        if self.job is not None:
            self.job.close()
            self.job = None
        if forced:
            raise RuntimeError("The offline tracking worker exceeded its shutdown deadline.")
        if self._started and self.exit_code != 0:
            raise RuntimeError(f"The offline tracking worker exited with code {self.exit_code}.")

    def __exit__(self, *_args):
        self.close()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def output_paths(args, source: Path) -> tuple[list[Path], list[Path]]:
    video = args.render_video.resolve()
    report = (args.report or video.with_suffix(".report.json")).resolve()
    destinations = [video, report]
    if args.snapshot is not None:
        destinations.append(args.snapshot.resolve())
    suffixes = [".mp4", ".json"] + ([".png"] if args.snapshot is not None else [])
    if any(
        path.suffix.lower() != suffix for path, suffix in zip(destinations, suffixes, strict=True)
    ):
        raise ValueError("Video/report/snapshot outputs must use .mp4/.json/.png respectively.")
    if len(set(destinations)) != len(destinations):
        raise ValueError("Export outputs must have distinct paths.")
    inputs = [source]
    if args.avatar is not None:
        inputs.append(args.avatar.resolve())
        profile = args.avatar_profile or args.avatar.with_suffix(".trickroom.json")
        if profile.is_file():
            inputs.append(profile.resolve())
    for path in destinations:
        if path in inputs or any(
            path.exists() and item.exists() and path.samefile(item) for item in inputs
        ):
            raise ValueError("An export output cannot replace the recording, model or profile.")
        if path.exists():
            raise FileExistsError("An export output already exists. Choose new output names.")
    return destinations, inputs


def publish_outputs(staged: list[Path], destinations: list[Path]) -> None:
    created = []
    try:
        for temporary, destination in zip(staged, destinations, strict=True):
            os.link(temporary, destination)
            created.append((temporary, destination))
    except OSError:
        for temporary, destination in reversed(created):
            if destination.exists() and temporary.samefile(destination):
                destination.unlink()
        raise


def verify_video(path: Path, expected_frames: int, size: tuple[int, int], fps: float) -> dict:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise RuntimeError("The encoded video could not be reopened.")
        encoded_fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(encoded_fps) or abs(encoded_fps - fps) > 0.01:
            raise RuntimeError("The encoder did not preserve the requested frame rate.")
        count = 0
        while True:
            ok, image = capture.read()
            if not ok:
                break
            if (image.shape[1], image.shape[0]) != size:
                raise RuntimeError("The encoder changed the output dimensions.")
            count += 1
        if count != expected_frames or not count:
            raise RuntimeError("The encoded video is incomplete; outputs were not published.")
        return {
            "decoded_frames": count,
            "fps": encoded_fps,
            "duration_seconds": count / encoded_fps,
        }
    finally:
        capture.release()


def export_video(args, save_snapshot) -> int:
    if args.demo or args.avatar_mode != "live":
        raise ValueError("Video export uses recording detections, not demo/bind/clip preview.")
    if args.avatar_profile is not None and args.avatar is None:
        raise ValueError("--avatar-profile requires --avatar for video export.")
    if not math.isfinite(args.start_seconds) or args.start_seconds < 0:
        raise ValueError("The export start time must be finite and nonnegative.")
    source = Source.parse(args.source)
    if source.kind != "file":
        raise ValueError("Video export requires an existing recording, not a live camera source.")
    source_path = Path(source.location).resolve()
    destinations, inputs = output_paths(args, source_path)
    original = {path: digest(path) for path in inputs}
    renderer = Renderer()
    renderer.motion_options = MotionOptions(
        enabled=args.rig_motion,
        space=args.rig_space,
        constrain_limbs=args.rig_constraints,
        relax_missing=args.relax_missing,
        interpolation_delay=0.0,
    )
    renderer.face_response.enabled = args.face_response
    staged = []
    writer = None
    started = time.perf_counter()
    counts, presentation = Counter(), Counter()
    inference_ms = render_ms = 0.0
    rendered = 0
    last_image = None
    input_size = None
    graphics_shutdown_started = False
    try:
        if args.avatar is not None:
            renderer.load_model(args.avatar, args.avatar_profile)
        for path in destinations:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".trickroom-export-", suffix=path.suffix, delete=False
            ) as stream:
                staged.append(Path(stream.name))
        with RecordingReader(
            source_path,
            args.models,
            args.rotate,
            args.tracking_size,
            args.start_seconds,
            args.seconds,
        ) as reader:
            info = reader.info
            if info is None:
                raise RuntimeError("The export worker did not provide recording metadata.")
            writer = cv2.VideoWriter(
                str(staged[0]), cv2.VideoWriter_fourcc(*"mp4v"), info.fps, args.render_size
            )
            if not writer.isOpened():
                raise RuntimeError("The MP4 encoder could not be opened; no output was published.")
            for state in reader:
                expected_time = (info.start_frame + rendered) / info.fps
                if state.sequence != rendered + 1 or state.media_time != expected_time:
                    raise RuntimeError("The offline worker skipped or reordered a source frame.")
                before_render = time.perf_counter()
                last_image = renderer.render(
                    state,
                    args.render_size,
                    now=expected_time,
                    replay=True,
                    connection="EXPORT",
                    options=StageOptions(
                        mirror=args.mirror,
                        head_detail=not args.clean_output,
                        hud=not args.clean_output,
                    ),
                )
                render_ms += (time.perf_counter() - before_render) * 1000
                writer.write(last_image)
                rendered += 1
                input_size = state.frame_size
                inference_ms += state.inference_ms
                counts[state.body_status(expected_time)] += 1
                counts["face_present"] += state.face is not None
                if renderer._imported_frame is not None:
                    states = renderer._imported_frame.evaluation.tracking_states
                    if states is not None:
                        presentation.update(states.values())
                if rendered % 300 == 0:
                    print(
                        f"Rendered {rendered}/{info.selected_frames} reference frames.", flush=True
                    )
            if rendered != info.selected_frames:
                raise RuntimeError("Not every selected reference frame was rendered.")
        writer.release()
        writer = None
        encoded = verify_video(staged[0], rendered, args.render_size, info.fps)
        if any(digest(path) != old for path, old in original.items()):
            raise RuntimeError("An input file changed during export; outputs were not published.")
        if args.snapshot is not None:
            save_snapshot(staged[2], last_image)
        report = {
            "schema_version": 1,
            "mode": "offline-reference-video-render",
            "status": "complete",
            "source": {
                "sha256": original[source_path],
                **asdict(info),
                "frame_size_after_rotation": input_size,
                "start_seconds": info.start_frame / info.fps,
                "selected_duration_seconds": rendered / info.fps,
            },
            "output": {
                "video": destinations[0].name,
                "sha256": digest(staged[0]),
                "size": args.render_size,
                "codec": "mp4v",
                "audio": False,
                **encoded,
            },
            "rendered_frames": rendered,
            "skipped_source_frames": 0,
            "tracking_availability": dict(counts),
            "presentation_bone_state_samples": dict(presentation),
            "avatar": renderer.imported.asset.report() if renderer.imported else "built-in",
            "rig_motion": asdict(renderer.motion_options),
            "settings": {
                "mirror": args.mirror,
                "rotation": args.rotate,
                "tracking_size": args.tracking_size,
                "clean_output": args.clean_output,
                "face_response_enabled": args.face_response,
            },
            "elapsed_seconds": time.perf_counter() - started,
            "mean_inference_ms": inference_ms / rendered,
            "mean_render_ms": render_ms / rendered,
            "worker_exit_code": reader.exit_code,
            "source_files_unchanged": True,
            "raw_pixels_or_landmarks_saved": False,
            "physical_camera_opened": False,
            "personal_calibration_saved": False,
            "model_visual_approval": False,
            "clock": (
                "source frame index / reported FPS; offline timestamps, not live capture latency"
            ),
            "limitations": [
                "Constant-frame-rate export; not exact variable-frame-rate timestamp repair.",
                "Tracking availability and GLB validation do not prove rigging or motion accuracy.",
                "Input audio and raw reference images are not included.",
                "Native SDK telemetry policy is unchanged; local inference is not network silence.",
            ],
        }
        staged[1].write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        graphics_shutdown_started = True
        close_renderer()
        publish_outputs(staged, destinations)
        print(json.dumps(report, indent=2))
        return 0
    finally:
        if writer is not None:
            writer.release()
        try:
            if not graphics_shutdown_started:
                close_renderer()
        finally:
            for path in staged:
                path.unlink(missing_ok=True)
