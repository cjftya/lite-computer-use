from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from scripts.lcu import capture, direct, batch
from scripts.lcu.errors import LCUError

CLI = Path(__file__).resolve().parents[1] / "scripts" / "lcu.py"


@pytest.fixture
def cache(tmp_path, monkeypatch):
    folder = tmp_path / "captures"
    folder.mkdir()
    index = tmp_path / "index.json"
    monkeypatch.setattr(capture, "get_capture_dir", lambda: folder)
    monkeypatch.setattr(capture, "get_capture_index_path", lambda: index)
    monkeypatch.setattr(capture, "init_windows_environment", lambda: None)
    return folder, index


def metadata(path, cid="c_12345678", age=0, owned=False):
    meta = capture.CaptureMetadata(cid, "screen", None, None, None,
        {"x": 10, "y": 20, "width": 100, "height": 80}, None,
        100, 80, 50, 40, .5, .5, time.time() - age, "Per-Monitor-V2", str(path))
    meta.cache_owned = owned
    return meta


@pytest.mark.parametrize("overflow", [False, True])
@pytest.mark.parametrize("inside", [False, True])
def test_user_output_preserved(cache, tmp_path, overflow, inside):
    folder, _ = cache
    output = (folder if inside else tmp_path) / "user.webp"
    output.write_text("new user image")
    old = metadata(output, age=100 if overflow else 90000)
    entries = {old.captureId: old}
    if overflow:
        for i in range(50):
            cid = f"c_{i:08x}"
            entries[cid] = metadata(folder / f"{cid}.webp", cid)
    capture._save_capture_index(entries)
    assert output.read_text() == "new user image"
    assert old.captureId not in capture._load_capture_index()


@pytest.mark.parametrize("overflow", [False, True])
def test_owned_capture_pruned(cache, overflow):
    folder, _ = cache
    old_path = folder / "c_ffffffff.webp"
    old_path.write_text("old")
    old = metadata(old_path, "c_ffffffff", 100 if overflow else 90000, True)
    entries = {old.captureId: old}
    if overflow:
        for i in range(50):
            cid = f"c_{i:08x}"
            entries[cid] = metadata(folder / f"{cid}.webp", cid, owned=True)
    capture._save_capture_index(entries)
    assert not old_path.exists()
    assert old.captureId not in capture._load_capture_index()


def test_legacy_external_and_malformed_entries(cache, tmp_path):
    _, index = cache
    outside = tmp_path / "c_12345678.webp"
    outside.write_text("keep")
    legacy = metadata(outside, age=90000).to_dict()
    legacy.pop("cache_owned", None)
    index.write_text(json.dumps({"legacy": legacy, "bad": {"path": "bad"}}))
    loaded = capture._load_capture_index()
    assert "legacy" in loaded
    capture._save_capture_index(loaded)
    assert outside.exists()
    external = metadata(outside, age=90000, owned=True)
    capture._save_capture_index({external.captureId: external})
    assert outside.exists()


def test_shared_output_protects_old_owned_path(cache):
    folder, _ = cache
    output = folder / "c_12345678.webp"
    output.write_text("new user output")
    old = metadata(output, age=90000, owned=True)
    new = metadata(output, "c_87654321")
    capture._save_capture_index({old.captureId: old, new.captureId: new})
    assert output.read_text() == "new user output"


@pytest.mark.parametrize("stage", ["write", "replace"])
def test_atomic_save_failure(cache, monkeypatch, stage):
    folder, index = cache
    old_path = folder / "c_12345678.webp"
    old_path.write_text("old")
    old = metadata(old_path, age=90000, owned=True)
    original = json.dumps({old.captureId: old.to_dict()})
    index.write_text(original)
    if stage == "write":
        monkeypatch.setattr(capture.json, "dump", Mock(side_effect=OSError("write failed")))
    else:
        monkeypatch.setattr(capture.os, "replace", Mock(side_effect=OSError("replace failed")))
    with pytest.raises(LCUError) as exc:
        capture._save_capture_index({old.captureId: old})
    assert exc.value.code == "capture_index_save_failed"
    assert index.read_text() == original
    assert old_path.exists()
    assert sorted(p.name for p in index.parent.iterdir()) == ["captures", "index.json"]


@pytest.mark.parametrize("explicit", [False, True])
def test_screenshot_save_failure(cache, tmp_path, monkeypatch, explicit):
    folder, index = cache
    old_path = folder / "c_ffffffff.webp"
    old_path.write_text("old cache image")
    old = metadata(old_path, "c_ffffffff", age=90000, owned=True)
    original = json.dumps({old.captureId: old.to_dict()})
    index.write_text(original)
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(GetSystemMetrics=lambda n: {76: 0, 77: 0, 78: 100, 79: 80}[n]))
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace())
    monkeypatch.setattr(capture.ImageGrab, "grab", lambda **kw: Image.new("RGB", (100, 80)))
    monkeypatch.setattr(capture.os, "replace", Mock(side_effect=OSError("replace failed")))
    output = tmp_path / "user.webp" if explicit else None
    with pytest.raises(LCUError) as exc:
        capture.capture_screenshot(target="screen", output_path=output)
    assert exc.value.code == "capture_index_save_failed"
    assert index.read_text() == original
    assert list(folder.iterdir()) == [old_path]
    assert old_path.read_text() == "old cache image"
    if explicit:
        assert output.exists()


