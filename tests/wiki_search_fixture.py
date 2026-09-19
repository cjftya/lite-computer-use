from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import tkinter as tk
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

STATUS_FILE = Path(tempfile.gettempdir()) / "LiteComputerUse" / "tc16_wiki_status.json"
ARTICLE_TITLE = "Computer vision"


class WikipediaFixtureApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Wikipedia - The Free Encyclopedia")
        self.root.geometry("700x520")
        self.root.configure(bg="#ffffff")

        self.status = {
            "search_query": "",
            "article_loaded": False,
            "title_copied": False,
        }
        self._write_status()

        self._build_ui()
        self.root.deiconify()
        self.root.update()

    def _write_status(self) -> None:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.status, f, ensure_ascii=False)

    def _build_ui(self) -> None:
        # Top bar with Logo & Search
        top_bar = tk.Frame(self.root, bg="#f8fafc", height=50, bd=1, relief="solid")
        top_bar.pack(fill="x", side="top")

        lbl_logo = tk.Label(top_bar, text="WIKIPEDIA", font=("Georgia", 13, "bold"), bg="#f8fafc", fg="#111827")
        lbl_logo.pack(side="left", padx=(15, 15), pady=10)

        lbl_search = tk.Label(top_bar, text="검색:", font=("Segoe UI", 9, "bold"), bg="#f8fafc", fg="#475569")
        lbl_search.pack(side="left", padx=(0, 5))

        self.ent_search = tk.Entry(top_bar, font=("Segoe UI", 10), bd=1, relief="solid", width=32)
        self.ent_search.pack(side="left", padx=(0, 8), ipady=3)
        self.ent_search.bind("<Return>", lambda e: self.on_search())

        self.btn_search = tk.Button(
            top_bar,
            text="검색",
            font=("Segoe UI", 9, "bold"),
            bg="#2563eb",
            fg="white",
            bd=0,
            padx=12,
            pady=3,
            cursor="hand2",
            command=self.on_search,
        )
        self.btn_search.pack(side="left")

        # Content frame
        self.content_frame = tk.Frame(self.root, bg="#ffffff", padx=30, pady=25)
        self.content_frame.pack(fill="both", expand=True)

        self._render_home()

    def _render_home(self) -> None:
        for w in self.content_frame.winfo_children():
            w.destroy()

        h = tk.Label(self.content_frame, text="Wikipedia 메인 페이지", font=("Georgia", 16, "bold"), bg="#ffffff", fg="#111827")
        h.pack(anchor="w", pady=(20, 10))

        sub = tk.Label(
            self.content_frame,
            text="상단 검색창에 'Computer vision'을 입력하고 [검색]을 누르세요.",
            font=("Segoe UI", 11),
            bg="#ffffff",
            fg="#64748b",
        )
        sub.pack(anchor="w", pady=(0, 20))

    def on_search(self) -> None:
        q = self.ent_search.get().strip()
        self.status["search_query"] = q
        self.status["article_loaded"] = True
        self._write_status()

        for w in self.content_frame.winfo_children():
            w.destroy()

        # Render Article
        lbl_title = tk.Label(self.content_frame, text=ARTICLE_TITLE, font=("Georgia", 22, "bold"), bg="#ffffff", fg="#0f172a")
        lbl_title.pack(anchor="w", pady=(10, 4))

        lbl_sub = tk.Label(self.content_frame, text="From Wikipedia, the free encyclopedia", font=("Georgia", 10, "italic"), bg="#ffffff", fg="#64748b")
        lbl_sub.pack(anchor="w", pady=(0, 15))

        line = tk.Frame(self.content_frame, bg="#cbd5e1", height=1)
        line.pack(fill="x", pady=(0, 15))

        body = tk.Label(
            self.content_frame,
            text="Computer vision is an interdisciplinary scientific field that deals with how computers can gain high-level understanding from digital images or videos. From the perspective of engineering, it seeks to understand and automate tasks that the human visual system can do.",
            font=("Segoe UI", 10),
            bg="#ffffff",
            fg="#334155",
            wraplength=620,
            justify="left",
        )
        body.pack(anchor="w", pady=(0, 20))

        self.btn_copy = tk.Button(
            self.content_frame,
            text="📋 제목 복사 (Copy Title)",
            font=("Segoe UI", 10, "bold"),
            bg="#059669",
            fg="white",
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self.copy_title,
        )
        self.btn_copy.pack(anchor="w")

        self.lbl_copied = tk.Label(self.content_frame, text="", font=("Segoe UI", 9, "italic"), bg="#ffffff", fg="#059669")
        self.lbl_copied.pack(anchor="w", pady=(8, 0))

    def copy_title(self) -> None:
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, ARTICLE_TITLE)
        finally:
            win32clipboard.CloseClipboard()

        self.status["title_copied"] = True
        self._write_status()
        self.lbl_copied.configure(text=f"✔ 클립보드 복사 완료: '{ARTICLE_TITLE}'")


def main() -> None:
    root = tk.Tk()
    app = WikipediaFixtureApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
