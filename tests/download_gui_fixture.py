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

DOWNLOADS_DIR = Path.home() / "Downloads"
DOWNLOADED_FILE = DOWNLOADS_DIR / "sample-report.txt"
DOWNLOAD_CONTENT = "LCU Download Verification Successful - 2026\nStatus: Verified\n"

STATUS_FILE = Path(tempfile.gettempdir()) / "LiteComputerUse" / "download_status.json"


class DownloadBrowserApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("LCU Browser - Web Download")
        self.root.geometry("650x500")
        self.root.configure(bg="#f1f5f9")

        self.status = {
            "download_clicked": False,
            "download_finished": False,
            "downloads_menu_opened": False,
            "file_opened": False,
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
        # Browser toolbar
        toolbar = tk.Frame(self.root, bg="#e2e8f0", height=45, bd=1, relief="solid")
        toolbar.pack(fill="x", side="top")

        lbl_url_title = tk.Label(toolbar, text="URL:", bg="#e2e8f0", font=("Segoe UI", 9, "bold"))
        lbl_url_title.pack(side="left", padx=(10, 5), pady=8)

        url_entry = tk.Entry(toolbar, font=("Segoe UI", 9), bd=1, relief="solid")
        url_entry.insert(0, "http://localhost:8765/download.html")
        url_entry.configure(state="readonly")
        url_entry.pack(side="left", fill="x", expand=True, padx=5, pady=8)

        self.btn_dl_menu = tk.Button(
            toolbar,
            text="Downloads (Ctrl+J)",
            bg="#ffffff",
            fg="#1e293b",
            font=("Segoe UI", 9),
            bd=1,
            command=self.toggle_downloads_panel,
        )
        self.btn_dl_menu.pack(side="right", padx=10, pady=6)

        # Page content frame
        self.content = tk.Frame(self.root, bg="#ffffff", bd=1, relief="solid")
        self.content.pack(fill="both", expand=True, padx=20, pady=20)

        title = tk.Label(self.content, text="샘플 데이터 다운로드 센터", font=("Segoe UI", 16, "bold"), bg="#ffffff", fg="#0f172a")
        title.pack(pady=(35, 10))

        desc = tk.Label(
            self.content,
            text="아래 버튼을 클릭하여 검증 리포트(sample-report.txt)를 다운로드하세요.",
            font=("Segoe UI", 11),
            bg="#ffffff",
            fg="#475569",
        )
        desc.pack(pady=(0, 30))

        # Download button
        self.btn_download = tk.Button(
            self.content,
            text="⬇ Download sample-report.txt",
            bg="#2563eb",
            fg="#ffffff",
            font=("Segoe UI", 12, "bold"),
            padx=20,
            pady=10,
            bd=0,
            cursor="hand2",
            command=self.start_download,
        )
        self.btn_download.pack(pady=10)

        # Status label
        self.lbl_status = tk.Label(self.content, text="", font=("Segoe UI", 10, "italic"), bg="#ffffff", fg="#64748b")
        self.lbl_status.pack(pady=10)

        # Downloads flyout panel (initially hidden)
        self.dl_panel = tk.Frame(self.root, bg="#f8fafc", bd=2, relief="groove")
        self.dl_panel_visible = False

    def start_download(self) -> None:
        self.status["download_clicked"] = True
        self.lbl_status.configure(text="다운로드 진행 중...", fg="#2563eb")
        self.root.update()

        # Simulate brief download write
        time.sleep(0.3)
        try:
            DOWNLOADED_FILE.write_text(DOWNLOAD_CONTENT, encoding="utf-8")
        except Exception as e:
            self.lbl_status.configure(text=f"오류: {e}", fg="#dc2626")
            return

        self.status["download_finished"] = True
        self._write_status()

        self.lbl_status.configure(text="✔ 다운로드 완료: Downloads/sample-report.txt", fg="#059669")
        self.show_downloads_panel()

    def show_downloads_panel(self) -> None:
        self.dl_panel.place(x=350, y=45, width=280, height=180)
        self.dl_panel_visible = True
        self.status["downloads_menu_opened"] = True
        self._write_status()

        for widget in self.dl_panel.winfo_children():
            widget.destroy()

        header = tk.Label(self.dl_panel, text="최근 다운로드 목록", font=("Segoe UI", 10, "bold"), bg="#f8fafc", fg="#0f172a")
        header.pack(anchor="w", padx=10, pady=(8, 4))

        item_frame = tk.Frame(self.dl_panel, bg="#ffffff", bd=1, relief="solid", padx=8, pady=6)
        item_frame.pack(fill="x", padx=10, pady=5)

        fname = tk.Label(item_frame, text="📄 sample-report.txt", font=("Segoe UI", 9, "bold"), bg="#ffffff")
        fname.pack(anchor="w")

        finfo = tk.Label(item_frame, text="완료 • 57 bytes", font=("Segoe UI", 8), bg="#ffffff", fg="#64748b")
        finfo.pack(anchor="w")

        btn_row = tk.Frame(self.dl_panel, bg="#f8fafc")
        btn_row.pack(fill="x", padx=10, pady=8)

        btn_reveal = tk.Button(
            btn_row,
            text="폴더에서 보기",
            font=("Segoe UI", 8),
            bg="#e2e8f0",
            bd=1,
            command=self.reveal_download,
        )
        btn_reveal.pack(side="left", padx=(0, 5))

        btn_open = tk.Button(
            btn_row,
            text="파일 열기",
            font=("Segoe UI", 8, "bold"),
            bg="#2563eb",
            fg="white",
            bd=0,
            command=self.open_download,
        )
        btn_open.pack(side="left")

    def toggle_downloads_panel(self) -> None:
        if self.dl_panel_visible:
            self.dl_panel.place_forget()
            self.dl_panel_visible = False
        else:
            self.show_downloads_panel()

    def reveal_download(self) -> None:
        import subprocess

        if DOWNLOADED_FILE.exists():
            subprocess.Popen(["explorer.exe", f"/select,{DOWNLOADED_FILE}"])

    def open_download(self) -> None:
        self.status["file_opened"] = True
        self._write_status()
        from lcu.apps import open_app
        open_app("notepad")


def main() -> None:
    root = tk.Tk()
    app = DownloadBrowserApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
