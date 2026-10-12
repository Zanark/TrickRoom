"""One bounded owner for mutable avatar state and its thread-local OpenGL resources."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from functools import partial
from typing import TypeVar

from trickroom.assets.presentation import ModelPresentation
from trickroom.raster import close_renderer
from trickroom.render import Renderer

T = TypeVar("T")
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GraphicsStatus:
    imported: bool = False
    preview: bool = False
    mode: str = "live"
    frame: ModelPresentation | None = None
    face_message: str = ""
    face_collecting: str | None = None
    face_calibrated: bool = False


class GraphicsWorker:
    def __init__(self, renderer: Renderer) -> None:
        self.renderer = renderer
        self.status = GraphicsStatus()
        self.error: Exception | None = None
        self._queue: queue.Queue = queue.Queue(maxsize=32)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="trickroom-graphics", daemon=True)
        self._thread.start()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def submit(self, function: Callable[..., T], *args, **kwargs) -> Future[T]:
        if self._stop.is_set():
            raise RuntimeError("The graphics worker is stopping.")
        future: Future[T] = Future()
        try:
            self._queue.put_nowait((future, partial(function, *args, **kwargs)))
        except queue.Full as error:
            raise RuntimeError("Too many pending graphics operations.") from error
        return future

    def close(self) -> None:
        self._stop.set()

    def join(self, timeout: float = 1.0) -> None:
        self._thread.join(timeout)

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    future, function = self._queue.get(timeout=0.02)
                except queue.Empty:
                    continue
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    result = function()
                    model, face = self.renderer.imported, self.renderer.face_response
                    self.status = GraphicsStatus(
                        imported=model is not None,
                        preview=model.preview if model is not None else False,
                        mode=model.mode if model is not None else "live",
                        frame=self.renderer._imported_frame,
                        face_message=face.message,
                        face_collecting=face.collecting,
                        face_calibrated=face.calibrated,
                    )
                except Exception as error:
                    future.set_exception(error)
                else:
                    future.set_result(result)
        finally:
            while True:
                try:
                    future, _function = self._queue.get_nowait()
                except queue.Empty:
                    break
                future.cancel()
            try:
                close_renderer()
            except Exception as error:
                self.error = error
                LOGGER.exception("Graphics resource cleanup failed.")
