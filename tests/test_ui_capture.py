from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from tools import ui_capture


def test_unavailable_desktop_skips_pixels_and_clears_old_capture(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(ui_capture, "desktop_available", lambda: False)
    grab = Mock()
    monkeypatch.setattr(ui_capture.ImageGrab, "grab", grab)
    destination = tmp_path / "studio.png"
    destination.write_bytes(b"stale capture")

    assert not ui_capture.capture_own_window(Mock(), destination)
    grab.assert_not_called()
    assert not destination.exists()
    assert "Skipping UI screenshot" in caplog.text


def test_capture_requests_only_the_application_window(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_capture, "desktop_available", lambda: True)
    grab = Mock(return_value=Image.new("RGB", (20, 10), (13, 29, 21)))
    monkeypatch.setattr(ui_capture.ImageGrab, "grab", grab)
    root = Mock()
    root.wm_frame.return_value = "0x1234"
    destination = tmp_path / "studio.png"

    assert ui_capture.capture_own_window(root, destination)
    grab.assert_called_once_with(window=0x1234)
    with Image.open(destination) as image:
        assert image.size == (20, 10)
        assert image.getpixel((0, 0)) == (13, 29, 21)


def test_zero_window_handle_never_falls_back_to_desktop(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_capture, "desktop_available", lambda: True)
    grab = Mock()
    monkeypatch.setattr(ui_capture.ImageGrab, "grab", grab)
    root = Mock()
    root.wm_frame.return_value = "0x0"

    with pytest.raises(ValueError, match="valid application window"):
        ui_capture.capture_own_window(root, tmp_path / "studio.png")
    grab.assert_not_called()


def test_non_windows_desktop_is_not_captured(monkeypatch):
    monkeypatch.setattr(ui_capture, "sys", SimpleNamespace(platform="other"))
    assert not ui_capture.desktop_available()


@pytest.mark.parametrize(
    ("handle", "lookup_ok", "name", "expected"),
    [
        (0, True, "Default", False),
        (42, False, "", False),
        (42, True, "Winlogon", False),
        (42, True, "Default", True),
    ],
)
def test_windows_desktop_gate_and_handle_cleanup(monkeypatch, handle, lookup_ok, name, expected):
    user32 = Mock()
    user32.OpenInputDesktop.return_value = handle

    def lookup(desktop, kind, buffer, size, needed):
        buffer.value = name
        return lookup_ok

    user32.GetUserObjectInformationW.side_effect = lookup
    monkeypatch.setattr(ui_capture, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(ui_capture.ctypes, "WinDLL", Mock(return_value=user32), raising=False)

    assert ui_capture.desktop_available() is expected
    if handle:
        user32.CloseDesktop.assert_called_once_with(handle)
    else:
        user32.GetUserObjectInformationW.assert_not_called()
        user32.CloseDesktop.assert_not_called()
