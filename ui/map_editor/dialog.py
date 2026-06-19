#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import time
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable, Dict, List

from core.map_message import build_target_map_payload, send_target_map_payload
from ui.map_editor.model import (
    BLUE,
    COLOR_NAMES,
    EDIT_HEIGHT,
    EDIT_WIDTH,
    EMPTY,
    GRAY,
    RED,
    MapMode,
    build_full_grid,
    count_cells,
    empty_edit_grid,
    load_map_modes,
    validate_edit_grid,
)


CELL_COLORS = {
    EMPTY: "#22151d",
    BLUE: "#348cff",
    RED: "#ff4264",
    GRAY: "#888991",
}

CELL_ACTIVE_COLORS = {
    BLUE: "#63a8ff",
    RED: "#ff6f86",
    GRAY: "#b7b8c0",
}

CELL_TEXT = {
    EMPTY: "",
    BLUE: "B",
    RED: "R",
    GRAY: "G",
}


class TargetMapEditorDialog:
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
        self.modes = load_map_modes()
        self.mode_names = list(self.modes)
        self.selected_mode = tk.StringVar(value=self.mode_names[0])
        self.selected_color = tk.IntVar(value=RED)
        self.edit_grid = empty_edit_grid()
        self.cell_buttons: List[List[tk.Button]] = []
        self.color_buttons: Dict[int, tk.Radiobutton] = {}
        self.mode_box: tk.Button | None = None
        self.clear_button: tk.Button | None = None
        self.send_button: tk.Button | None = None
        self.cancel_button: tk.Button | None = None
        self.status_label: tk.Label | None = None
        self.send_reset_after_id: str | None = None
        self.window = tk.Toplevel(parent)
        self.window.title("Target Map Editor")
        self.window.configure(bg=self.theme["bg"])
        self.window.transient(parent)
        self.window.overrideredirect(True)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.resizable(False, False)
        self.window.withdraw()

        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.target_x = 0
        self.target_y = 0
        self.target_width = 640
        self.target_height = 700
        self.ui_font_family = self.pick_font_family()
        self.mono_font_family = "DejaVu Sans Mono"

        self.build_ui()
        self.refresh()
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
        title_bar.pack(fill=tk.X, pady=(0, 18))
        title_bar.bind("<ButtonPress-1>", self.begin_drag)
        title_bar.bind("<B1-Motion>", self.drag_window)
        dots = tk.Frame(title_bar, bg=panel)
        dots.pack(side=tk.LEFT, padx=(0, 12))
        for color in ("#ff5f57", "#ffbd2e", "#28c840"):
            tk.Label(dots, bg=color, width=2, height=1).pack(side=tk.LEFT, padx=3)
        tk.Label(
            title_bar,
            text="TARGET MAP",
            bg=panel,
            fg=text,
            font=(self.ui_font_family, 22, "bold"),
        ).pack(side=tk.LEFT)
        self.status_label = tk.Label(
            title_bar,
            text="HOST ...",
            bg=panel,
            fg=self.theme["muted"],
            font=(self.mono_font_family, 11, "bold"),
        )
        self.status_label.pack(side=tk.LEFT, padx=(30, 0))
        self.cancel_button = tk.Button(
            title_bar,
            text="CLEAR",
            command=self.clear,
            bg=surface,
            fg=muted,
            activebackground=self.theme["surface_alt"],
            activeforeground=text,
            relief=tk.FLAT,
            font=(self.ui_font_family, 15, "bold"),
            padx=24,
            pady=14,
        )
        self.cancel_button.pack(side=tk.RIGHT)

        body = tk.Frame(card, bg=panel)
        body.pack(fill=tk.BOTH, expand=True)
        body.grid_columnconfigure(0, minsize=290, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        left_panel = tk.Frame(body, bg=surface, highlightthickness=2, highlightbackground=line, padx=16, pady=16, width=290)
        left_panel.grid(row=0, column=0, sticky="ns")
        left_panel.pack_propagate(False)

        center_panel = tk.Frame(body, bg=panel, padx=14)
        center_panel.grid(row=0, column=1, sticky="nsew")

        tk.Label(left_panel, text="MISSION MODE", bg=surface, fg=muted, font=(self.ui_font_family, 18, "bold")).pack(anchor="w")
        self.mode_box = tk.Button(
            left_panel,
            text=self.selected_mode.get(),
            command=self.cycle_mode,
            bg=self.theme["panel_field"],
            fg=text,
            activebackground=self.theme["surface_alt"],
            activeforeground=text,
            relief=tk.FLAT,
            highlightthickness=2,
            highlightbackground=line,
            font=(self.ui_font_family, 22, "bold"),
            padx=18,
            pady=16,
        )
        self.mode_box.pack(fill=tk.X, pady=(12, 30))

        tk.Label(left_panel, text="BLOCK COLOR", bg=surface, fg=muted, font=(self.ui_font_family, 18, "bold")).pack(anchor="w", pady=(0, 14))

        for value, label, color in (
            (GRAY, "GRAY", CELL_COLORS[GRAY]),
            (BLUE, "BLUE", CELL_COLORS[BLUE]),
            (RED, "RED", CELL_COLORS[RED]),
        ):
            button = tk.Button(
                left_panel,
                text=label,
                bg=surface,
                fg=text,
                activebackground=surface,
                activeforeground=text,
                font=(self.ui_font_family, 24, "bold"),
                padx=18,
                pady=18,
                relief=tk.FLAT,
                highlightthickness=3,
                highlightbackground=color,
                command=lambda v=value: self.select_color(v),
            )
            button.pack(fill=tk.X, pady=10)
            self.color_buttons[value] = button

        tk.Label(
            left_panel,
            text="Tap mission mode to cycle",
            bg=surface,
            fg=muted,
            font=(self.ui_font_family, 12),
            wraplength=250,
            justify="left",
        ).pack(anchor="w", pady=(12, 0))

        footer = tk.Frame(left_panel, bg=surface)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        self.clear_button = self.cancel_button
        self.send_button = tk.Button(
            footer,
            text="SEND MAP",
            command=self.send,
            bg=self.theme["accent_bg"],
            fg=text,
            activebackground=self.theme["accent"],
            activeforeground=text,
            relief=tk.FLAT,
            font=(self.ui_font_family, 15, "bold"),
            padx=42,
            pady=21,
        )
        self.send_button.pack(fill=tk.X)
        self.set_send_button_state("idle")

        tk.Label(center_panel, text="EXIT  ↑", bg=panel, fg=self.theme["accent"], font=(self.ui_font_family, 17, "bold")).pack(pady=(0, 6))

        grid_frame = tk.Frame(center_panel, bg=panel)
        grid_frame.pack(expand=True)
        for row in range(EDIT_HEIGHT):
            button_row: List[tk.Button] = []
            for col in range(EDIT_WIDTH):
                button = tk.Button(
                    grid_frame,
                    text="",
                    command=lambda r=row, c=col: self.set_cell(r, c),
                    width=7,
                    height=2,
                    relief=tk.FLAT,
                    bd=0,
                    font=(self.ui_font_family, 30, "bold"),
                )
                button.grid(row=row, column=col, padx=12, pady=8, ipadx=32, ipady=16)
                button_row.append(button)
            self.cell_buttons.append(button_row)

        tk.Label(center_panel, text="ENTRANCE  ↑", bg=panel, fg=self.theme["ok"], font=(self.ui_font_family, 17, "bold")).pack(pady=(6, 0))

    def current_mode(self) -> MapMode:
        return self.modes[self.selected_mode.get()]

    def pick_font_family(self) -> str:
        families = set(tkfont.families(self.window))
        for family in ("Noto Sans CJK SC", "Microsoft YaHei", "WenQuanYi Zen Hei", "Arial Unicode MS"):
            if family in families:
                return family
        return "DejaVu Sans"

    def select_color(self, value: int) -> None:
        self.selected_color.set(value)
        self.refresh()

    def set_cell(self, row: int, col: int) -> None:
        previous = self.edit_grid[row][col]
        next_value = int(self.selected_color.get())
        if previous == next_value:
            next_value = EMPTY

        candidate = [list(item) for item in self.edit_grid]
        candidate[row][col] = next_value
        try:
            validate_edit_grid(candidate, self.current_mode())
        except ValueError as exc:
            print(f"[map-editor] {exc}")
            return

        self.edit_grid = candidate
        self.refresh()

    def clear(self) -> None:
        self.edit_grid = empty_edit_grid()
        self.refresh()

    def send(self) -> None:
        try:
            validate_edit_grid(self.edit_grid, self.current_mode())
            full_grid = build_full_grid(self.edit_grid)
            payload = build_target_map_payload(self.current_mode().name, full_grid)
            sent = send_target_map_payload(payload, self.local_ip, self.target_ip, self.target_port)
        except Exception as exc:
            print(f"[map-editor] send failed: {exc}")
            self.set_send_button_state("failed")
            return

        print(f"[map-editor] sent {sent} bytes -> {self.target_ip}:{self.target_port}")
        self.set_send_button_state("sent")

    def refresh(self) -> None:
        selected = int(self.selected_color.get())
        if self.mode_box is not None:
            self.mode_box.configure(text=self.selected_mode.get())
        for row in range(EDIT_HEIGHT):
            for col in range(EDIT_WIDTH):
                value = int(self.edit_grid[row][col])
                button = self.cell_buttons[row][col]
                button.configure(
                    text=CELL_TEXT[value],
                    bg=CELL_COLORS[value],
                    fg=self.theme["text"],
                    activebackground=CELL_COLORS[value],
                    activeforeground=self.theme["text"],
                )
        selected_color = int(self.selected_color.get())
        for value, button in self.color_buttons.items():
            active = value == selected_color
            base_color = CELL_COLORS[value]
            button.configure(
                text=COLOR_NAMES[value],
                bg=CELL_ACTIVE_COLORS.get(value, base_color) if active else self.theme["panel_field"],
                activebackground=CELL_ACTIVE_COLORS.get(value, base_color),
                highlightbackground=CELL_ACTIVE_COLORS.get(value, base_color) if active else base_color,
                highlightcolor=CELL_ACTIVE_COLORS.get(value, base_color) if active else base_color,
                fg=self.theme["active_text"] if active else self.theme["text"],
            )

    def refresh_status_label(self) -> None:
        if self.status_label is not None and self.status_provider is not None:
            try:
                self.status_label.configure(text=self.status_provider())
            except Exception as exc:
                self.status_label.configure(text=f"HOST status unavailable: {exc}")
        if self.window.winfo_exists():
            self.window.after(500, self.refresh_status_label)

    def set_send_button_state(self, state: str) -> None:
        if self.send_button is None:
            return
        if self.send_reset_after_id is not None:
            try:
                self.window.after_cancel(self.send_reset_after_id)
            except tk.TclError:
                pass
            self.send_reset_after_id = None

        if state == "sent":
            self.send_button.configure(
                text="SENT",
                bg=self.theme["ok_dark"],
                activebackground=self.theme["ok"],
                fg=self.theme["active_text"],
            )
            self.send_reset_after_id = self.window.after(1200, lambda: self.set_send_button_state("idle"))
        elif state == "failed":
            self.send_button.configure(
                text="FAILED",
                bg=self.theme["danger_bg"],
                activebackground=self.theme["danger"],
                fg=self.theme["active_text"],
            )
            self.send_reset_after_id = self.window.after(1600, lambda: self.set_send_button_state("idle"))
        else:
            self.send_button.configure(
                text="SEND MAP",
                bg=self.theme["accent_bg"],
                activebackground=self.theme["accent"],
                fg=self.theme["text"],
            )

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

    def handle_screen_touch(self, screen_x: float, screen_y: float) -> bool:
        if not self.window.winfo_exists():
            return False
        abs_x = self.parent.winfo_rootx() + int(screen_x)
        abs_y = self.parent.winfo_rooty() + int(screen_y)

        if self.cancel_button is not None and self.widget_contains(self.cancel_button, abs_x, abs_y):
            self.clear()
            return True
        if self.clear_button is not None and self.widget_contains(self.clear_button, abs_x, abs_y):
            self.clear()
            return True
        if self.send_button is not None and self.widget_contains(self.send_button, abs_x, abs_y):
            self.send()
            return True
        if self.mode_box is not None and self.widget_contains(self.mode_box, abs_x, abs_y):
            self.cycle_mode()
            return True

        for value, button in self.color_buttons.items():
            if self.widget_contains(button, abs_x, abs_y):
                self.select_color(value)
                return True

        for row in range(EDIT_HEIGHT):
            for col in range(EDIT_WIDTH):
                button = self.cell_buttons[row][col]
                if self.widget_contains(button, abs_x, abs_y):
                    self.set_cell(row, col)
                    return True
        return self.widget_contains(self.window, abs_x, abs_y)

    def cycle_mode(self) -> None:
        current = self.selected_mode.get()
        index = self.mode_names.index(current) if current in self.mode_names else 0
        self.selected_mode.set(self.mode_names[(index + 1) % len(self.mode_names)])
        self.refresh()

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

    def begin_drag(self, event: tk.Event) -> None:
        self.drag_offset_x = int(event.x_root - self.window.winfo_x())
        self.drag_offset_y = int(event.y_root - self.window.winfo_y())

    def drag_window(self, event: tk.Event) -> None:
        x = int(event.x_root - self.drag_offset_x)
        y = int(event.y_root - self.drag_offset_y)
        self.window.geometry(f"+{x}+{y}")

    def cancel(self) -> None:
        if self.on_close is not None:
            self.on_close()
        self.window.destroy()
