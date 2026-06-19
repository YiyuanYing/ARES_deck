#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import time
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable, Dict, Tuple

from core.map_message import build_action_command_payload, send_action_command_payload


COMMAND_ROWS = (3, 2)
COMMAND_COLS: Tuple[Tuple[str, str], ...] = (("left", "LEFT"), ("mid", "MID"), ("right", "RIGHT"))


class ActionCommandDialog:
    def __init__(
        self,
        parent: tk.Tk,
        *,
        theme: Dict[str, str],
        local_ip: str,
        target_ip: str,
        target_port: int,
        origin: tuple[int, int] | None = None,
        status_provider: Callable[[], str] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.parent = parent
        self.theme = theme
        self.local_ip = local_ip
        self.target_ip = target_ip
        self.target_port = int(target_port)
        self.origin = origin
        self.status_provider = status_provider
        self.on_close = on_close
        self.command_buttons: Dict[Tuple[int, str], tk.Button] = {}
        self.place_button: tk.Button | None = None
        self.release_button: tk.Button | None = None
        self.status_label: tk.Label | None = None
        self.reset_after_id: str | None = None
        self.window = tk.Toplevel(parent)
        self.window.title("Target Action")
        self.window.configure(bg=self.theme["bg"])
        self.window.transient(parent)
        self.window.overrideredirect(True)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.resizable(False, False)
        self.window.withdraw()

        self.target_x = 0
        self.target_y = 0
        self.target_width = 640
        self.target_height = 700
        self.ui_font_family = self.pick_font_family()
        self.mono_font_family = "DejaVu Sans Mono"

        self.build_ui()
        self.center_window()
        self.animate_in()
        self.refresh_status_label()

    def build_ui(self) -> None:
        surface = self.theme["surface"]
        panel = self.theme["panel_dark"]
        line = self.theme["line"]
        text = self.theme["text"]
        muted = self.theme["muted"]

        outer = tk.Frame(self.window, bg=self.theme["bg"], padx=24, pady=24)
        outer.pack(fill=tk.BOTH, expand=True)

        card = tk.Frame(outer, bg=panel, highlightthickness=2, highlightbackground=line, padx=24, pady=18)
        card.pack(fill=tk.BOTH, expand=True)

        title_bar = tk.Frame(card, bg=panel)
        title_bar.pack(fill=tk.X, pady=(0, 20))
        dots = tk.Frame(title_bar, bg=panel)
        dots.pack(side=tk.LEFT, padx=(0, 12))
        for color in ("#ff5f57", "#ffbd2e", "#28c840"):
            tk.Label(dots, bg=color, width=2, height=1).pack(side=tk.LEFT, padx=3)
        tk.Label(
            title_bar,
            text="TARGET ACTION",
            bg=panel,
            fg=text,
            font=(self.ui_font_family, 22, "bold"),
        ).pack(side=tk.LEFT)
        self.status_label = tk.Label(
            title_bar,
            text="HOST ...",
            bg=panel,
            fg=muted,
            font=(self.mono_font_family, 11, "bold"),
        )
        self.status_label.pack(side=tk.LEFT, padx=(30, 0))

        body = tk.Frame(card, bg=panel)
        body.pack(fill=tk.BOTH, expand=True)
        body.grid_columnconfigure(0, minsize=290, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        left_panel = tk.Frame(body, bg=surface, highlightthickness=2, highlightbackground=line, padx=18, pady=18, width=290)
        left_panel.grid(row=0, column=0, sticky="ns")
        left_panel.pack_propagate(False)

        tk.Label(left_panel, text="ACTION", bg=surface, fg=muted, font=(self.ui_font_family, 18, "bold")).pack(anchor="w")
        tk.Label(
            left_panel,
            text="Tap a command tile to send immediately.",
            bg=surface,
            fg=muted,
            font=(self.ui_font_family, 13),
            wraplength=245,
            justify="left",
        ).pack(anchor="w", pady=(14, 0))

        bottom_actions = tk.Frame(left_panel, bg=surface)
        bottom_actions.pack(fill=tk.X, side=tk.BOTTOM)

        self.release_button = tk.Button(
            bottom_actions,
            text="RELEASE",
            command=self.send_release,
            bg=self.theme["danger_bg"],
            fg=text,
            activebackground=self.theme["danger"],
            activeforeground=text,
            relief=tk.FLAT,
            font=(self.ui_font_family, 22, "bold"),
            padx=28,
            pady=22,
        )
        self.release_button.pack(fill=tk.X, pady=(0, 12))

        self.place_button = tk.Button(
            bottom_actions,
            text="PLACE",
            command=self.send_place,
            bg=self.theme["accent_bg"],
            fg=text,
            activebackground=self.theme["accent"],
            activeforeground=text,
            relief=tk.FLAT,
            font=(self.ui_font_family, 24, "bold"),
            padx=30,
            pady=26,
        )
        self.place_button.pack(fill=tk.X)

        center_panel = tk.Frame(body, bg=panel, padx=20)
        center_panel.grid(row=0, column=1, sticky="nsew")
        center_panel.grid_columnconfigure(0, weight=1)
        center_panel.grid_rowconfigure(0, weight=1)

        grid_frame = tk.Frame(center_panel, bg=panel)
        grid_frame.grid(row=0, column=0, sticky="nsew")
        for col_index in range(3):
            grid_frame.grid_columnconfigure(col_index, weight=1, uniform="action_cols")
        for row_index in range(2):
            grid_frame.grid_rowconfigure(row_index, weight=1, uniform="action_rows")

        for row_index, row_value in enumerate(COMMAND_ROWS):
            for col_index, (col_value, col_label) in enumerate(COMMAND_COLS):
                button = tk.Button(
                    grid_frame,
                    text=f"{row_value} {col_label}",
                    command=lambda r=row_value, c=col_value: self.send_select(r, c),
                    bg=self.theme["panel_field"],
                    fg=text,
                    activebackground=self.theme["surface_alt"],
                    activeforeground=text,
                    relief=tk.FLAT,
                    highlightthickness=2,
                    highlightbackground=line,
                    font=(self.ui_font_family, 28, "bold"),
                    padx=20,
                    pady=28,
                )
                button.grid(row=row_index, column=col_index, sticky="nsew", padx=14, pady=14)
                self.command_buttons[(row_value, col_value)] = button

    def pick_font_family(self) -> str:
        families = set(tkfont.families(self.window))
        for family in ("Noto Sans CJK SC", "Microsoft YaHei", "WenQuanYi Zen Hei", "Arial Unicode MS"):
            if family in families:
                return family
        return "DejaVu Sans"

    def send_select(self, row: int, col: str) -> None:
        button = self.command_buttons.get((row, col))
        try:
            payload = build_action_command_payload("select", row=row, col=col)
            sent = send_action_command_payload(payload, self.local_ip, self.target_ip, self.target_port)
        except Exception as exc:
            print(f"[action-command] send failed: {exc}")
            self.set_button_state(button, "failed", f"{row} {col.upper()}")
            return
        print(f"[action-command] sent select row={row} col={col} {sent} bytes -> {self.target_ip}:{self.target_port}")
        self.set_button_state(button, "sent", f"{row} {col.upper()}")

    def send_place(self) -> None:
        self.send_simple_action("place", self.place_button, "PLACE")

    def send_release(self) -> None:
        self.send_simple_action("release", self.release_button, "RELEASE")

    def send_simple_action(self, action: str, button: tk.Button | None, label: str) -> None:
        try:
            payload = build_action_command_payload(action)
            sent = send_action_command_payload(payload, self.local_ip, self.target_ip, self.target_port)
        except Exception as exc:
            print(f"[action-command] send failed: {exc}")
            self.set_button_state(button, "failed", label)
            return
        print(f"[action-command] sent {action} {sent} bytes -> {self.target_ip}:{self.target_port}")
        self.set_button_state(button, "sent", label)

    def set_button_state(self, button: tk.Button | None, state: str, label: str) -> None:
        if button is None:
            return
        if self.reset_after_id is not None:
            try:
                self.window.after_cancel(self.reset_after_id)
            except tk.TclError:
                pass
            self.reset_after_id = None

        if state == "sent":
            button.configure(text="SENT", bg=self.theme["ok_dark"], activebackground=self.theme["ok"], fg=self.theme["active_text"])
            self.reset_after_id = self.window.after(900, lambda: self.restore_buttons())
        elif state == "failed":
            button.configure(text="FAILED", bg=self.theme["danger_bg"], activebackground=self.theme["danger"], fg=self.theme["active_text"])
            self.reset_after_id = self.window.after(1400, lambda: self.restore_buttons())
        else:
            button.configure(text=label)

    def restore_buttons(self) -> None:
        self.reset_after_id = None
        for row_value in COMMAND_ROWS:
            for col_value, col_label in COMMAND_COLS:
                button = self.command_buttons[(row_value, col_value)]
                button.configure(
                    text=f"{row_value} {col_label}",
                    bg=self.theme["panel_field"],
                    activebackground=self.theme["surface_alt"],
                    fg=self.theme["text"],
                )
        if self.place_button is not None:
            self.place_button.configure(
                text="PLACE",
                bg=self.theme["accent_bg"],
                activebackground=self.theme["accent"],
                fg=self.theme["text"],
            )
        if self.release_button is not None:
            self.release_button.configure(
                text="RELEASE",
                bg=self.theme["danger_bg"],
                activebackground=self.theme["danger"],
                fg=self.theme["text"],
            )

    def refresh_status_label(self) -> None:
        if self.status_label is not None and self.status_provider is not None:
            try:
                self.status_label.configure(text=self.status_provider())
            except Exception as exc:
                self.status_label.configure(text=f"HOST status unavailable: {exc}")
        if self.window.winfo_exists():
            self.window.after(500, self.refresh_status_label)

    def center_window(self) -> None:
        self.window.update_idletasks()
        parent_x = self.parent.winfo_rootx()
        parent_y = self.parent.winfo_rooty()
        parent_w = max(self.parent.winfo_width(), 1)
        parent_h = max(self.parent.winfo_height(), 1)
        self.target_width = parent_w
        self.target_height = parent_h
        self.target_x = parent_x
        self.target_y = parent_y
        start_width = 52
        start_height = 40
        if self.origin is None:
            start_x = self.target_x + (self.target_width - start_width) // 2
            start_y = self.target_y + (self.target_height - start_height) // 2
        else:
            start_x = int(self.origin[0] - start_width / 2)
            start_y = int(self.origin[1] - start_height / 2)
        self.window.geometry(f"{start_width}x{start_height}+{start_x}+{start_y}")

    def animate_in(self) -> None:
        try:
            self.window.attributes("-alpha", 0.35)
        except tk.TclError:
            self.window.geometry(f"{self.target_width}x{self.target_height}+{self.target_x}+{self.target_y}")
            self.window.deiconify()
            return

        self.window.deiconify()
        self.window.lift()
        start = time.perf_counter()
        duration = 0.08

        def step() -> None:
            elapsed = time.perf_counter() - start
            progress = min(1.0, elapsed / duration)
            eased = 1.0 - (1.0 - progress) ** 3
            alpha = 0.35 + 0.65 * eased
            start_width = 52
            start_height = 40
            if self.origin is None:
                start_x = self.target_x + (self.target_width - start_width) // 2
                start_y = self.target_y + (self.target_height - start_height) // 2
            else:
                start_x = int(self.origin[0] - start_width / 2)
                start_y = int(self.origin[1] - start_height / 2)
            width = int(start_width + (self.target_width - start_width) * eased)
            height = int(start_height + (self.target_height - start_height) * eased)
            x = int(start_x + (self.target_x - start_x) * eased)
            y = int(start_y + (self.target_y - start_y) * eased)
            try:
                self.window.geometry(f"{width}x{height}+{x}+{y}")
                self.window.attributes("-alpha", alpha)
            except tk.TclError:
                return
            if progress < 1.0 and self.window.winfo_exists():
                self.window.after(12, step)
            else:
                self.window.geometry(f"{self.target_width}x{self.target_height}+{self.target_x}+{self.target_y}")

        step()

    def handle_screen_touch(self, screen_x: float, screen_y: float) -> bool:
        if not self.window.winfo_exists():
            return False
        abs_x = self.parent.winfo_rootx() + int(screen_x)
        abs_y = self.parent.winfo_rooty() + int(screen_y)

        if self.place_button is not None and self.widget_contains(self.place_button, abs_x, abs_y):
            self.send_place()
            return True
        if self.release_button is not None and self.widget_contains(self.release_button, abs_x, abs_y):
            self.send_release()
            return True

        for (row, col), button in self.command_buttons.items():
            if self.widget_contains(button, abs_x, abs_y):
                self.send_select(row, col)
                return True
        return self.widget_contains(self.window, abs_x, abs_y)

    @staticmethod
    def widget_contains(widget: tk.Widget, abs_x: int, abs_y: int) -> bool:
        try:
            x1 = widget.winfo_rootx()
            y1 = widget.winfo_rooty()
            x2 = x1 + widget.winfo_width()
            y2 = y1 + widget.winfo_height()
        except tk.TclError:
            return False
        return x1 <= abs_x <= x2 and y1 <= abs_y <= y2

    def cancel(self) -> None:
        if self.on_close is not None:
            self.on_close()
        self.window.destroy()
