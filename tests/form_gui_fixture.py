from __future__ import annotations

import json
import os
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
from pathlib import Path

STATUS_FILE = Path(tempfile.gettempdir()) / "LiteComputerUse" / "form_status.json"


class FormApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("LCU Form Fixture")
        self.root.geometry("600x520")
        self.root.configure(bg="#f8fafc")

        self.status = {
            "step": 1,
            "name": "",
            "email": "",
            "country": "",
            "opt_a": False,
            "opt_b": False,
            "opt_c": False,
            "memo": "",
            "submitted": False,
        }
        self._write_status()

        # Container
        self.frame = tk.Frame(root, bg="#ffffff", bd=1, relief="solid", padx=25, pady=20)
        self.frame.place(x=50, y=30, width=500, height=450)

        self._build_step1()

        self.root.deiconify()
        self.root.update()

    def _write_status(self) -> None:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.status, f, ensure_ascii=False)

    def _build_step1(self) -> None:
        for widget in self.frame.winfo_children():
            widget.destroy()

        self.status["step"] = 1
        self._write_status()

        title = tk.Label(self.frame, text="회원 정보 입력 (1단계)", font=("Arial", 14, "bold"), bg="#ffffff", fg="#1e293b")
        title.pack(anchor="w", pady=(0, 15))

        # Name
        lbl_name = tk.Label(self.frame, text="이름", font=("Arial", 10, "bold"), bg="#ffffff", fg="#334155")
        lbl_name.pack(anchor="w", pady=(0, 2))
        self.ent_name = tk.Entry(self.frame, font=("Arial", 11), bd=1, relief="solid")
        self.ent_name.pack(fill="x", pady=(0, 12), ipady=4)

        # Email
        lbl_email = tk.Label(self.frame, text="이메일", font=("Arial", 10, "bold"), bg="#ffffff", fg="#334155")
        lbl_email.pack(anchor="w", pady=(0, 2))
        self.ent_email = tk.Entry(self.frame, font=("Arial", 11), bd=1, relief="solid")
        self.ent_email.pack(fill="x", pady=(0, 12), ipady=4)

        # Country
        lbl_country = tk.Label(self.frame, text="국가", font=("Arial", 10, "bold"), bg="#ffffff", fg="#334155")
        lbl_country.pack(anchor="w", pady=(0, 2))
        self.combo_country = ttk.Combobox(self.frame, values=["United States", "South Korea", "Japan", "Germany"], state="readonly", font=("Arial", 10))
        self.combo_country.set("국가를 선택하세요")
        self.combo_country.pack(fill="x", pady=(0, 15), ipady=3)

        # Checkboxes
        lbl_opt = tk.Label(self.frame, text="옵션 선택", font=("Arial", 10, "bold"), bg="#ffffff", fg="#334155")
        lbl_opt.pack(anchor="w", pady=(0, 4))
        
        chk_frame = tk.Frame(self.frame, bg="#ffffff")
        chk_frame.pack(fill="x", pady=(0, 20))

        self.var_a = tk.BooleanVar(value=False)
        self.var_b = tk.BooleanVar(value=False)
        self.var_c = tk.BooleanVar(value=False)

        chk_a = tk.Checkbutton(chk_frame, text="옵션 A", variable=self.var_a, bg="#ffffff", font=("Arial", 10))
        chk_a.pack(side="left", padx=(0, 15))
        chk_b = tk.Checkbutton(chk_frame, text="옵션 B", variable=self.var_b, bg="#ffffff", font=("Arial", 10))
        chk_b.pack(side="left", padx=(0, 15))
        chk_c = tk.Checkbutton(chk_frame, text="옵션 C", variable=self.var_c, bg="#ffffff", font=("Arial", 10))
        chk_c.pack(side="left")

        # Continue button
        btn_continue = tk.Button(self.frame, text="Continue", command=self.on_continue, bg="#2563eb", fg="white", font=("Arial", 11, "bold"), bd=0, cursor="hand2")
        btn_continue.pack(fill="x", pady=(10, 0), ipady=6)

    def on_continue(self) -> None:
        self.status["name"] = self.ent_name.get()
        self.status["email"] = self.ent_email.get()
        self.status["country"] = self.combo_country.get()
        self.status["opt_a"] = self.var_a.get()
        self.status["opt_b"] = self.var_b.get()
        self.status["opt_c"] = self.var_c.get()
        self.status["step"] = 2
        self._write_status()
        self._build_step2()

    def _build_step2(self) -> None:
        for widget in self.frame.winfo_children():
            widget.destroy()

        title = tk.Label(self.frame, text="추가 메모 작성 (2단계)", font=("Arial", 14, "bold"), bg="#ffffff", fg="#1e293b")
        title.pack(anchor="w", pady=(0, 15))

        lbl_memo = tk.Label(self.frame, text="메모", font=("Arial", 10, "bold"), bg="#ffffff", fg="#334155")
        lbl_memo.pack(anchor="w", pady=(0, 4))

        self.txt_memo = tk.Text(self.frame, height=8, font=("Arial", 11), bd=1, relief="solid")
        self.txt_memo.pack(fill="x", pady=(0, 20))

        btn_submit = tk.Button(self.frame, text="Submit", command=self.on_submit, bg="#059669", fg="white", font=("Arial", 11, "bold"), bd=0, cursor="hand2")
        btn_submit.pack(fill="x", pady=(10, 0), ipady=6)

    def on_submit(self) -> None:
        self.status["memo"] = self.txt_memo.get("1.0", "end-1c")
        self.status["submitted"] = True
        self.status["step"] = 3
        self._write_status()
        self._build_complete()

    def _build_complete(self) -> None:
        for widget in self.frame.winfo_children():
            widget.destroy()

        success_title = tk.Label(self.frame, text="완료되었습니다!", font=("Arial", 16, "bold"), bg="#ffffff", fg="#059669")
        success_title.pack(pady=(40, 15))

        opts = []
        if self.status["opt_a"]: opts.append("A")
        if self.status["opt_b"]: opts.append("B")
        if self.status["opt_c"]: opts.append("C")

        summary = (
            f"이름: {self.status['name']}\n"
            f"이메일: {self.status['email']}\n"
            f"국가: {self.status['country']}\n"
            f"선택 옵션: {', '.join(opts)}\n"
            f"메모: {self.status['memo']}"
        )

        lbl_summary = tk.Label(self.frame, text=summary, font=("Arial", 11), bg="#f0fdf4", fg="#166534", bd=1, relief="solid", padx=15, pady=15, justify="left")
        lbl_summary.pack(fill="x", pady=10)

        # Poll for clean exit
        self.root.after(100, self._poll)

    def _poll(self) -> None:
        exit_file = STATUS_FILE.parent / "form_exit.flag"
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
    app = FormApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
