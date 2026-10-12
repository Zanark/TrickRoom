import argparse
import json
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from trickroom import video_export
from trickroom.cli import main, parser, render_size, save_png
from trickroom.demo import demo_observation
from trickroom.video_export import (
    ExportFailure,
    RecordingInfo,
    RecordingReader,
    export_video,
    output_paths,
    publish_outputs,
    recording_info,
    verify_video,
)


def fake_worker(connection, stop, ready, *_args):
    assert ready.wait(5)
    connection.send(RecordingInfo(10, 3, 0, 3))
    for index in range(4):
        while not connection.poll(0.01):
            if stop.is_set():
                connection.close()
                return
        assert connection.recv() == "next"
        if index == 3:
            connection.send(None)
            break
        timestamp = index / 10
        connection.send(
            replace(
                demo_observation(index, timestamp),
                sequence=index + 1,
                completed_at=timestamp,
                media_time=timestamp,
            )
        )
    connection.close()


def hung_worker(connection, stop, ready, *_args):
    assert ready.wait(5)
    connection.send(RecordingInfo(10, 3, 0, 3))
    stop.wait(10)
    connection.close()


def options(tmp_path, *extra):
    source = tmp_path / "reference.avi"
    source.write_bytes(b"source is decoded by the injected test reader")
    return parser().parse_args(
        ["--source", str(source), "--render-video", str(tmp_path / "render.mp4"), *extra]
    )


class AuthoredReader:
    info = RecordingInfo(10, 3, 0, 3)
    exit_code = 0

    def __init__(self, *_args):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def __iter__(self):
        for index in range(3):
            timestamp = index / 10
            yield replace(
                demo_observation(index, timestamp),
                sequence=index + 1,
                completed_at=timestamp,
                media_time=timestamp,
            )


@pytest.mark.parametrize("value", ["1x1", "641x480", "640x481", "4098x720", "bad", "640x480x1"])
def test_render_size_rejects_invalid_encoder_dimensions(value):
    with pytest.raises(argparse.ArgumentTypeError):
        render_size(value)


def test_export_duration_default_does_not_truncate_to_smoke_test_duration():
    args = parser().parse_args(["--render-video", "out.mp4"])
    assert args.seconds is None
    assert args.render_size == (960, 720)


def test_recording_interval_uses_frame_boundaries_and_source_fps():
    capture = SimpleNamespace(get=lambda key: 10 if key == cv2.CAP_PROP_FPS else 100)
    assert recording_info(capture, 1.25, 0.25) == RecordingInfo(10, 100, 12, 3)
    assert recording_info(capture, 9.9, None) == RecordingInfo(10, 100, 99, 1)
    assert recording_info(capture, 0, 1e-12).selected_frames == 1
    with pytest.raises(ValueError, match="outside"):
        recording_info(capture, 10, None)


@pytest.mark.parametrize("fps,count", [(0, 10), (float("nan"), 10), (121, 10), (30, 0)])
def test_export_rejects_unusable_timing_instead_of_inventing_fps(fps, count):
    capture = SimpleNamespace(get=lambda key: fps if key == cv2.CAP_PROP_FPS else count)
    with pytest.raises(ValueError, match="metadata"):
        recording_info(capture, 0, None)


def test_existing_outputs_and_input_aliases_are_protected(tmp_path):
    args = options(tmp_path)
    destinations, _ = output_paths(args, Path(args.source))
    assert destinations[1].name == "render.report.json"
    destinations[0].write_bytes(b"keep this existing output")
    with pytest.raises(FileExistsError):
        output_paths(args, Path(args.source))
    assert destinations[0].read_bytes() == b"keep this existing output"
    destinations[0].unlink()
    args.report = Path(args.source)
    with pytest.raises(ValueError):
        output_paths(args, Path(args.source))


def test_output_publication_rolls_back_only_its_own_links_on_collision(tmp_path):
    staged = [tmp_path / "one.tmp", tmp_path / "two.tmp"]
    destinations = [tmp_path / "one.mp4", tmp_path / "two.json"]
    for path in staged:
        path.write_bytes(b"new")
    destinations[1].write_bytes(b"other process output")
    with pytest.raises(FileExistsError):
        publish_outputs(staged, destinations)
    assert not destinations[0].exists()
    assert destinations[1].read_bytes() == b"other process output"
    assert all(path.read_bytes() == b"new" for path in staged)


def test_real_encoder_and_report_include_only_synthetic_frames(tmp_path, monkeypatch):
    args = options(tmp_path, "--render-size", "320x240", "--snapshot", str(tmp_path / "last.png"))
    monkeypatch.setattr(video_export, "RecordingReader", AuthoredReader)
    assert export_video(args, save_png) == 0
    report = json.loads((tmp_path / "render.report.json").read_text())
    assert report["output"]["decoded_frames"] == 3
    assert report["output"]["duration_seconds"] == pytest.approx(0.3)
    assert report["skipped_source_frames"] == 0
    assert report["source_files_unchanged"] and not report["raw_pixels_or_landmarks_saved"]
    assert report["tracking_availability"]["FULL BODY"] == 3
    assert not report["model_visual_approval"] and not report["output"]["audio"]
    assert report["settings"]["mirror"] and not report["settings"]["clean_output"]
    assert str(tmp_path) not in json.dumps(report)
    assert cv2.imread(str(tmp_path / "last.png")).shape == (240, 320, 3)
    assert not list(tmp_path.glob(".trickroom-export-*"))
    with pytest.raises(RuntimeError, match="incomplete"):
        verify_video(tmp_path / "render.mp4", 4, (320, 240), 10)


