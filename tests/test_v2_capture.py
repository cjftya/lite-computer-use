from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from scripts.lcu.capture import (
    CaptureMetadata,
    _load_capture_index,
    _save_capture_index,
    get_capture_metadata,
    resolve_capture_coordinates,
)
from scripts.lcu.errors import LCUError


@pytest.fixture
def mock_capture_index(tmp_path: object) -> None:
    # Set up sample metadata in index
    meta = CaptureMetadata(
        captureId="c_test_01",
        source="active-window",
        hwnd=12345,
        window_title="Test Window",
        window_bounds={"x": 100, "y": 200, "width": 800, "height": 600},
        source_bounds={"x": 100, "y": 200, "width": 800, "height": 600},
        crop_bounds=None,
        source_width=800,
        source_height=600,
        returned_width=400,
        returned_height=300,
        scale_x=0.5,
        scale_y=0.5,
        timestamp=time.time(),
        dpi_mode="Per-Monitor-V2",
        path="C:\\mock\\test.webp",
    )
    _save_capture_index({"c_test_01": meta})


def test_get_capture_metadata(mock_capture_index: None) -> None:
    meta = get_capture_metadata("c_test_01")
    assert meta.captureId == "c_test_01"
    assert meta.hwnd == 12345
    assert meta.scale_x == 0.5

    with pytest.raises(LCUError) as exc:
        get_capture_metadata("non_existent_cid")
    assert exc.value.code == "capture_not_found"


def test_resolve_capture_coordinates_success(mock_capture_index: None) -> None:
    with patch("win32gui.IsWindow", return_value=True), patch(
        "win32gui.GetForegroundWindow", return_value=12345
    ), patch("win32gui.GetWindowRect", return_value=(100, 200, 900, 800)):
        # Image center: (200, 150)
        # Scaled: 200 / 0.5 = 400
        # 150 / 0.5 = 300
        # Screen: 100 + 400 = 500, 200 + 300 = 500
        sx, sy = resolve_capture_coordinates("c_test_01", 200, 150)
        assert sx == 500
        assert sy == 500

        # Top-left corner: (0, 0)
        sx, sy = resolve_capture_coordinates("c_test_01", 0, 0)
        assert sx == 100
        assert sy == 200


def test_resolve_capture_coordinates_out_of_bounds(mock_capture_index: None) -> None:
    with patch("win32gui.IsWindow", return_value=True), patch(
        "win32gui.GetForegroundWindow", return_value=12345
    ), patch("win32gui.GetWindowRect", return_value=(100, 200, 900, 800)):
        with pytest.raises(LCUError) as exc:
            resolve_capture_coordinates("c_test_01", 401, 150)
        assert exc.value.code == "coordinate_out_of_bounds"

        with pytest.raises(LCUError) as exc:
            resolve_capture_coordinates("c_test_01", -1, 150)
        assert exc.value.code == "coordinate_out_of_bounds"


def test_stale_capture_window_closed(mock_capture_index: None) -> None:
    with patch("win32gui.IsWindow", return_value=False):
        with pytest.raises(LCUError) as exc:
            resolve_capture_coordinates("c_test_01", 100, 100)
        assert exc.value.code == "stale_capture"
        assert "closed" in exc.value.message


def test_stale_capture_lost_focus(mock_capture_index: None) -> None:
    with patch("win32gui.IsWindow", return_value=True), patch(
        "win32gui.GetForegroundWindow", return_value=99999
    ):
        with pytest.raises(LCUError) as exc:
            resolve_capture_coordinates("c_test_01", 100, 100)
        assert exc.value.code == "stale_capture"
        assert "lost focus" in exc.value.message


def test_stale_capture_moved(mock_capture_index: None) -> None:
    with patch("win32gui.IsWindow", return_value=True), patch(
        "win32gui.GetForegroundWindow", return_value=12345
    ), patch("win32gui.GetWindowRect", return_value=(150, 200, 950, 800)):  # moved by 50px
        with pytest.raises(LCUError) as exc:
            resolve_capture_coordinates("c_test_01", 100, 100)
        assert exc.value.code == "stale_capture"
        assert "moved or resized" in exc.value.message


def test_region_capture_coordinate_mapping() -> None:
    meta = CaptureMetadata(
        captureId="c_region_01",
        source="active-window",
        hwnd=12345,
        window_title="Test Window",
        window_bounds={"x": 100, "y": 200, "width": 800, "height": 600},
        source_bounds={"x": 150, "y": 250, "width": 200, "height": 100},  # region inside window
        crop_bounds={"x": 50, "y": 50, "width": 200, "height": 100},
        source_width=200,
        source_height=100,
        returned_width=200,
        returned_height=100,
        scale_x=1.0,
        scale_y=1.0,
        timestamp=time.time(),
        dpi_mode="Per-Monitor-V2",
        path="C:\\mock\\region.webp",
    )
    _save_capture_index({"c_region_01": meta})

    with patch("win32gui.IsWindow", return_value=True), patch(
        "win32gui.GetForegroundWindow", return_value=12345
    ), patch("win32gui.GetWindowRect", return_value=(100, 200, 900, 800)):
        # (10, 20) inside region
        # Screen: 150 + 10 = 160, 250 + 20 = 270
        sx, sy = resolve_capture_coordinates("c_region_01", 10, 20)
        assert sx == 160
        assert sy == 270
