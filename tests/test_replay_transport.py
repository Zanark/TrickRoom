import multiprocessing
import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

import trickroom.runtime as runtime_module
from trickroom.camera import Camera, CapturedFrame, CaptureStatus, Source
from trickroom.demo import demo_observation
from trickroom.runtime import Runtime, RuntimeStatus, _PlaybackCommand, _Snapshot


def wait_for(predicate, timeout=4):
    deadline = time.perf_counter() + timeout
    while not predicate() and time.perf_counter() < deadline:
        time.sleep(0.01)
    assert predicate()


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "indexed.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 20, (64, 48))
    assert writer.isOpened()
    for index in range(80):
        writer.write(np.full((48, 64, 3), index * 3, np.uint8))
    writer.release()
    return Source.parse(str(path))


def test_capture_seek_pause_resume_and_end_decode_the_selected_frames(recording):
    camera = Camera(recording, paused=True)
    camera.start()
    try:
        first = camera.next_frame(0, 3)
        assert first is not None and first.media_time == 0
        assert camera.status.duration_seconds == 4
        assert camera.next_frame(first.sequence, 0.12) is None
        assert camera.seek(2, 1)
        forward = camera.next_frame(first.sequence, 3)
        assert forward.generation == 1 and forward.media_time == 2
        assert np.mean(forward.image) == pytest.approx(120, abs=1)
        assert camera.seek(0.5, 2)
        backward = camera.next_frame(forward.sequence, 3)
        assert backward.media_time == 0.5 and backward.generation == 2
        assert np.mean(backward.image) == pytest.approx(30, abs=1)
        assert first.captured_at < forward.captured_at < backward.captured_at
        assert camera.next_frame(backward.sequence, 0.12) is None
        camera.set_paused(False)
        resumed = camera.next_frame(backward.sequence, 3)
        assert 0.5 < resumed.media_time < 0.7
        camera.set_paused(True)
        time.sleep(0.15)
        count = camera.status.frames
        assert camera.next_frame(count, 0.15) is None
        assert camera.status.frames == count and camera.status.paused
        assert camera.seek(camera.status.duration_seconds, 3)
        end = camera.next_frame(count, 3)
        assert end.media_time == 3.95 and end.generation == 3
        assert np.mean(end.image) == pytest.approx(237, abs=1)
        camera.set_paused(False)
        camera.join(2)
        assert not camera.alive and camera.status.state == "ENDED"
        assert camera.status.position_seconds == camera.status.duration_seconds == 4
        assert not camera.seek(1, 4)
        assert camera.status.state == "ENDED"
    finally:
        camera.stop()
        camera.join()
    assert not camera.alive


def test_paused_capture_stop_wakes_the_waiter(recording):
    camera = Camera(recording, start_position=1.5, paused=True)
    camera.start()
    frame = camera.next_frame(0, 3)
    assert frame.media_time == 1.5
    started = time.perf_counter()
    camera.stop()
    camera.join(1)
    assert not camera.alive and time.perf_counter() - started < 1
    assert camera.status.state == "STOPPED"


@pytest.mark.parametrize("seconds", [-1, float("nan"), float("inf"), 4.01])
def test_capture_rejects_invalid_seek_without_changing_the_frame(recording, seconds):
    camera = Camera(recording, paused=True)
    camera.start()
    try:
        first = camera.next_frame(0, 3)
        with pytest.raises(ValueError):
            camera.seek(seconds, 1)
        assert camera.next_frame(0, 0) is first
        assert camera.status.generation == 0
    finally:
        camera.stop()
        camera.join()


def test_transport_rejects_live_sources_unknown_duration_and_old_generations(recording):
    live = Camera(Source("device", 0))
    with pytest.raises(ValueError):
        live.set_paused(True)
    with pytest.raises(ValueError):
        live.seek(0, 1)
    unknown = Camera(recording)
    with pytest.raises(ValueError):
        unknown.seek(0, 1)
    camera = Camera(recording, paused=True)
    camera.start()
    try:
        assert camera.next_frame(0, 3) is not None
        with pytest.raises(ValueError):
            camera.seek(1, 0)
        with pytest.raises(ValueError):
            camera.set_paused("paused")
    finally:
        camera.stop()
        camera.join()


class Decoder:
    def __init__(self, *, block_first=False, reject_seek=False, wrong_position=False):
        self.position = 0
        self.started, self.release_read = threading.Event(), threading.Event()
        self.block_first = block_first
        self.reject_seek, self.wrong_position = reject_seek, wrong_position
        self.seeks = []
        self.released = False

    def isOpened(self):
        return True

    def get(self, field):
        return {
            cv2.CAP_PROP_FPS: 10,
            cv2.CAP_PROP_FRAME_COUNT: 40,
            cv2.CAP_PROP_POS_FRAMES: self.position,
        }[field]

    def set(self, field, value):
        assert field == cv2.CAP_PROP_POS_FRAMES
        self.seeks.append(value)
        if self.reject_seek:
            return False
        self.position = value + 5 if self.wrong_position else value
        return True

    def read(self):
        index = self.position
        if self.block_first and index == 0:
            self.started.set()
            assert self.release_read.wait(3)
        self.position += 1
        return True, np.full((48, 64, 3), index, np.uint8)

    def release(self):
        self.released = True