def test_atomic_roundtrip_coordinates(cache):
    folder, _ = cache
    meta = metadata(folder / "c_12345678.webp", owned=True)
    capture._save_capture_index({meta.captureId: meta})
    assert capture.get_capture_metadata(meta.captureId).to_dict() == meta.to_dict()
    assert capture.resolve_capture_coordinates(meta.captureId, 5, 6) == (20, 32)


@pytest.mark.parametrize("args", [["click", "10"], ["unknown_command"], ["click", "bad", "20"],
    ["click", "10", "20", "--button", "bad"], [], ["click", "10", "20", "--unknown"]])
def test_cli_parse_error(args):
    proc = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True)
    assert proc.returncode == 2
    data = json.loads(proc.stdout)
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_arguments"
    assert data["action"] == ("click" if args and args[0] == "click" else "unknown")


@pytest.mark.parametrize("args", [["--help"], ["click", "--help"]])
def test_cli_help(args):
    proc = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "usage:" in proc.stdout
    assert '"ok"' not in proc.stdout


def test_cli_parse_does_not_dispatch(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("defect_cli", CLI)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    dispatch = Mock(side_effect=AssertionError("dispatch reached"))
    monkeypatch.setattr(cli.windows, "click", dispatch)
    monkeypatch.setattr(sys, "argv", [str(CLI), "click", "10"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_arguments"
    dispatch.assert_not_called()


def test_runtime_and_batch_cli_errors():
    for args in [["open_url", "ftp://invalid.example"], ["batch", '[{"action":"open_url","url":"ftp://invalid.example"}]']]:
        proc = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True)
        assert proc.returncode == 1
        assert json.loads(proc.stdout)["error"]["code"] == "invalid_arguments"


@pytest.mark.parametrize("primary,fallback", [(True, True), (False, True), (False, False), (False, OSError("fallback failed"))])
def test_open_url_dispatch(monkeypatch, primary, fallback):
    import webbrowser
    start = Mock(side_effect=None if primary else OSError("primary failed"))
    browser = Mock(return_value=fallback, side_effect=fallback if isinstance(fallback, Exception) else None)
    monkeypatch.setattr(direct.os, "startfile", start, raising=False)
    monkeypatch.setattr(webbrowser, "open", browser)
    if not primary and (fallback is False or isinstance(fallback, Exception)):
        with pytest.raises(LCUError) as exc:
            direct.open_url(" https://example.com ")
        assert exc.value.code == "dispatch_failed"
    else:
        assert direct.open_url(" https://example.com ") == {"url": "https://example.com"}
    assert browser.call_count == (0 if primary else 1)
    start.assert_called_once_with("https://example.com")


def test_url_batch_stops_on_failure(monkeypatch):
    import webbrowser
    monkeypatch.setattr(direct.os, "startfile", Mock(side_effect=OSError("failed")), raising=False)
    monkeypatch.setattr(webbrowser, "open", Mock(return_value=False))
    clip = Mock()
    monkeypatch.setattr(batch.windows, "set_clipboard", clip)
    result = batch.execute_batch([{"action": "set_clipboard", "text": "first"},
        {"action": "open_url", "url": "https://example.com"},
        {"action": "set_clipboard", "text": "last"}])
    assert result["ok"] is False
    assert result["error"]["code"] == "dispatch_failed"
    assert result["result"]["completed"] == 1
    assert result["result"]["failedIndex"] == 1
    clip.assert_called_once_with(text="first")


@pytest.mark.parametrize("redirect", ["symlink", "ancestor"])
def test_redirected_owned_path_preserved(cache, monkeypatch, redirect):
    folder, _ = cache
    path = folder / "c_12345678.webp"
    path.write_text("preserve")
    meta = metadata(path, age=90000, owned=True)
    if redirect == "symlink":
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda p: p == path or original(p))
    else:
        original = Path.resolve
        monkeypatch.setattr(Path, "resolve", lambda p, *a, **kw: folder.parent / "redirected" if p == folder else original(p, *a, **kw))
    capture._save_capture_index({meta.captureId: meta})
    assert path.exists()


@pytest.mark.parametrize("explicit", [False, True])
def test_screenshot_records_ownership(cache, tmp_path, monkeypatch, explicit):
    folder, _ = cache
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(GetSystemMetrics=lambda n: {76: 0, 77: 0, 78: 100, 79: 80}[n]))
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace())
    monkeypatch.setattr(capture.ImageGrab, "grab", lambda **kw: Image.new("RGB", (100, 80)))
    output = folder / "user.webp" if explicit else None
    result = capture.capture_screenshot(target="screen", output_path=output)
    meta = capture.get_capture_metadata(result["captureId"])
    assert meta.cache_owned is (not explicit)
    meta.timestamp -= 90000
    capture._save_capture_index({meta.captureId: meta})
    assert Path(result["path"]).exists() is explicit
