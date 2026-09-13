from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from app_index import AppIndex, IndexedApp
from helpers import AppDefinition, AppRegistry, LCUError
from lcu_tools import launch_app_resilient, resolve_app


class AppIndexTests(unittest.TestCase):
    def test_discovers_start_menu_and_app_paths_without_exposing_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Programs"
            root.mkdir()
            (root / "Visual Studio Code.lnk").touch()
            app_paths = [
                IndexedApp(
                    name="Discord",
                    normalized="discord",
                    source="app-paths",
                    target=r"C:\Apps\Discord.exe",
                    process="discord.exe",
                )
            ]

            index = AppIndex(AppIndex.discover([root], app_paths))

        self.assertEqual("Discord", index.resolve("discord").name)
        self.assertEqual("Visual Studio Code", index.resolve("visual studio").name)
        serialized = json.dumps(index.public_apps())
        self.assertNotIn(r"C:\Apps", serialized)
        self.assertNotIn("target", serialized)

    def test_cache_is_reused_for_24_hours_and_refresh_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "apps.json"
            first = [
                IndexedApp("First", "first", "app-paths", "first.exe", "first.exe")
            ]
            second = [
                IndexedApp(
                    "Second", "second", "app-paths", "second.exe", "second.exe"
                )
            ]
            initial = AppIndex.load(
                cache_path=cache,
                start_menu_roots=[],
                app_path_entries=first,
                now=1_000.0,
            )
            cached = AppIndex.load(
                cache_path=cache,
                start_menu_roots=[],
                app_path_entries=second,
                now=1_001.0,
            )
            refreshed = AppIndex.load(
                refresh=True,
                cache_path=cache,
                start_menu_roots=[],
                app_path_entries=second,
                now=1_002.0,
            )

        self.assertTrue(initial.refreshed)
        self.assertFalse(cached.refreshed)
        self.assertEqual("First", cached.apps[0].name)
        self.assertTrue(refreshed.refreshed)
        self.assertEqual("Second", refreshed.apps[0].name)

    def test_stale_or_invalid_cache_is_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "apps.json"
            cache.write_text("not json", encoding="utf-8")
            apps = [IndexedApp("Paint", "paint", "app-paths", "paint.exe")]
            invalid = AppIndex.load(
                cache_path=cache,
                start_menu_roots=[],
                app_path_entries=apps,
                now=100.0,
            )
            stale = AppIndex.load(
                cache_path=cache,
                start_menu_roots=[],
                app_path_entries=[],
                now=100.0 + 86_401,
            )

        self.assertTrue(invalid.refreshed)
        self.assertTrue(stale.refreshed)
        self.assertEqual((), stale.apps)

    def test_partial_match_must_be_unique(self) -> None:
        index = AppIndex(
            [
                IndexedApp("Visual Studio", "visual studio", "app-paths", "vs.exe"),
                IndexedApp(
                    "Visual Studio Code",
                    "visual studio code",
                    "app-paths",
                    "code.exe",
                ),
            ]
        )
        with self.assertRaises(LCUError) as context:
            index.resolve("visual")
        self.assertEqual("ambiguous_app", context.exception.code)
        self.assertNotIn("target", json.dumps(context.exception.details))

    def test_configured_registry_alias_has_priority_over_index(self) -> None:
        configured = AppDefinition("configured", ("same",), ("configured.exe",))
        registry = AppRegistry([configured])
        index = Mock()

        result = resolve_app(registry, "same", index)

        self.assertIs(configured, result)
        index.resolve.assert_not_called()

    def test_cache_write_failure_does_not_discard_discovery(self) -> None:
        app = IndexedApp("Paint", "paint", "app-paths", "paint.exe")
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            AppIndex, "_write_cache", side_effect=OSError("locked")
        ):
            index = AppIndex.load(
                cache_path=Path(temp_dir) / "apps.json",
                start_menu_roots=[],
                app_path_entries=[app],
            )
        self.assertEqual("Paint", index.apps[0].name)

    def test_configured_not_found_falls_back_to_same_indexed_app_once(self) -> None:
        configured = AppDefinition("chrome", ("크롬",), ("chrome.exe",))
        registry = AppRegistry([configured])
        index = AppIndex(
            [
                IndexedApp(
                    "Google Chrome",
                    "google chrome",
                    "app-paths",
                    r"C:\Apps\chrome.exe",
                    "chrome.exe",
                )
            ]
        )
        backend = Mock()
        backend.launch_app.side_effect = [
            LCUError("app_launch_failed", "missing", notFoundOnly=True),
            {"name": "Google Chrome", "source": "app-paths"},
        ]
        with patch.object(AppIndex, "load", return_value=index) as load:
            result = launch_app_resilient(backend, registry, "크롬")
        self.assertEqual("registry-not-found", result["fallbackFrom"])
        self.assertEqual(2, backend.launch_app.call_count)
        load.assert_called_once_with()

    def test_access_denial_never_fans_out_to_index(self) -> None:
        registry = AppRegistry(
            [AppDefinition("chrome", ("크롬",), ("chrome.exe",))]
        )
        backend = Mock()
        backend.launch_app.side_effect = LCUError(
            "app_launch_failed", "denied", notFoundOnly=False
        )
        with patch.object(AppIndex, "load") as load, self.assertRaises(LCUError):
            launch_app_resilient(backend, registry, "크롬")
        load.assert_not_called()

    def test_resolve_any_maps_localized_alias_to_process(self) -> None:
        index = AppIndex(
            [
                IndexedApp(
                    "Google Chrome",
                    "google chrome",
                    "app-paths",
                    r"C:\Apps\chrome.exe",
                    "chrome.exe",
                )
            ]
        )
        app = index.resolve_any({"크롬", "chrome", "chrome.exe"})
        self.assertEqual("Google Chrome", app.name)

    def test_stale_indexed_target_refreshes_at_most_once(self) -> None:
        registry = AppRegistry(
            [AppDefinition("chrome", ("크롬",), ("chrome.exe",))]
        )
        stale = AppIndex(
            [IndexedApp("Discord", "discord", "start-menu", "old.lnk")],
            refreshed=False,
        )
        fresh = AppIndex(
            [IndexedApp("Discord", "discord", "start-menu", "new.lnk")],
            refreshed=True,
        )
        backend = Mock()
        backend.launch_app.side_effect = [
            LCUError("app_launch_failed", "missing", notFoundOnly=True),
            {"name": "Discord", "source": "start-menu"},
        ]
        with patch.object(AppIndex, "load", side_effect=[stale, fresh]) as load:
            result = launch_app_resilient(backend, registry, "Discord")
        self.assertEqual("Discord", result["name"])
        self.assertEqual([unittest.mock.call(), unittest.mock.call(refresh=True)], load.call_args_list)


if __name__ == "__main__":
    unittest.main()
