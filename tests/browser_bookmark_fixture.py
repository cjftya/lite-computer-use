from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path

# Add scripts directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Attach thread to default desktop for Win32 enumeration
if sys.platform == "win32":
    try:
        import ctypes
        import win32con
        import win32service

        hdesk = win32service.OpenDesktop("default", 0, False, win32con.GENERIC_ALL)
        if hdesk:
            ctypes.windll.user32.SetThreadDesktop(int(hdesk))
    except Exception:
        pass

STATUS_FILE = Path(tempfile.gettempdir()) / "LiteComputerUse" / "bookmark_status.json"


class BrowserBookmarkApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("LCU Browser - Bookmarks & Menu")
        self.root.geometry("700x520")
        self.root.configure(bg="#f8fafc")

        self.status = {
            "current_url": "https://en.wikipedia.org",
            "bookmark_added": False,
            "navigated_away": False,
            "bookmark_opened": False,
            "bookmark_deleted": False,
        }
        self.bookmarks: list[dict[str, str]] = []
        self._write_status()

        self._build_ui()
        self.root.deiconify()
        self.root.update()

    def _write_status(self) -> None:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.status, f, ensure_ascii=False)

    def _build_ui(self) -> None:
        # Browser Top Bar
        top_bar = tk.Frame(self.root, bg="#e2e8f0", height=45, bd=1, relief="solid")
        top_bar.pack(fill="x", side="top")

        lbl_addr = tk.Label(top_bar, text="URL:", bg="#e2e8f0", font=("Segoe UI", 9, "bold"))
        lbl_addr.pack(side="left", padx=(10, 4), pady=8)

        self.ent_url = tk.Entry(top_bar, font=("Segoe UI", 9), bd=1, relief="solid")
        self.ent_url.insert(0, "https://en.wikipedia.org")
        self.ent_url.pack(side="left", fill="x", expand=True, padx=4, pady=8)
        self.ent_url.bind("<Return>", lambda e: self.on_navigate())

        self.btn_star = tk.Button(
            top_bar,
            text="★ 북마크 추가",
            font=("Segoe UI", 9, "bold"),
            bg="#fef3c7",
            fg="#b45309",
            bd=1,
            cursor="hand2",
            command=self.add_bookmark,
        )
        self.btn_star.pack(side="left", padx=5, pady=6)

        self.btn_menu = tk.Button(
            top_bar,
            text="☰ 메뉴",
            font=("Segoe UI", 9, "bold"),
            bg="#ffffff",
            fg="#1e293b",
            bd=1,
            cursor="hand2",
            command=self.toggle_menu,
        )
        self.btn_menu.pack(side="right", padx=10, pady=6)

        # Page Container
        self.page_frame = tk.Frame(self.root, bg="#ffffff", bd=1, relief="solid")
        self.page_frame.pack(fill="both", expand=True, padx=15, pady=15)

        self.menu_panel = None
        self._render_page("https://en.wikipedia.org")

    def _render_page(self, url: str) -> None:
        for w in self.page_frame.winfo_children():
            w.destroy()

        self.status["current_url"] = url
        self._write_status()
        self.ent_url.delete(0, "end")
        self.ent_url.insert(0, url)

        if "wikipedia" in url.lower():
            # Wikipedia Page
            title = tk.Label(self.page_frame, text="Wikipedia: The Free Encyclopedia", font=("Georgia", 18, "bold"), bg="#ffffff", fg="#111827")
            title.pack(anchor="w", padx=25, pady=(25, 8))

            subtitle = tk.Label(self.page_frame, text="From Wikipedia, the free knowledge repository", font=("Georgia", 11, "italic"), bg="#ffffff", fg="#4b5563")
            subtitle.pack(anchor="w", padx=25, pady=(0, 20))

            body = tk.Label(
                self.page_frame,
                text="Welcome to Wikipedia, where millions of volunteer editors collaborate to build human knowledge across languages.",
                font=("Segoe UI", 10),
                bg="#ffffff",
                fg="#374151",
                wraplength=620,
                justify="left",
            )
            body.pack(anchor="w", padx=25)

        else:
            # Other Page (e.g. Hacker News / Search)
            title = tk.Label(self.page_frame, text="Hacker News Portal", font=("Segoe UI", 16, "bold"), bg="#ffffff", fg="#ff6600")
            title.pack(anchor="w", padx=25, pady=(25, 8))

            body = tk.Label(
                self.page_frame,
                text="1. Show HN: Lite Computer Use v2 - Production Agent Architecture\n2. Ask HN: Favorite Win32 GUI patterns in 2026?\n3. High-throughput Vision Automation benchmarks",
                font=("Segoe UI", 10),
                bg="#ffffff",
                fg="#1f2937",
                justify="left",
            )
            body.pack(anchor="w", padx=25, pady=(10, 0))

    def add_bookmark(self) -> None:
        title = "Wikipedia: The Free Encyclopedia" if "wikipedia" in self.status["current_url"] else "Other Page"
        bm = {"title": title, "url": self.status["current_url"]}
        if not any(b["url"] == bm["url"] for b in self.bookmarks):
            self.bookmarks.append(bm)
        self.status["bookmark_added"] = True
        self._write_status()
        self.btn_star.configure(text="★ 북마크됨", bg="#fde68a")

    def on_navigate(self) -> None:
        url = self.ent_url.get().strip()
        self.status["navigated_away"] = True
        self._render_page(url)

    def toggle_menu(self) -> None:
        if self.menu_panel is not None:
            self.menu_panel.destroy()
            self.menu_panel = None
            return

        self.menu_panel = tk.Frame(self.root, bg="#f8fafc", bd=2, relief="groove")
        self.menu_panel.place(x=480, y=45, width=210, height=260)

        header = tk.Label(self.menu_panel, text="브라우저 메뉴", font=("Segoe UI", 10, "bold"), bg="#f8fafc", fg="#0f172a")
        header.pack(anchor="w", padx=10, pady=(8, 4))

        # Bookmark section inside menu
        lbl_bm_title = tk.Label(self.menu_panel, text="저장된 북마크:", font=("Segoe UI", 9, "bold"), bg="#f8fafc", fg="#334155")
        lbl_bm_title.pack(anchor="w", padx=10, pady=(4, 2))

        self.bm_list_frame = tk.Frame(self.menu_panel, bg="#ffffff", bd=1, relief="solid")
        self.bm_list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._render_bookmarks_list()

    def _render_bookmarks_list(self) -> None:
        for w in self.bm_list_frame.winfo_children():
            w.destroy()

        if not self.bookmarks:
            lbl_empty = tk.Label(self.bm_list_frame, text="북마크 없음", font=("Segoe UI", 8), fg="#94a3b8", bg="#ffffff")
            lbl_empty.pack(pady=20)
            return

        for idx, bm in enumerate(self.bookmarks):
            item = tk.Frame(self.bm_list_frame, bg="#ffffff", pady=4, padx=6)
            item.pack(fill="x", side="top")

            lbl_title = tk.Label(item, text=bm["title"][:16], font=("Segoe UI", 8, "bold"), bg="#ffffff", fg="#1d4ed8")
            lbl_title.pack(anchor="w")

            btn_box = tk.Frame(item, bg="#ffffff")
            btn_box.pack(fill="x", pady=2)

            btn_open = tk.Button(
                btn_box,
                text="열기",
                font=("Segoe UI", 8, "bold"),
                bg="#2563eb",
                fg="white",
                bd=0,
                padx=6,
                command=lambda b=bm: self.open_bookmark(b),
            )
            btn_open.pack(side="left", padx=(0, 4))

            btn_del = tk.Button(
                btn_box,
                text="삭제",
                font=("Segoe UI", 8),
                bg="#fee2e2",
                fg="#dc2626",
                bd=0,
                padx=6,
                command=lambda i=idx: self.delete_bookmark(i),
            )
            btn_del.pack(side="left")

    def open_bookmark(self, bm: dict[str, str]) -> None:
        self.status["bookmark_opened"] = True
        self._render_page(bm["url"])
        if self.menu_panel:
            self.menu_panel.destroy()
            self.menu_panel = None

    def delete_bookmark(self, idx: int) -> None:
        if 0 <= idx < len(self.bookmarks):
            self.bookmarks.pop(idx)
        self.status["bookmark_deleted"] = True
        self._write_status()
        self._render_bookmarks_list()


def main() -> None:
    root = tk.Tk()
    app = BrowserBookmarkApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
