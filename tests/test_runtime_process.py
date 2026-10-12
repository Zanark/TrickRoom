import os
import time
from pathlib import Path

from trickroom.camera import CaptureStatus, Source
from trickroom.runtime import Runtime, RuntimeStatus, _Snapshot


def crashing_worker(*args):
    args[-1].wait(5)
    os._exit(23)


def hung_worker(*args):
    args[-1].wait(5)
    time.sleep(30)


def responsive_worker(connection, stop, preview_enabled, *args):
    args[-1].wait(5)
    packet = _Snapshot(RuntimeStatus("RUNNING"), CaptureStatus(), None)
    connection.send(packet)
    while not stop.is_set():
        if connection.poll(0.02):
            assert connection.recv() == "snapshot"
            connection.send(packet)
    connection.send(_Snapshot(RuntimeStatus("STOPPED"), CaptureStatus(), None, finished=True))
    connection.close()


def preview_worker(connection, stop, preview_enabled, *args):
    import numpy as np

    from trickroom.camera import CapturedFrame
    from trickroom.demo import demo_observation

    args[-1].wait(5)
    connection.send(_Snapshot(RuntimeStatus("RUNNING"), CaptureStatus(), None))
    sequence = 0
    while not stop.is_set():
        if connection.poll(0.02):
            assert connection.recv() == "snapshot"
            sequence += 1
            now = time.perf_counter()
            state = demo_observation(sequence / 30, now)
            raw = CapturedFrame(sequence, now, np.full((12, 20, 3), 42, np.uint8))
            connection.send(
                _Snapshot(
                    RuntimeStatus("RUNNING", frames=sequence),
                    CaptureStatus("STREAMING", frames=sequence),
                    state,
                    raw if preview_enabled.is_set() else None,
                )
            )
    connection.send(_Snapshot(RuntimeStatus("STOPPED"), CaptureStatus(), None, finished=True))
    connection.close()


def test_native_worker_failure_is_contained_and_reported(monkeypatch):
    monkeypatch.setattr("trickroom.runtime._tracking_worker", crashing_worker)
    runtime = Runtime(Source("device", 999), Path("."))
    runtime.start()
    runtime.join(5)
    assert not runtime.alive
    assert runtime.status.state == "ERROR"
    assert runtime.status.worker_exit_code == 23
    assert runtime.status.worker_pid != os.getpid()
    assert runtime.observation is None
    assert runtime.debug_snapshot == (None, None)


def test_hung_initialization_is_terminated_without_hanging_owner(monkeypatch):
    monkeypatch.setattr("trickroom.runtime._tracking_worker", hung_worker)
    runtime = Runtime(Source("device", 999), Path("."))
    runtime.startup_timeout = 0.35
    runtime.start()
    runtime.join(5)
    assert not runtime.alive
    assert runtime.status.state == "ERROR"
    assert runtime.status.forced_shutdown
    assert "responding" in runtime.status.message


def test_owned_worker_stops_and_can_be_replaced_by_a_new_session(monkeypatch):
    monkeypatch.setattr("trickroom.runtime._tracking_worker", responsive_worker)
    pids = []
    for _ in range(2):
        runtime = Runtime(Source("device", 999), Path("."))
        runtime.start()
        deadline = time.perf_counter() + 4
        while runtime.status.state == "LOADING" and time.perf_counter() < deadline:
            time.sleep(0.01)
        assert runtime.status.state == "RUNNING"
        pids.append(runtime.status.worker_pid)
        runtime.stop()
        runtime.join(3)
        assert not runtime.alive
        assert runtime.status.state == "STOPPED"
        assert runtime.status.worker_exit_code == 0
    assert all(pid != os.getpid() for pid in pids)


def test_stop_before_start_never_creates_a_worker():
    runtime = Runtime(Source("device", 999), Path("."))
    runtime.stop()
    runtime.start()
    assert runtime.status.state == "STOPPED"
    assert runtime._process is None


def test_spawned_preview_is_paired_readonly_and_revoked_on_disable(monkeypatch):
    monkeypatch.setattr("trickroom.runtime._tracking_worker", preview_worker)
    runtime = Runtime(Source("device", 999), Path("."))
    runtime.start()
    try:
        deadline = time.perf_counter() + 4
        while runtime.observation is None and time.perf_counter() < deadline:
            time.sleep(0.01)
        assert runtime.observation is not None and runtime.input_preview is None
        runtime.enable_input_preview(True)
        deadline = time.perf_counter() + 3
        while runtime.input_preview is None and time.perf_counter() < deadline:
            time.sleep(0.01)
        observation, preview = runtime.debug_snapshot
        assert preview is not None
        assert observation.captured_at == preview.captured_at
        assert not preview.image.flags.writeable
        runtime.enable_input_preview(False)
        assert runtime.input_preview is None
        time.sleep(0.1)
        assert runtime.debug_snapshot[1] is None
    finally:
        runtime.stop()
        runtime.join(3)
    assert not runtime.alive


def test_windows_job_owns_only_the_started_worker(monkeypatch):
    monkeypatch.setattr("trickroom.runtime._tracking_worker", hung_worker)
    runtime = Runtime(Source("device", 999), Path("."))
    runtime.start()
    if runtime._job.handle is not None:
        runtime._job.close()
        runtime.join(4)
        assert not runtime.alive
        assert runtime.status.state == "ERROR"
    else:
        runtime.stop()
        runtime.join(1)
        assert not runtime.alive
