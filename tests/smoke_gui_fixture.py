from __future__ import annotations

import json
import os
import sys
import tempfile
import tkinter as tk
from pathlib import Path

STATUS_FILE = Path(tempfile.gettempdir()) / "LiteComputerUse" / "smoke_status.json"


class SmokeApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("LCU Smoke Fixture")
        self.root.geometry("600x450")
        self.root.configure(bg="#f0f0f0")

        self.status = {
            "hit_A": 0,
            "hit_B": 0,
            "hit_C": 0,
            "drag_done": False,
            "text_received": "",
        }
        self._write_status()

        # Place Button A at (100, 80)
        self.btn_a = tk.Button(root, text="Button A", command=self.on_a, bg="#4CAF50", fg="white", font=("Arial", 12))
        self.btn_a.place(x=100, y=80, width=100, height=50)

        # Place Button B at (350, 80)
        self.btn_b = tk.Button(root, text="Button B", command=self.on_b, bg="#2196F3", fg="white", font=("Arial", 12))
        self.btn_b.place(x=350, y=80, width=100, height=50)

        # Place Button C at (225, 200)
        self.btn_c = tk.Button(root, text="Button C", command=self.on_c, bg="#FF9800", fg="white", font=("Arial", 12))
        self.btn_c.place(x=225, y=200, width=100, height=50)

        # Entry for typing test
        self.entry = tk.Entry(root, font=("Arial", 12))
        self.entry.place(x=100, y=300, width=250, height=35)
        self.entry.bind("<KeyRelease>", self.on_text)

        # Canvas for drag test
        self.canvas = tk.Canvas(root, bg="#ffffff", highlightthickness=1, highlightbackground="#999")
        self.canvas.place(x=400, y=260, width=160, height=130)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_drag)

        # Poll status file
        self.root.after(100, self._poll)

    def _write_status(self) -> None:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.status, f)

    def on_a(self) -> None:
        self.status["hit_A"] += 1
        self._write_status()

    def on_b(self) -> None:
        self.status["hit_B"] += 1
        self._write_status()

    def on_c(self) -> None:
        self.status["hit_C"] += 1
        self._write_status()

    def on_text(self, event: Any) -> None:
        self.status["text_received"] = self.entry.get()
        self._write_status()

    def on_drag(self, event: Any) -> None:
        self.status["drag_done"] = True
        self._write_status()

    def _poll(self) -> None:
        # Check if exit signaled
        exit_file = STATUS_FILE.parent / "smoke_exit.flag"
        if exit_file.exists():
            try:
                exit_file.unlink()
            except Exception:
                pass
            self.root.destroy()
            return
        self.root.after(100, self._poll)


def main() -> None:
    if os.name == "nt":
        try:
            import ctypes
            import win32con
            import win32service

            hdesk = win32service.OpenDesktop("default", 0, False, win32con.GENERIC_ALL)
            if hdesk:
                ctypes.windll.user32.SetThreadDesktop(int(hdesk))
        except Exception:
            pass

    root = tk.Tk()
    app = SmokeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
