import threading

import pytest

from trickroom.graphics_worker import GraphicsWorker
from trickroom.render import Renderer


def test_graphics_operations_have_one_non_ui_owner_and_publish_immutable_status():
    renderer = Renderer()
    worker = GraphicsWorker(renderer)
    try:
        ids = [worker.submit(threading.get_ident).result(2) for _ in range(3)]
        assert len(set(ids)) == 1 and ids[0] != threading.get_ident()
        worker.submit(renderer.face_response.begin, "neutral", 10).result(2)
        status = worker.status
        assert status.face_collecting == "neutral"
        worker.submit(renderer.face_response.reset).result(2)
        assert worker.status.face_collecting is None
        assert status.face_collecting == "neutral"
    finally:
        worker.close()
        worker.join(2)
    assert not worker.alive


def test_graphics_failure_is_delivered_to_the_owner_not_swallowed():
    worker = GraphicsWorker(Renderer())
    try:
        future = worker.submit(lambda: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            future.result(2)
    finally:
        worker.close()
        worker.join(2)
    with pytest.raises(RuntimeError, match="stopping"):
        worker.submit(lambda: None)


def test_graphics_shutdown_cancels_queued_work_and_waits_for_current_work():
    worker = GraphicsWorker(Renderer())
    started, release = threading.Event(), threading.Event()

    def current():
        started.set()
        release.wait(2)

    future = worker.submit(current)
    assert started.wait(2)
    queued = worker.submit(lambda: pytest.fail("Queued work ran after shutdown."))
    worker.close()
    release.set()
    worker.join(2)
    assert future.done() and queued.cancelled() and not worker.alive
