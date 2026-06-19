#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
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
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.parent = parent
        self.theme = theme
        self.local_ip = local_ip
        self.target_ip = target_ip
        self.target_port = int(target_port)
        self.origin = origin
        self.on_close = on_close
        self.modes = load_map_modes()
        self.mode_names = list(self.modes)
        self.selected_mode = tk.StringVar(value=self.mode_names[0])
        self.selected_color = tk.IntVar(value=RED)
        self.edit_grid = empty_edit_grid()
        self.cell_buttons: List[List[tk.Button]] = []
        self.color_buttons: Dict[int, tk.Radiobutton] = {}
        self.mode_box: ttk.Combobox | None = None
        self.clear_button: tk.Button | None = None
        self.send_button: tk.Button | None = None
        self.cancel_button: tk.Button | None = None
        self.window = tk.Toplevel(parent)
        self.window.title("Target Map Editor")
        self.window.configure(bg=self.theme["bg"])
        self.window.transient(parent)
        self.window.overrideredirect(True)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.resizable(False, False)

        self.status_var = tk.StringVar(value="选择颜色后点击格子")
        self.counter_var = tk.StringVar(value="")
        self.color_hint_var = tk.StringVar(value="")
        self.color_hint_label: tk.Label | None = None
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.target_x = 0
        self.target_y = 0
        self.target_width = 640
        self.target_height = 700

        self.build_ui()
        self.refresh()
        self.center_window()
        self.animate_in()

    def build_ui(self) -> None:
        surface = self.theme["surface"]
        panel = self.theme["panel_dark"]
        line = self.theme["line"]
        text = self.theme["text"]
        muted = self.theme["muted"]

        outer = tk.Frame(self.window, bg=self.theme["bg"], padx=24, pady=24)
        outer.pack(fill=tk.BOTH, expand=True)

        card = tk.Frame(outer, bg=panel, highlightthickness=2, highlightbackground=line, padx=28, pady=20)
        card.pack(fill=tk.BOTH, expand=True)

        title_bar = tk.Frame(card, bg=panel)
        title_bar.pack(fill=tk.X)
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
            font=("DejaVu Sans", 22, "bold"),
        ).pack(side=tk.LEFT)
        self.cancel_button = tk.Button(
            title_bar,
            text="临时退出",
            command=self.cancel,
            bg=surface,
            fg=muted,
            activebackground=self.theme["surface_alt"],
            activeforeground=text,
            relief=tk.FLAT,
            padx=18,
            pady=10,
        )
        self.cancel_button.pack(side=tk.RIGHT)

        control = tk.Frame(card, bg=panel, pady=18)
        control.pack(fill=tk.X)
        tk.Label(control, text="子模式", bg=panel, fg=muted, font=("DejaVu Sans", 16, "bold")).pack(side=tk.LEFT)
        self.mode_box = ttk.Combobox(control, values=self.mode_names, textvariable=self.selected_mode, state="readonly", width=24)
        self.mode_box.pack(side=tk.LEFT, padx=(16, 52), ipady=13)
        self.mode_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        for value, label, color in (
            (GRAY, "灰", CELL_COLORS[GRAY]),
            (BLUE, "蓝", CELL_COLORS[BLUE]),
            (RED, "红", CELL_COLORS[RED]),
        ):
            button = tk.Radiobutton(
                control,
                text=label,
                value=value,
                variable=self.selected_color,
                bg=panel,
                fg=text,
                selectcolor=surface,
                activebackground=panel,
                activeforeground=text,
                indicatoron=False,
                width=9,
                padx=18,
                pady=15,
                relief=tk.FLAT,
                highlightthickness=3,
                highlightbackground=color,
                command=lambda v=value: self.select_color(v),
            )
            button.pack(side=tk.LEFT, padx=15)
            self.color_buttons[value] = button

        self.color_hint_label = tk.Label(
            card,
            textvariable=self.color_hint_var,
            bg=CELL_COLORS[RED],
            fg=self.theme["text"],
            font=("DejaVu Sans", 16, "bold"),
            padx=14,
            pady=10,
        )
        self.color_hint_label.pack(fill=tk.X, pady=(0, 10))

        tk.Label(card, text="EXIT  ↑", bg=panel, fg=self.theme["accent"], font=("DejaVu Sans", 17, "bold")).pack(pady=(2, 7))

        grid_frame = tk.Frame(card, bg=panel)
        grid_frame.pack()
        for row in range(EDIT_HEIGHT):
            button_row: List[tk.Button] = []
            for col in range(EDIT_WIDTH):
                button = tk.Button(
                    grid_frame,
                    text="",
                    command=lambda r=row, c=col: self.set_cell(r, c),
                    width=11,
                    height=3,
                    relief=tk.FLAT,
                    bd=0,
                    font=("DejaVu Sans", 28, "bold"),
                )
                button.grid(row=row, column=col, padx=16, pady=8, ipadx=28, ipady=10)
                button_row.append(button)
            self.cell_buttons.append(button_row)

        tk.Label(card, text="ENTRANCE  ↓", bg=panel, fg=self.theme["ok"], font=("DejaVu Sans", 17, "bold")).pack(pady=(7, 9))

        tk.Label(card, textvariable=self.counter_var, bg=panel, fg=muted, font=("DejaVu Sans Mono", 14)).pack()
        tk.Label(card, textvariable=self.status_var, bg=panel, fg=self.theme["warning"], font=("DejaVu Sans", 13)).pack(pady=(7, 12))

        footer = tk.Frame(card, bg=panel)
        footer.pack(fill=tk.X)
        self.clear_button = tk.Button(
            footer,
            text="清空",
            command=self.clear,
            bg=self.theme["warn_bg"],
            fg=text,
            activebackground=self.theme["warning"],
            activeforeground=text,
            relief=tk.FLAT,
            padx=36,
            pady=14,
        )
        self.clear_button.pack(side=tk.LEFT)
        self.send_button = tk.Button(
            footer,
            text="发送地图",
            command=self.send,
            bg=self.theme["accent_bg"],
            fg=text,
            activebackground=self.theme["accent"],
            activeforeground=text,
            relief=tk.FLAT,
            padx=42,
            pady=14,
        )
        self.send_button.pack(side=tk.RIGHT)

    def current_mode(self) -> MapMode:
        return self.modes[self.selected_mode.get()]

    def select_color(self, value: int) -> None:
        self.selected_color.set(value)
        self.status_var.set(f"当前颜色: {COLOR_NAMES[value]}")
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
            self.status_var.set(str(exc))
            return

        self.edit_grid = candidate
        self.status_var.set("地图已更新")
        self.refresh()

    def clear(self) -> None:
        self.edit_grid = empty_edit_grid()
        self.status_var.set("地图已清空")
        self.refresh()

    def send(self) -> None:
        try:
            validate_edit_grid(self.edit_grid, self.current_mode())
            full_grid = build_full_grid(self.edit_grid)
            payload = build_target_map_payload(self.current_mode().name, full_grid)
            sent = send_target_map_payload(payload, self.local_ip, self.target_ip, self.target_port)
        except Exception as exc:
            self.status_var.set(f"发送失败: {exc}")
            return

        self.status_var.set(f"已发送 {sent} bytes -> {self.target_ip}:{self.target_port}")

    def refresh(self) -> None:
        counts = count_cells(self.edit_grid)
        mode = self.current_mode()
        selected = int(self.selected_color.get())
        self.color_hint_var.set(f"当前颜色：{COLOR_NAMES[selected]}")
        if self.color_hint_label is not None:
            self.color_hint_label.configure(bg=CELL_COLORS[selected])
        self.counter_var.set(
            f"红 {counts[RED]}/{mode.red_max}   蓝 {counts[BLUE]}/{mode.blue_max}   灰 {counts[GRAY]}/{mode.gray_max}"
        )
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
        start_width = max(96, int(self.target_width * 0.12))
        start_height = max(72, int(self.target_height * 0.10))
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
            self.cancel()
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
        self.status_var.set(f"模式: {self.selected_mode.get()}")
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
            self.window.attributes("-alpha", 0.0)
        except tk.TclError:
            self.window.geometry(f"{self.target_width}x{self.target_height}+{self.target_x}+{self.target_y}")
            return

        start = time.perf_counter()
        duration = 0.08

        def step() -> None:
            elapsed = time.perf_counter() - start
            progress = min(1.0, elapsed / duration)
            eased = 1.0 - (1.0 - progress) ** 3
            alpha = eased
            start_width = max(96, int(self.target_width * 0.12))
            start_height = max(72, int(self.target_height * 0.10))
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
