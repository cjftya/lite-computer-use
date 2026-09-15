from __future__ import annotations

import ctypes
import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageGrab

from .errors import LCUError

# Enable DPI awareness and desktop attachment
_INITIALIZED = False


def init_windows_environment() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    if os.name != "nt":
        return

    # 1. Enable Per-Monitor DPI Awareness V2
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    # 2. Attach thread to default desktop
    try:
        import win32con
        import win32service

        hdesk = win32service.OpenDesktop("default", 0, False, win32con.GENERIC_ALL)
        if hdesk:
            ctypes.windll.user32.SetThreadDesktop(int(hdesk))
    except Exception:
        pass


def get_capture_dir() -> Path:
    base = Path(tempfile.gettempdir()) / "LiteComputerUse" / "captures"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_capture_index_path() -> Path:
    base = Path(tempfile.gettempdir()) / "LiteComputerUse"
    base.mkdir(parents=True, exist_ok=True)
    return base / "capture-index.json"


@dataclass
class CaptureMetadata:
    captureId: str
    source: str  # "active-window", "screen", "window"
    hwnd: int | None
    window_title: str | None
    window_bounds: dict[str, int] | None  # {"x", "y", "width", "height"}
    source_bounds: dict[str, int]  # Physical screen box captured: {"x", "y", "width", "height"}
    crop_bounds: dict[str, int] | None  # Region if specified
    source_width: int
    source_height: int
    returned_width: int
    returned_height: int
    scale_x: float
    scale_y: float
    timestamp: float
    dpi_mode: str
    path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CaptureMetadata:
        return cls(**d)


def _load_capture_index() -> dict[str, CaptureMetadata]:
    path = get_capture_index_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: CaptureMetadata.from_dict(v) for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        return {}