def test_seek_discards_inflight_decode_and_coalesces_to_the_latest_target(monkeypatch):
    decoder = Decoder(block_first=True)
    monkeypatch.setattr("trickroom.camera.cv2.VideoCapture", lambda *_: decoder)
    camera = Camera(Source("file", "synthetic-only.avi"), paused=True)
    camera.start()
    try:
        assert decoder.started.wait(3)
        assert camera.seek(1, 1)
        assert camera.seek(2, 2)
        assert camera.next_frame(0, 0) is None
        decoder.release_read.set()
        frame = camera.next_frame(0, 3)
        assert frame.generation == 2 and frame.sequence == 1 and frame.media_time == 2
        assert np.all(frame.image == 20)
        assert decoder.seeks == [20]
    finally:
        decoder.release_read.set()
        camera.stop()
        camera.join()
    assert decoder.released and not camera.alive


@pytest.mark.parametrize("failure", ["reject_seek", "wrong_position"])
def test_decoder_seek_failures_are_visible_and_never_keep_old_pixels(monkeypatch, failure):
    decoder = Decoder(**{failure: True})
    monkeypatch.setattr("trickroom.camera.cv2.VideoCapture", lambda *_: decoder)
    camera = Camera(Source("file", "private-source.avi"), paused=True)
    camera.start()
    try:
        assert camera.next_frame(0, 3) is not None
        assert camera.seek(1, 1)
        camera.join(3)
        assert camera.status.state == "ERROR" and not camera.alive
        assert "decoder" in camera.status.message
        assert "private-source" not in camera.status.message
        assert camera.next_frame(0, 0) is None
    finally:
        camera.stop()
        camera.join()


def transport_worker(connection, stop, preview_enabled, *args):
    args[-1].wait(5)
    generation, sequence, position, paused = 0, 1, args[-3], args[-2]
    observation = None

    def packet(finished=False):
        nonlocal observation
        if observation is None:
            observation = replace(
                demo_observation(0, time.perf_counter()),
                sequence=sequence,
                generation=generation,
                media_time=position,
            )
        raw = CapturedFrame(
            sequence,
            observation.captured_at,
            np.full((12, 20, 3), 42, np.uint8),
            position,
            generation,
        )
        return _Snapshot(
            RuntimeStatus(
                "STOPPED" if finished else "PAUSED" if paused else "RUNNING", frames=sequence
            ),
            CaptureStatus(
                "PAUSED" if paused else "STREAMING",
                frames=sequence,
                duration_seconds=10,
                position_seconds=position,
                paused=paused,
                generation=generation,
            ),
            observation,
            raw if preview_enabled.is_set() and not finished else None,
            finished,
        )

    connection.send(packet())
    while not stop.is_set():
        if connection.poll(0.02):
            command = connection.recv()
            if isinstance(command, _PlaybackCommand):
                if command.paused is not None:
                    paused = command.paused
                if command.seek_seconds is not None:
                    generation, position = command.generation, command.seek_seconds
                    sequence += 1
                    observation = None
            else:
                assert command == "snapshot"
            connection.send(packet())
    connection.send(packet(finished=True))
    connection.close()


def test_runtime_paused_heartbeat_seeking_and_preview_expiry_use_one_owned_worker(monkeypatch):
    monkeypatch.setattr(runtime_module, "_tracking_worker", transport_worker)
    runtime = Runtime(Source("file", "synthetic.avi"), Path("."), paused=True)
    runtime.enable_input_preview(True)
    runtime.start()
    try:
        wait_for(lambda: runtime.observation is not None and runtime.input_preview is not None)
        pid, first = runtime.status.worker_pid, runtime.observation
        assert runtime.status.state == "PAUSED"
        time.sleep(0.7)
        assert runtime.observation == first
        assert runtime.input_preview is None
        assert runtime.debug_snapshot == (first, None)
        runtime.seek(8)
        assert runtime.observation is None and runtime.input_preview is None
        wait_for(lambda: runtime.observation is not None and runtime.observation.generation == 1)
        assert runtime.observation.media_time == 8 and runtime.status.state == "PAUSED"
        runtime.seek(2)
        wait_for(lambda: runtime.observation is not None and runtime.observation.generation == 2)
        assert runtime.observation.media_time == 2
        assert runtime.observation.captured_at > first.captured_at
        runtime.set_paused(False)
        wait_for(lambda: runtime.status.state == "RUNNING")
        assert runtime.status.worker_pid == pid
    finally:
        runtime.stop()
        runtime.join(3)
    assert not runtime.alive and runtime.status.worker_exit_code == 0
    assert not runtime.status.forced_shutdown


