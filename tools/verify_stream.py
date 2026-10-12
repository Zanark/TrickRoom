"""Timed loopback MJPEG -> real inference -> synthetic rendering. No physical camera is opened."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

from trickroom.camera import Source
from trickroom.cli import save_png
from trickroom.models import default_model_directory
from trickroom.raster import close_renderer, renderer_info
from trickroom.render import Renderer
from trickroom.runtime import Runtime

EXPECTED_SHA256 = "99e0649aa4f2553b0213982f544146565a1028877c4bb9fbe3884453659d8cdc"


def check(fixture: Path, output: Path, duration: float = 5, avatar: Path | None = None) -> dict:
    data = fixture.read_bytes()
    if hashlib.sha256(data).hexdigest() != EXPECTED_SHA256:
        raise ValueError(
            "Use the checksum-pinned public fitness fixture, not private camera media."
        )
    base = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    packets = []
    for shift in range(-12, 13, 4):
        image = cv2.warpAffine(
            base,
            np.float32(((1, 0, shift), (0, 1, 0))),
            (base.shape[1], base.shape[0]),
        )
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise OSError("Fixture JPEG encoding failed.")
        packets.append(encoded.tobytes())
    stopped = threading.Event()
    sent = 0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            nonlocal sent
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=trickroom")
            self.end_headers()
            deadline = time.perf_counter()
            try:
                while not stopped.is_set():
                    jpeg = packets[sent % len(packets)]
                    self.wfile.write(
                        b"--trickroom\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n",
                    )
                    self.wfile.flush()
                    sent += 1
                    deadline += 1 / 30
                    stopped.wait(max(0, deadline - time.perf_counter()))
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    runtime = Runtime(
        Source.parse(f"http://127.0.0.1:{server.server_port}/video"), default_model_directory()
    )
    renderer = Renderer()
    if avatar:
        renderer.load_model(avatar)
    render_ms, ages = [], []
    last_sequence = 0
    first_result_at = None
    output.mkdir(parents=True, exist_ok=True)
    report = {}
    try:
        runtime.start()
        deadline = time.perf_counter() + duration
        while time.perf_counter() < deadline:
            now = time.perf_counter()
            state = runtime.observation
            image = renderer.render(state, now=now, connection="RUNNING")
            render_ms.append((time.perf_counter() - now) * 1000)
            if state is not None and state.sequence != last_sequence:
                first_result_at = first_result_at or now
                ages.append(state.age(now) * 1000)
                last_sequence = state.sequence
            assert runtime.status.state != "ERROR", runtime.status.message
            time.sleep(max(0, 1 / 30 - (time.perf_counter() - now)))
        status, capture = runtime.status, runtime.camera.status
        assert status.frames >= 20, "Too few frames reached actual inference."
        assert status.body_frames >= 20 and status.face_frames >= 20
        assert status.fps >= 15, "Tracking did not sustain the prototype's 15 Hz local floor."
        assert runtime.observation.age(time.perf_counter()) < 0.6
        save_png(output / "loopback-synthetic.png", image)
        report = {
            "recorded_at": datetime.now().astimezone().isoformat(),
            "evidence_class": "30 Hz loopback MJPEG, transformed public still, real inference",
            "owner_camera_opened": False,
            "real_motion_recording": False,
            "camera_to_display_latency_measured": False,
            "input_frames": capture.frames,
            "inferred_frames": status.frames,
            "body_frames": status.body_frames,
            "face_frames": status.face_frames,
            "dropped_frames": status.dropped,
            "reported_inference_hz": round(status.fps, 2),
            "mean_inference_ms": round(status.mean_inference_ms, 2),
            "mean_renderer_ms": round(statistics.mean(render_ms), 2),
            "mean_postdecode_observation_age_ms": round(statistics.mean(ages), 2),
            "p95_postdecode_observation_age_ms": round(float(np.percentile(ages, 95)), 2),
            "passed": True,
            "avatar": renderer.imported.asset.report() if renderer.imported else "built-in",
            "graphics": renderer_info(),
        }
    finally:
        runtime.stop()
        runtime.join()
        stopped.set()
        server.shutdown()
        server.server_close()
        server_thread.join(2)
        close_renderer()
    assert not runtime.alive and not server_thread.is_alive()
    report["shutdown_complete"] = True
    (output / "loopback-report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path(".local/fixtures/fitness.jpg"))
    parser.add_argument("--output", type=Path, default=Path(".local/stream-check"))
    parser.add_argument("--avatar", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.fixture, args.output, avatar=args.avatar), indent=2))