def _save_capture_index(index: dict[str, CaptureMetadata]) -> None:
    path = get_capture_index_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({k: v.to_dict() for k, v in index.items()}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_capture_metadata(capture_id: str) -> CaptureMetadata:
    index = _load_capture_index()
    if capture_id not in index:
        raise LCUError("capture_not_found", f"Capture ID '{capture_id}' was not found in cache")
    return index[capture_id]


def resolve_capture_coordinates(capture_id: str, image_x: int, image_y: int) -> tuple[int, int]:
    meta = get_capture_metadata(capture_id)
    init_windows_environment()

    # Verify stale capture
    if meta.hwnd is not None:
        import win32gui

        if not win32gui.IsWindow(meta.hwnd):
            raise LCUError("stale_capture", f"Window (hwnd {meta.hwnd}) associated with capture has been closed")

        if meta.source == "active-window":
            fg = win32gui.GetForegroundWindow()
            if fg != meta.hwnd:
                raise LCUError(
                    "stale_capture",
                    f"Active window has lost focus since capture (expected hwnd {meta.hwnd}, current fg is {fg})",
                )

        # Check bounds change
        rect = win32gui.GetWindowRect(meta.hwnd)
        curr_bounds = {
            "x": rect[0],
            "y": rect[1],
            "width": max(0, rect[2] - rect[0]),
            "height": max(0, rect[3] - rect[1]),
        }
        if meta.window_bounds is not None:
            if (
                curr_bounds["x"] != meta.window_bounds["x"]
                or curr_bounds["y"] != meta.window_bounds["y"]
                or curr_bounds["width"] != meta.window_bounds["width"]
                or curr_bounds["height"] != meta.window_bounds["height"]
            ):
                raise LCUError(
                    "stale_capture",
                    f"Window moved or resized since capture: current {curr_bounds} != captured {meta.window_bounds}",
                )

    # Check bounds in image
    if not (0 <= image_x <= meta.returned_width and 0 <= image_y <= meta.returned_height):
        raise LCUError(
            "coordinate_out_of_bounds",
            f"Coordinate ({image_x}, {image_y}) is outside capture image bounds (0..{meta.returned_width}, 0..{meta.returned_height})",
        )

    # Inverse scale mapping
    phys_crop_x = image_x / meta.scale_x
    phys_crop_y = image_y / meta.scale_y

    # Screen coordinates
    screen_x = int(round(meta.source_bounds["x"] + phys_crop_x))
    screen_y = int(round(meta.source_bounds["y"] + phys_crop_y))

    return screen_x, screen_y


def capture_screenshot(
    target: str = "active-window",
    hwnd: int | None = None,
    region: list[int] | tuple[int, int, int, int] | None = None,
    quality: str = "normal",
    from_capture: str | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    init_windows_environment()

    if quality not in ("fast", "normal", "detail"):
        raise LCUError("invalid_arguments", f"Invalid quality preset: '{quality}'. Must be fast, normal, or detail.")

    if from_capture is not None:
        # Partial re-capture from an existing capture
        parent_meta = get_capture_metadata(from_capture)

        # Stale capture check on parent
        if parent_meta.hwnd is not None:
            import win32gui

            if not win32gui.IsWindow(parent_meta.hwnd):
                raise LCUError("stale_capture", "Window associated with previous capture has closed")
            if parent_meta.source == "active-window":
                if win32gui.GetForegroundWindow() != parent_meta.hwnd:
                    raise LCUError("stale_capture", "Active window has lost focus since previous capture")
            rect = win32gui.GetWindowRect(parent_meta.hwnd)
            curr_bounds = {
                "x": rect[0],
                "y": rect[1],
                "width": max(0, rect[2] - rect[0]),
                "height": max(0, rect[3] - rect[1]),
            }
            if parent_meta.window_bounds and curr_bounds != parent_meta.window_bounds:
                raise LCUError("stale_capture", "Window moved or resized since previous capture")

        if region is None:
            raise LCUError("invalid_arguments", "Region is required when capturing --from-capture")

        rx, ry, rw, rh = region
        if rw <= 0 or rh <= 0:
            raise LCUError("invalid_arguments", f"Region width and height must be positive: ({rw}, {rh})")

        # Check region within parent image
        if not (
            0 <= rx < parent_meta.returned_width
            and 0 <= ry < parent_meta.returned_height
            and rx + rw <= parent_meta.returned_width
            and ry + rh <= parent_meta.returned_height
        ):
            raise LCUError(
                "coordinate_out_of_bounds",
                f"Region ({rx}, {ry}, {rw}, {rh}) is outside parent image bounds ({parent_meta.returned_width}x{parent_meta.returned_height})",
            )

        # Convert parent image region to physical screen coordinates
        source_x = int(round(parent_meta.source_bounds["x"] + (rx / parent_meta.scale_x)))
        source_y = int(round(parent_meta.source_bounds["y"] + (ry / parent_meta.scale_y)))
        source_w = int(round(rw / parent_meta.scale_x))
        source_h = int(round(rh / parent_meta.scale_y))

        target_type = parent_meta.source
        target_hwnd = parent_meta.hwnd
        window_title = parent_meta.window_title
        window_bounds = parent_meta.window_bounds
        crop_bounds = {"x": rx, "y": ry, "width": rw, "height": rh}

    else:
        # Standard capture: active-window, screen, or window
        import win32api
        import win32gui

        window_title: str | None = None
        window_bounds: dict[str, int] | None = None
        target_hwnd: int | None = None

        if target == "screen":
            target_type = "screen"
            screen_x = win32api.GetSystemMetrics(76)
            screen_y = win32api.GetSystemMetrics(77)
            screen_w = win32api.GetSystemMetrics(78)
            screen_h = win32api.GetSystemMetrics(79)

            if region is not None:
                rx, ry, rw, rh = region
                if rw <= 0 or rh <= 0:
                    raise LCUError("invalid_arguments", f"Region width and height must be positive: ({rw}, {rh})")
                source_x = rx
                source_y = ry
                source_w = rw
                source_h = rh
                crop_bounds = {"x": rx, "y": ry, "width": rw, "height": rh}
            else:
                source_x = screen_x
                source_y = screen_y
                source_w = screen_w
                source_h = screen_h
                crop_bounds = None

        elif target in ("active-window", "window"):
            target_type = target
            if target == "window":
                if hwnd is None:
                    raise LCUError("invalid_arguments", "Window target requires --hwnd")
                target_hwnd = hwnd
                if not win32gui.IsWindow(target_hwnd):
                    raise LCUError("window_not_found", f"Window with hwnd {target_hwnd} not found")
            else:
                target_hwnd = win32gui.GetForegroundWindow()
                if not target_hwnd or not win32gui.IsWindow(target_hwnd):
                    raise LCUError("no_active_window", "No active foreground window found")

            if win32gui.IsIconic(target_hwnd):
                raise LCUError("window_not_foreground", "Target window is minimized")

            window_title = win32gui.GetWindowText(target_hwnd)
            rect = win32gui.GetWindowRect(target_hwnd)
            win_l, win_t, win_r, win_b = rect
            win_w = max(0, win_r - win_l)
            win_h = max(0, win_b - win_t)
            if win_w <= 0 or win_h <= 0:
                raise LCUError("invalid_arguments", f"Window has invalid bounds: {rect}")

            window_bounds = {"x": win_l, "y": win_t, "width": win_w, "height": win_h}

            if region is not None:
                rx, ry, rw, rh = region
                if rw <= 0 or rh <= 0:
                    raise LCUError("invalid_arguments", f"Region width and height must be positive: ({rw}, {rh})")
                # Region is relative to the target window
                source_x = win_l + rx
                source_y = win_t + ry
                source_w = rw
                source_h = rh
                crop_bounds = {"x": rx, "y": ry, "width": rw, "height": rh}
            else:
                source_x = win_l
                source_y = win_t
                source_w = win_w
                source_h = win_h
                crop_bounds = None
        else:
            raise LCUError("invalid_arguments", f"Unknown target: '{target}'. Must be active-window, screen, or window.")

    # Grab the physical screen pixels
    bbox = (source_x, source_y, source_x + source_w, source_y + source_h)
    try:
        raw_img = ImageGrab.grab(bbox=bbox, all_screens=True)
    except Exception as exc:
        raise LCUError("dispatch_failed", f"Screen capture failed: {exc}") from exc

    # Resize according to quality preset
    orig_w, orig_h = raw_img.size
    final_img = raw_img

    if quality == "fast":
        max_dim = 1024
        if max(orig_w, orig_h) > max_dim:
            scale = max_dim / float(max(orig_w, orig_h))
            new_w = max(1, int(round(orig_w * scale)))
            new_h = max(1, int(round(orig_h * scale)))
            final_img = raw_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    elif quality == "normal":
        max_dim = 1600
        if max(orig_w, orig_h) > max_dim:
            scale = max_dim / float(max(orig_w, orig_h))
            new_w = max(1, int(round(orig_w * scale)))
            new_h = max(1, int(round(orig_h * scale)))
            final_img = raw_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    elif quality == "detail":
        # Keep 1.0 original resolution
        pass

    final_w, final_h = final_img.size
    scale_x = final_w / float(source_w) if source_w > 0 else 1.0
    scale_y = final_h / float(source_h) if source_h > 0 else 1.0

    # Save image
    cid = f"c_{uuid.uuid4().hex[:8]}"
    ext = "webp"
    if output_path is not None:
        save_file = output_path
    else:
        save_file = get_capture_dir() / f"{cid}.{ext}"

    if quality == "detail":
        # Lossless webp
        final_img.save(save_file, format="WEBP", lossless=True)
    elif quality == "fast":
        final_img.save(save_file, format="WEBP", quality=70)
    else:  # normal
        final_img.save(save_file, format="WEBP", quality=82)

    # Store metadata
    metadata = CaptureMetadata(
        captureId=cid,
        source=target_type,
        hwnd=target_hwnd,
        window_title=window_title,
        window_bounds=window_bounds,
        source_bounds={"x": source_x, "y": source_y, "width": source_w, "height": source_h},
        crop_bounds=crop_bounds,
        source_width=source_w,
        source_height=source_h,
        returned_width=final_w,
        returned_height=final_h,
        scale_x=scale_x,
        scale_y=scale_y,
        timestamp=time.time(),
        dpi_mode="Per-Monitor-V2",
        path=str(save_file.resolve()),
    )

    index = _load_capture_index()
    index[cid] = metadata
    _save_capture_index(index)

    return {
        "captureId": cid,
        "path": str(save_file.resolve()),
        "width": final_w,
        "height": final_h,
    }