def test_pending_pause_and_seek_commands_merge_and_stale_snapshots_cannot_reappear():
    runtime = Runtime(Source("file", "synthetic.avi"), Path("."))
    runtime._thread = Mock()
    runtime._capture_status = CaptureStatus("STREAMING", duration_seconds=10)
    state = replace(demo_observation(0, time.perf_counter()), media_time=0)
    frame = CapturedFrame(state.sequence, state.captured_at, np.zeros((12, 20, 3), np.uint8))
    runtime.enable_input_preview(True)
    runtime._publish(state, frame, RuntimeStatus("RUNNING"))
    runtime.set_paused(True)
    runtime.seek(8)
    runtime.seek(2)
    assert runtime._playback_command == _PlaybackCommand(2, True, 2)
    assert runtime.observation is None and runtime.input_preview is None
    runtime._publish(state, frame, RuntimeStatus("RUNNING"))
    assert runtime.observation is None and runtime.input_preview is None
    runtime.set_paused(False)
    assert runtime._playback_command == _PlaybackCommand(2, False, 2)


@pytest.mark.parametrize("position", [-1, float("nan"), float("inf"), 11])
def test_runtime_rejects_invalid_seek_positions(position):
    runtime = Runtime(Source("file", "synthetic.avi"), Path("."))
    runtime._thread = Mock()
    runtime._capture_status = CaptureStatus(duration_seconds=10)
    with pytest.raises(ValueError):
        runtime.seek(position)
    assert runtime._playback_command is None and runtime._seek_generation == 0


def test_runtime_controls_require_running_recorded_input():
    runtime = Runtime(Source("device", 0), Path("."))
    with pytest.raises(ValueError):
        runtime.seek(1)
    with pytest.raises(ValueError):
        runtime.set_paused(True)
    runtime = Runtime(Source("file", "synthetic.avi"), Path("."))
    with pytest.raises(RuntimeError):
        runtime.set_paused(True)
    with pytest.raises(RuntimeError):
        runtime.seek(0)
    with pytest.raises(ValueError):
        Runtime(Source("device", 0), Path("."), start_position=1)
    with pytest.raises(ValueError):
        Camera(Source("file", "synthetic.avi"), start_position=float("nan"))


def hung_seek_worker(connection, stop, preview_enabled, *args):
    args[-1].wait(5)
    packet = _Snapshot(
        RuntimeStatus("PAUSED"), CaptureStatus("PAUSED", duration_seconds=10, paused=True), None
    )
    connection.send(packet)
    while not stop.is_set():
        if connection.poll(0.02):
            if isinstance(connection.recv(), _PlaybackCommand):
                time.sleep(30)
            connection.send(packet)


def test_paused_seek_does_not_disable_the_worker_watchdog(monkeypatch):
    monkeypatch.setattr(runtime_module, "_tracking_worker", hung_seek_worker)
    runtime = Runtime(Source("file", "synthetic.avi"), Path("."), paused=True)
    runtime.response_timeout = 0.4
    runtime.start()
    try:
        wait_for(lambda: runtime.status.state == "PAUSED")
        runtime.seek(2)
        runtime.join(5)
        assert not runtime.alive
        assert runtime.status.state == "ERROR" and runtime.status.forced_shutdown
        assert runtime.observation is None and runtime.input_preview is None
    finally:
        runtime.stop()
        runtime.join(1)


def test_real_worker_loop_recreates_tracking_at_each_seek_and_closes_while_paused(
    recording, monkeypatch, tmp_path
):
    trackers = []

    class Tracker:
        def __init__(self, *_):
            self.generations = []
            self.closed = False
            trackers.append(self)

        def process(self, frame):
            self.generations.append(frame.generation)
            return replace(
                demo_observation(0, frame.captured_at),
                sequence=frame.sequence,
                generation=frame.generation,
                media_time=frame.media_time,
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(runtime_module, "Tracker", Tracker)
    parent, child = multiprocessing.Pipe()
    stop, preview, ready = threading.Event(), threading.Event(), threading.Event()
    ready.set()
    worker = threading.Thread(
        target=runtime_module._tracking_worker,
        args=(child, stop, preview, recording, tmp_path, "none", 768, True, 1.5, True, ready),
    )
    worker.start()

    def request(command="snapshot"):
        parent.send(command)
        assert parent.poll(3)
        result = parent.recv()
        assert result.status.state != "ERROR", result.status.message
        return result

    def observed(generation):
        deadline = time.perf_counter() + 3
        while time.perf_counter() < deadline:
            result = request()
            if result.observation is not None and result.observation.generation == generation:
                return result
            time.sleep(0.01)
        pytest.fail("The worker did not infer the selected generation.")

    try:
        assert parent.poll(3)
        parent.recv()
        assert observed(0).observation.media_time == 1.5
        assert request(_PlaybackCommand(2.5, True, 1)).observation is None
        assert observed(1).observation.media_time == 2.5
        assert request(_PlaybackCommand(0.5, True, 2)).observation is None
        result = observed(2)
        assert result.observation.media_time == 0.5 and result.status.state == "PAUSED"
        assert [tracker.generations for tracker in trackers] == [[0], [1], [2]]
        assert all(tracker.closed for tracker in trackers[:-1])
    finally:
        stop.set()
        worker.join(3)
        parent.close()
    assert not worker.is_alive()
    assert all(tracker.closed for tracker in trackers)
