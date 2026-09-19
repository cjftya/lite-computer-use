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

STATUS_FILE = Path(tempfile.gettempdir()) / "LiteComputerUse" / "search_tab_status.json"
TARGET_TITLE_TEXT = "OpenAI ChatGPT Overview & Capabilities"


class BrowserSearchApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("LCU Browser - Search & Multi-Tab")
        self.root.geometry("700x520")
        self.root.configure(bg="#f8fafc")

        self.status = {
            "search_query": "",
            "search_executed": False,
            "new_tab_opened": False,
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
        # Notebook for Tabs
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook", background="#e2e8f0")
        style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=[12, 6])

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)

        # Tab 1: Search Portal
        self.tab_search = tk.Frame(self.notebook, bg="#ffffff")
        self.notebook.add(self.tab_search, text="🔍 Search Portal")

        # Tab 2: Destination page (created when opened)
        self.tab_dest = None

        self._build_search_tab()

    def _build_search_tab(self) -> None:
        # Search Box bar
        search_bar = tk.Frame(self.tab_search, bg="#f1f5f9", pady=15, padx=20)
        search_bar.pack(fill="x", side="top")

        lbl_logo = tk.Label(search_bar, text="LCU Portal", font=("Segoe UI", 14, "bold"), fg="#2563eb", bg="#f1f5f9")
        lbl_logo.pack(side="left", padx=(0, 15))

        self.ent_search = tk.Entry(search_bar, font=("Segoe UI", 11), bd=1, relief="solid")
        self.ent_search.pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=4)
        self.ent_search.bind("<Return>", lambda e: self.on_search())

        btn_search = tk.Button(
            search_bar,
            text="검색",
            font=("Segoe UI", 10, "bold"),
            bg="#2563eb",
            fg="white",
            bd=0,
            padx=15,
            command=self.on_search,
        )
        btn_search.pack(side="left")

        # Results area
        self.results_frame = tk.Frame(self.tab_search, bg="#ffffff", padx=25, pady=20)
        self.results_frame.pack(fill="both", expand=True)

        self.lbl_initial = tk.Label(
            self.results_frame,
            text="검색어를 입력하고 [검색]을 누르세요.",
            font=("Segoe UI", 11),
            fg="#64748b",
            bg="#ffffff",
        )
        self.lbl_initial.pack(pady=40)

    def on_search(self) -> None:
        query = self.ent_search.get().strip()
        self.status["search_query"] = query
        self.status["search_executed"] = True
        self._write_status()

        for w in self.results_frame.winfo_children():
            w.destroy()

        header = tk.Label(
            self.results_frame,
            text=f"'{query}' 검색 결과 (약 1,420,000건)",
            font=("Segoe UI", 11, "bold"),
            fg="#1e293b",
            bg="#ffffff",
        )
        header.pack(anchor="w", pady=(0, 15))

        # Result Item 1: Target OpenAI result
        res1 = tk.Frame(self.results_frame, bg="#ffffff", bd=1, relief="solid", padx=12, pady=10)
        res1.pack(fill="x", pady=(0, 10))

        title1 = tk.Label(
            res1,
            text="ChatGPT - OpenAI 공식 사이트",
            font=("Segoe UI", 12, "bold"),
            fg="#1d4ed8",
            bg="#ffffff",
            cursor="hand2",
        )
        title1.pack(anchor="w")

        url1 = tk.Label(res1, text="https://openai.com/chatgpt", font=("Segoe UI", 9), fg="#059669", bg="#ffffff")
        url1.pack(anchor="w", pady=(1, 4))

        desc1 = tk.Label(
            res1,
            text="OpenAI의 ChatGPT를 통해 일상적인 대화, 코딩 지원, 창의적인 글쓰기를 경험하세요.",
            font=("Segoe UI", 10),
            fg="#475569",
            bg="#ffffff",
            wraplength=600,
            justify="left",
        )
        desc1.pack(anchor="w", pady=(0, 6))

        # New tab button
        btn_new_tab = tk.Button(
            res1,
            text="새 탭으로 열기 (Open in New Tab)",
            font=("Segoe UI", 9, "bold"),
            bg="#2563eb",
            fg="white",
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            command=self.open_new_tab,
        )
        btn_new_tab.pack(anchor="w")

        # Result Item 2
        res2 = tk.Frame(self.results_frame, bg="#ffffff", bd=1, relief="solid", padx=12, pady=10)
        res2.pack(fill="x")
        title2 = tk.Label(res2, text="ChatGPT - 위키백과", font=("Segoe UI", 11, "bold"), fg="#1d4ed8", bg="#ffffff")
        title2.pack(anchor="w")
        desc2 = tk.Label(res2, text="ChatGPT는 OpenAI가 개발한 인공지능 챗봇입니다.", font=("Segoe UI", 9), fg="#475569", bg="#ffffff")
        desc2.pack(anchor="w")

    def open_new_tab(self) -> None:
        if self.tab_dest is not None:
            self.notebook.select(self.tab_dest)
            return

        self.tab_dest = tk.Frame(self.notebook, bg="#ffffff")
        self.notebook.add(self.tab_dest, text="📄 OpenAI ChatGPT")
        self.notebook.select(self.tab_dest)

        self.status["new_tab_opened"] = True
        self._write_status()

        # Build Tab 2 page content
        content = tk.Frame(self.tab_dest, bg="#ffffff", padx=30, pady=25)
        content.pack(fill="both", expand=True)

        badge = tk.Label(content, text="공식 제품 페이지", font=("Segoe UI", 9, "bold"), bg="#dbeafe", fg="#1e40af", padx=6, pady=2)
        badge.pack(anchor="w", pady=(0, 8))

        self.lbl_page_title = tk.Label(
            content,
            text=TARGET_TITLE_TEXT,
            font=("Segoe UI", 16, "bold"),
            fg="#0f172a",
            bg="#ffffff",
        )
        self.lbl_page_title.pack(anchor="w", pady=(0, 10))

        desc = tk.Label(
            content,
            text="OpenAI ChatGPT provides conversational artificial intelligence capabilities powered by cutting-edge neural models.",
            font=("Segoe UI", 11),
            fg="#334155",
            bg="#ffffff",
            wraplength=620,
            justify="left",
        )
        desc.pack(anchor="w", pady=(0, 25))

        btn_copy = tk.Button(
            content,
            text="📋 제목 복사 (Copy Title to Clipboard)",
            font=("Segoe UI", 11, "bold"),
            bg="#059669",
            fg="white",
            bd=0,
            padx=15,
            pady=8,
            cursor="hand2",
            command=self.copy_title,
        )
        btn_copy.pack(anchor="w")

        self.lbl_copy_notice = tk.Label(content, text="", font=("Segoe UI", 10, "italic"), bg="#ffffff", fg="#059669")
        self.lbl_copy_notice.pack(anchor="w", pady=(10, 0))

    def copy_title(self) -> None:
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, TARGET_TITLE_TEXT)
        finally:
            win32clipboard.CloseClipboard()

        self.status["title_copied"] = True
        self._write_status()
        self.lbl_copy_notice.configure(text=f"✔ 클립보드에 복사됨: '{TARGET_TITLE_TEXT}'")


def main() -> None:
    root = tk.Tk()
    app = BrowserSearchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
