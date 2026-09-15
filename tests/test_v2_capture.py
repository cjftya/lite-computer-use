from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from scripts.lcu.capture import (
    MAX_CAPTURES_IN_CACHE,
    CaptureMetadata,
    _load_capture_index,
    _prune_capture_cache,
    _save_capture_index,
    capture_screenshot,
    get_capture_metadata,
    resolve_capture_coordinates,
)
from scripts.lcu.errors import LCUError


@pytest.fixture
def mock_capture_index(tmp_path: Path) -> None:
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

        # Bottom-right valid corner: (399, 299)
        sx, sy = resolve_capture_coordinates("c_test_01", 399, 299)
        assert sx == int(round(100 + 399 / 0.5))
        assert sy == int(round(200 + 299 / 0.5))


def test_resolve_capture_coordinates_boundary_conditions(mock_capture_index: None) -> None:
    # returned_width = 400, returned_height = 300
    with patch("win32gui.IsWindow", return_value=True), patch(
        "win32gui.GetForegroundWindow", return_value=12345
    ), patch("win32gui.GetWindowRect", return_value=(100, 200, 900, 800)):
        # x == width (400) is OUT of bounds
        with pytest.raises(LCUError) as exc:
            resolve_capture_coordinates("c_test_01", 400, 0)
        assert exc.value.code == "coordinate_out_of_bounds"

        # y == height (300) is OUT of bounds
        with pytest.raises(LCUError) as exc:
            resolve_capture_coordinates("c_test_01", 0, 300)
        assert exc.value.code == "coordinate_out_of_bounds"

        # negative x
        with pytest.raises(LCUError) as exc:
            resolve_capture_coordinates("c_test_01", -1, 0)
        assert exc.value.code == "coordinate_out_of_bounds"

        # negative y
        with pytest.raises(LCUError) as exc:
            resolve_capture_coordinates("c_test_01", 0, -1)
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


def test_capture_cache_pruning(tmp_path: Path) -> None:
    # Create 55 dummy capture entries and files
    now = time.time()
    index: dict[str, CaptureMetadata] = {}
    file_paths: list[Path] = []
    for i in range(55):
        f = tmp_path / f"img_{i}.webp"
        f.write_text(f"dummy content {i}")
        file_paths.append(f)
        cid = f"c_{i:04d}"
        index[cid] = CaptureMetadata(
            captureId=cid,
            source="screen",
            hwnd=None,
            window_title=None,
            window_bounds=None,
            source_bounds={"x": 0, "y": 0, "width": 100, "height": 100},
            crop_bounds=None,
            source_width=100,
            source_height=100,
            returned_width=100,
            returned_height=100,
            scale_x=1.0,
            scale_y=1.0,
            timestamp=now - (55 - i) * 10,  # oldest first
            dpi_mode="Per-Monitor-V2",
            path=str(f),
        )

    pruned = _prune_capture_cache(index)
    assert len(pruned) == MAX_CAPTURES_IN_CACHE  # 50
    # The 5 oldest items (0..4) must be removed
    for i in range(5):
        cid = f"c_{i:04d}"
        assert cid not in pruned
        assert not file_paths[i].exists()  # file unlinked from disk

    # The 50 newest items (5..54) must be kept
    for i in range(5, 55):
        cid = f"c_{i:04d}"
        assert cid in pruned
        assert file_paths[i].exists()


def test_screen_region_negative_virtual_desktop(tmp_path: Path) -> None:
    # Multi-monitor setup where secondary monitor is to the left:
    # Left = -1920, Top = 0, Width = 3840, Height = 1080
    mock_metrics = {76: -1920, 77: 0, 78: 3840, 79: 1080}
    dummy_img = Image.new("RGB", (300, 200), color="white")

    with patch("win32api.GetSystemMetrics", side_effect=lambda idx: mock_metrics[idx]), patch(
        "PIL.ImageGrab.grab", return_value=dummy_img
    ):
        # Request region at virtual image coordinate (100, 50, 300, 200)
        # Virtual image (0, 0) is at physical (-1920, 0)
        # So physical source box is (-1920 + 100, 0 + 50) = (-1820, 50)
        res = capture_screenshot(
            target="screen",
            region=(100, 50, 300, 200),
            quality="detail",
            output_path=tmp_path / "neg_screen.webp",
        )
        cid = res["captureId"]
        meta = get_capture_metadata(cid)
        assert meta.source_bounds["x"] == -1820
        assert meta.source_bounds["y"] == 50

        # Resolving coordinate (10, 20) inside the captured region:
        # Physical = -1820 + 10 = -1810, 50 + 20 = 70
        phys_x, phys_y = resolve_capture_coordinates(cid, 10, 20)
        assert phys_x == -1810
        assert phys_y == 70

        # Region out of virtual screen bounds
        with pytest.raises(LCUError) as exc:
            capture_screenshot(target="screen", region=(3800, 0, 100, 100))
        assert exc.value.code == "coordinate_out_of_bounds"
