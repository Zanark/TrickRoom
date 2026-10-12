import base64
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
import pytest

from trickroom.camera import (
    Camera,
    JPEGStream,
    Source,
    _SameOriginRedirect,
    camera_error,
    rotate_frame,
)


def test_source_normalization_keeps_credentials_private():
    source = Source.parse("http://name:p%40ss@127.0.0.1:8080")
    assert source.location == "http://127.0.0.1:8080/video"
    assert source.username == "name"
    assert source.password == "p@ss"
    assert "name" not in repr(source) and "p@ss" not in repr(source)
    assert Source.parse("0").kind == "device"
    assert Source.parse("http://[::1]:8080/video").location == "http://[::1]:8080/video"


@pytest.mark.parametrize(
    "source",
    [
        "",
        "rtsp://name:secret@localhost/live",
        "http://",
        "http://localhost:bad/video",
        "http://localhost/video#secret",
        "not-a-file",
        "-1",
    ],
)
def test_invalid_source_has_a_safe_error(source):
    with pytest.raises(ValueError) as error:
        Source.parse(source)
    assert "secret" not in str(error.value)


def test_control_characters_cannot_reach_the_http_client():
    with pytest.raises(ValueError, match="control characters") as error:
        Source.parse("http://localhost/secret\r\nvideo")
    assert "secret" not in str(error.value)


def test_jpeg_parser_handles_fragmentation_and_discards_backlog():
    parser = JPEGStream()
    assert parser.feed(b"header\r\n\xff") is None
    assert parser.feed(b"\xd8first") is None
    assert parser.feed(b"\xff\xd9") == b"\xff\xd8first\xff\xd9"
    assert parser.feed(b"\xff\xd8old\xff\xd9junk\xff\xd8new\xff\xd9") == b"\xff\xd8new\xff\xd9"
    assert len(parser.buffer) <= 1


def test_jpeg_parser_has_a_memory_bound():
    parser = JPEGStream(32)
    with pytest.raises(ValueError):
        parser.feed(b"\xff\xd8" + b"x" * 32)
    assert len(parser.buffer) == 0
    assert parser.feed(b"\xff\xd8ok\xff\xd9") is not None


def test_capture_publishes_only_latest_and_rotates():
    camera = Camera(Source("device", 0), rotation="left")
    camera._publish(np.zeros((30, 50, 3), np.uint8))
    camera._publish(np.full((30, 50, 3), 60, np.uint8))
    frame = camera.next_frame(0, 0)
    assert frame.sequence == 2
    assert frame.image.shape == (50, 30, 3)
    assert camera.status.size == (30, 50)
    assert np.all(frame.image == 60)
    assert camera.next_frame(2, 0) is None
    camera.stop()
    assert camera.next_frame(0, 0) is None


@pytest.mark.parametrize(
    "rotation,shape",
    [
        ("none", (3, 5, 3)),
        ("left", (5, 3, 3)),
        ("right", (5, 3, 3)),
        ("180", (3, 5, 3)),
    ],
)
def test_rotation_preserves_pixels(rotation, shape):
    image = np.arange(45, dtype=np.uint8).reshape(3, 5, 3)
    result = rotate_frame(image, rotation)
    assert result.shape == shape
    assert sorted(result.ravel()) == sorted(image.ravel())


def test_errors_never_echo_source_secrets():
    secret_url = "http://user:secret@localhost/video"
    error = urllib.error.HTTPError(secret_url, 401, "secret", {}, None)
    assert "authentication" in camera_error(error)
    assert "secret" not in camera_error(error)
    assert "secret" not in camera_error(ValueError(secret_url))
    assert "timed out" in camera_error(TimeoutError(secret_url))


def test_cross_origin_redirect_is_rejected_before_credentials_can_follow():
    request = urllib.request.Request("http://localhost:1234/video")
    with pytest.raises(ValueError):
        _SameOriginRedirect().redirect_request(
            request,
            None,
            302,
            "",
            {},
            "http://another-host/video",
        )


@contextmanager
def mjpeg_server(*, authenticated=False, fail_first=False):
    image = np.full((80, 120, 3), (20, 40, 180), np.uint8)
    ok, data = cv2.imencode(".jpg", image)
    assert ok
    jpeg = data.tobytes()
    stop = threading.Event()
    requests = 0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            nonlocal requests
            requests += 1
            if fail_first and requests == 1:
                self.send_response(503)
                self.end_headers()
                return
            expected = "Basic " + base64.b64encode(b"tester:fixture").decode()
            if authenticated and self.headers.get("Authorization") != expected:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="test-camera"')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                for _ in range(30):
                    if stop.is_set():
                        break
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n",
                    )
                    self.wfile.flush()
                    stop.wait(0.02)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/video"
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize("authenticated", [False, True])
def test_real_loopback_mjpeg_transport_and_shutdown(authenticated):
    with mjpeg_server(authenticated=authenticated) as url:
        camera = Camera(Source.parse(url, "tester" if authenticated else "", "fixture"))
        camera.start()
        try:
            frame = camera.next_frame(0, 3)
            assert frame is not None
            assert frame.image.shape == (80, 120, 3)
            assert camera.status.state == "STREAMING"
            assert camera.status.frames > 0
        finally:
            camera.stop()
            camera.join()
        assert not camera.alive
        assert camera.status.state == "STOPPED"


def test_mjpeg_reconnects_after_a_transient_server_failure():
    with mjpeg_server(fail_first=True) as url:
        camera = Camera(Source.parse(url))
        camera.start()
        try:
            assert camera.next_frame(0, 4) is not None
            assert camera.status.state == "STREAMING"
            assert camera.status.reconnects == 1
        finally:
            camera.stop()
            camera.join()
        assert not camera.alive


def test_capture_error_invalidates_the_old_frame_slot():
    camera = Camera(Source("device", 0))
    camera._publish(np.zeros((30, 50, 3), np.uint8))
    camera._set_status("ERROR", "Test disconnection")
    assert camera.next_frame(0, 0) is None
    assert camera.status.state == "ERROR"


def test_local_video_is_paced_and_stops_at_eof(tmp_path):
    path = tmp_path / "synthetic.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    assert writer.isOpened()
    for _ in range(5):
        writer.write(np.zeros((48, 64, 3), np.uint8))
    writer.release()
    camera = Camera(Source.parse(str(path)))
    started = time.perf_counter()
    camera.start()
    camera.join(3)
    assert not camera.alive
    assert camera.status.state == "ENDED"
    assert camera.status.frames == 5
    assert time.perf_counter() - started >= 0.4
