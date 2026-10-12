"""Capture only the test window, and skip unavailable Windows desktops."""

import ctypes
import logging
import sys
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

LOGGER = logging.getLogger(__name__)


def desktop_available() -> bool:
    if sys.platform != "win32":
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL
    user32.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    desktop = user32.OpenInputDesktop(0, False, 1)
    if not desktop:
        return False
    try:
        name = ctypes.create_unicode_buffer(128)
        needed = wintypes.DWORD()
        return (
            bool(
                user32.GetUserObjectInformationW(
                    desktop,
                    2,
                    name,
                    ctypes.sizeof(name),
                    ctypes.byref(needed),
                )
            )
            and name.value.casefold() == "default"
        )
    finally:
        user32.CloseDesktop(desktop)


def capture_own_window(root: tk.Tk, destination: Path) -> bool:
    if not desktop_available():
        destination.unlink(missing_ok=True)
        LOGGER.warning("Skipping UI screenshot: normal Windows desktop is unavailable.")
        return False
    window = int(root.wm_frame(), 0)
    if window <= 0:
        raise ValueError("A valid application window handle is required for capture.")
    with ImageGrab.grab(window=window) as image:
        image.save(destination)
    return True