def test_failed_and_cancelled_export_publish_nothing(tmp_path, monkeypatch):
    args = options(tmp_path)

    class FailedReader(AuthoredReader):
        def __iter__(self):
            yield from super().__iter__()
            raise KeyboardInterrupt

    monkeypatch.setattr(video_export, "RecordingReader", FailedReader)
    with pytest.raises(KeyboardInterrupt):
        export_video(args, save_png)
    assert not (tmp_path / "render.mp4").exists()
    assert not (tmp_path / "render.report.json").exists()
    assert not list(tmp_path.glob(".trickroom-export-*"))


def test_input_modified_during_export_is_not_accepted(tmp_path, monkeypatch):
    args = options(tmp_path, "--render-size", "320x240")

    class ChangedReader(AuthoredReader):
        def __iter__(self):
            yield from super().__iter__()
            Path(args.source).write_bytes(b"changed by another authoring operation")

    monkeypatch.setattr(video_export, "RecordingReader", ChangedReader)
    with pytest.raises(RuntimeError, match="changed during export"):
        export_video(args, save_png)
    assert not (tmp_path / "render.mp4").exists()
    assert not (tmp_path / "render.report.json").exists()
    assert not list(tmp_path.glob(".trickroom-export-*"))


def test_reordered_observation_cannot_produce_a_successful_video(tmp_path, monkeypatch):
    args = options(tmp_path, "--render-size", "320x240")

    class ReorderedReader(AuthoredReader):
        def __iter__(self):
            yield replace(next(iter(super().__iter__())), sequence=2)

    monkeypatch.setattr(video_export, "RecordingReader", ReorderedReader)
    with pytest.raises(RuntimeError, match="skipped or reordered"):
        export_video(args, save_png)
    assert not (tmp_path / "render.mp4").exists()
    assert not list(tmp_path.glob(".trickroom-export-*"))


def test_explicit_profile_is_required_and_protected(tmp_path):
    args = options(tmp_path)
    profile = tmp_path / "mapping.json"
    profile.write_text("{}")
    args.avatar_profile = profile
    with pytest.raises(ValueError, match="requires --avatar"):
        export_video(args, save_png)
    args.avatar = tmp_path / "character.glb"
    args.avatar.write_bytes(b"model input")
    args.report = profile
    with pytest.raises(ValueError, match="cannot replace"):
        output_paths(args, Path(args.source))
    assert profile.read_text() == "{}"


def test_native_tracker_stays_in_owned_lockstep_child(monkeypatch):
    monkeypatch.setattr(video_export, "_recording_worker", fake_worker)
    with RecordingReader(Path("unused.avi"), Path("."), "none", 768, 0, None) as reader:
        states = list(reader)
        assert [state.sequence for state in states] == [1, 2, 3]
        assert [state.media_time for state in states] == [0, 0.1, 0.2]
    assert reader.exit_code == 0
    reader.close()


def test_offline_worker_response_deadline_is_enforced(monkeypatch):
    monkeypatch.setattr(video_export, "_recording_worker", hung_worker)
    reader = RecordingReader(Path("unused.avi"), Path("."), "none", 768, 0, None)
    with reader:
        reader.response_timeout = 0.2
        with pytest.raises(RuntimeError, match="responding"):
            next(reader)
    assert reader.exit_code == 0


def test_actual_decoder_delivers_every_selected_frame_without_raw_ipc(tmp_path, monkeypatch):
    source = tmp_path / "indexed.avi"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    assert writer.isOpened()
    for index in range(5):
        writer.write(np.full((48, 64, 3), index * 40, np.uint8))
    writer.release()
    decoded = []

    class AuthoredTracker:
        def __init__(self, *_args):
            pass

        def process(self, frame):
            decoded.append((frame.media_time, float(frame.image.mean())))
            return replace(
                demo_observation(frame.media_time, frame.captured_at),
                sequence=frame.sequence,
                media_time=frame.media_time,
            )

        def close(self):
            pass

    packets = []
    connection = SimpleNamespace(
        send=packets.append, recv=lambda: "next", poll=lambda _timeout: True, close=lambda: None
    )
    ready = threading.Event()
    ready.set()
    monkeypatch.setattr(video_export, "Tracker", AuthoredTracker)
    video_export._recording_worker(
        connection, threading.Event(), ready, source, Path("."), "none", 768, 0.1, 0.3
    )
    assert packets[0] == RecordingInfo(10, 5, 1, 3)
    assert packets[-1] is None and not any(isinstance(item, ExportFailure) for item in packets)
    assert [item[0] for item in decoded] == [0.1, 0.2, 0.3]
    assert [item[1] for item in decoded] == pytest.approx([40, 80, 120], abs=2)
    assert all(
        state.completed_at == state.captured_at == state.media_time for state in packets[1:-1]
    )


def test_cli_video_mode_is_headless_and_rejects_live_or_preview_input(tmp_path, monkeypatch):
    monkeypatch.setenv("TRICKROOM_CAMERA_URL", "http://example.invalid/video")
    assert main(["--render-video", str(tmp_path / "out.mp4")]) == 2
    assert not (tmp_path / "out.mp4").exists()
    args = options(tmp_path, "--demo")
    with pytest.raises(ValueError, match="not demo"):
        export_video(args, save_png)
