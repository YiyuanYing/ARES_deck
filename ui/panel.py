#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import queue
import statistics
import time
import tkinter as tk
import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from core.protocol import BUTTON_IDS, BUTTON_NAMES
from core.udp_sender import ControllerUdpSender
from ui.config import (
    AXIS_MAP,
    BASE_HEIGHT,
    BASE_WIDTH,
    CALIBRATION_SECONDS,
    DEFAULT_BUTTON_ACTIVATION_MODE,
    DEADZONE,
    DEVICE_PATH,
    DISPLAY_BUTTON_MAP,
    FOOTER_TOUCH_BUTTONS,
    JS_EVENT_AXIS,
    JS_EVENT_BUTTON,
    JS_EVENT_INIT,
    MAP_EDITOR_TRIGGER_BUTTON_ID,
    OUTPUT_PHYSICAL_BUTTON_IDS,
    REFRESH_MS,
    RESET_PULSE_SECONDS,
    UI_COLOR_THEME,
    UI_COLOR_THEMES,
    VIRTUAL_BUTTON_IDS,
    VIRTUAL_BUTTON_MAP,
)
from ui.inputs import HostReachabilityMonitor, JoystickReader, TouchReader
from ui.map_editor import TargetMapEditorDialog

THEME = UI_COLOR_THEMES.get(UI_COLOR_THEME, UI_COLOR_THEMES["burgundy"])
BG = THEME["bg"]
SURFACE = THEME["surface"]
SURFACE_ALT = THEME["surface_alt"]
LINE = THEME["line"]
TEXT = THEME["text"]
MUTED = THEME["muted"]
GREEN = THEME["ok"]
GREEN_DARK = THEME["ok_dark"]
ACTIVE_GLOW = THEME["active_glow"]
ACTIVE_TEXT = THEME["active_text"]
YELLOW = THEME["warning"]
RED = THEME["danger"]
BLUE = THEME["accent"]
PANEL_DARK = THEME["panel_dark"]
PANEL_FIELD = THEME["panel_field"]
STICK_BG = THEME["stick_bg"]
WARN_BG = THEME["warn_bg"]
ACCENT_BG = THEME["accent_bg"]
DANGER_BG = THEME["danger_bg"]
BUTTON_IDLE = THEME["button_idle"]
BUTTON_PRESSED = THEME["button_pressed"]
BUTTON_IDLE_OUTLINE = THEME["button_idle_outline"]
TITLE_RAINBOW = (
    "#ff5d73",
    "#ff9f5d",
    "#e7d95e",
    "#72e58c",
    "#78d7ff",
    "#8fb4ff",
    "#d18cff",
)
TITLE_PIXEL_SHADOW = "#2a0d18"
TITLE_PIXEL_FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
}


def blend_color(color_a: str, color_b: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    a = color_a.lstrip("#")
    b = color_b.lstrip("#")
    rgb = []
    for index in range(0, 6, 2):
        value_a = int(a[index : index + 2], 16)
        value_b = int(b[index : index + 2], 16)
        rgb.append(round(value_a + (value_b - value_a) * ratio))
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def on_button_toggled(button_id: int, name: str, state: bool) -> None:
    """TODO: 后续在这里加入机器人控制指令发送逻辑。"""
    print(f"[button] {button_id:02d} {name} toggled -> {state}")


def on_axis_updated(axis_id: int, value: float) -> None:
    """TODO: 后续在这里加入摇杆控制指令发送逻辑。当前只保留接口。"""
    _ = axis_id, value


@dataclass
class ControllerState:
    """GUI 主线程维护的手柄状态。"""

    button_physical: Dict[int, bool] = field(default_factory=lambda: {i: False for i in OUTPUT_PHYSICAL_BUTTON_IDS})
    button_toggle: Dict[int, bool] = field(default_factory=lambda: {i: False for i in OUTPUT_PHYSICAL_BUTTON_IDS})
    virtual_button_toggle: Dict[int, bool] = field(default_factory=lambda: {i: False for i in VIRTUAL_BUTTON_IDS})
    raw_axes: Dict[int, int] = field(default_factory=lambda: {i: 0 for i in AXIS_MAP})
    axis_values: Dict[int, float] = field(default_factory=lambda: {i: 0.0 for i in AXIS_MAP})
    center_offsets: Dict[int, float] = field(default_factory=lambda: {i: 0.0 for i in AXIS_MAP})
    connected: bool = False
    status_text: str = f"{DEVICE_PATH} disconnected"
    status_is_error: bool = True
    touch_connected: bool = False
    touch_status_text: str = "TOUCH disabled"
    touch_status_is_error: bool = False

class ControllerPanel:
    def __init__(
        self,
        local_ip: str,
        remote_ip: str,
        udp_port: int,
        map_message_port: int,
        send_hz: float,
        failsafe_timeout_ms: int,
        touch_device: str,
        no_touch_reader: bool,
        touch_swap_xy: bool,
        touch_invert_x: bool,
        touch_invert_y: bool,
        debug_touch: bool,
        virtual_button_mode_default: str = DEFAULT_BUTTON_ACTIVATION_MODE,
        virtual_button_modes: Dict[int, str] | None = None,
        physical_button_mode_default: str = DEFAULT_BUTTON_ACTIVATION_MODE,
        physical_button_modes: Dict[int, str] | None = None,
    ) -> None:
        self.root = tk.Tk()
        self.root.title("SUSTECH-ARES ROBOCON2026")
        self.root.configure(bg=BG)
        self.root.geometry(f"{BASE_WIDTH}x{BASE_HEIGHT}")
        self.fullscreen = True
        self.root.attributes("-fullscreen", self.fullscreen)

        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.state = ControllerState()
        self.event_queue: "queue.Queue[Tuple]" = queue.Queue()
        self.reader = JoystickReader(DEVICE_PATH, self.event_queue)
        self.touch_canvas_width = BASE_WIDTH
        self.touch_canvas_height = BASE_HEIGHT
        self.touch_reader = None
        if no_touch_reader:
            self.state.touch_status_text = "TOUCH disabled"
            print("[touch] TOUCH disabled by --no-touch-reader")
        else:
            self.touch_reader = TouchReader(
                touch_device,
                self.event_queue,
                swap_xy=touch_swap_xy,
                invert_x=touch_invert_x,
                invert_y=touch_invert_y,
                debug_touch=debug_touch,
                screen_size_provider=self.get_touch_canvas_size,
            )
        self.host_monitor = HostReachabilityMonitor(remote_ip)
        self.local_ip = local_ip
        self.remote_ip = remote_ip
        self.map_message_port = int(map_message_port)
        self.map_editor_dialog: TargetMapEditorDialog | None = None
        self.udp_sender = ControllerUdpSender(
            state_provider=self.get_controller_snapshot,
            local_ip=local_ip,
            target_ip=remote_ip,
            target_port=udp_port,
            send_hz=send_hz,
            failsafe_timeout_ms=failsafe_timeout_ms,
        )

        self.calibrating = False
        self.debug_touch = debug_touch
        self.calibration_deadline = 0.0
        self.calibration_samples: Dict[int, List[int]] = {i: [] for i in AXIS_MAP}
        self.virtual_button_until: Dict[int, float] = {}
        self.active_touch_target = ""
        self.virtual_button_mode_default = virtual_button_mode_default
        self.virtual_button_modes = dict(virtual_button_modes or {})
        self.physical_button_mode_default = physical_button_mode_default
        self.physical_button_modes = dict(physical_button_modes or {})
        self.button_light_levels: Dict[Tuple[str, int], float] = {}
        self.last_animation_at = time.monotonic()

        self.root.bind("<F11>", self.toggle_fullscreen)
        self.root.bind("<Control-q>", self.exit_program)
        self.root.bind("<r>", self.reset_toggles)
        self.root.bind("<R>", self.reset_toggles)
        self.root.bind("<c>", self.recalibrate_axes)
        self.root.bind("<C>", self.recalibrate_axes)
        self.canvas.bind("<ButtonPress-1>", self.handle_canvas_press)
        self.canvas.bind("<B1-Motion>", self.handle_canvas_press)
        self.canvas.bind("<ButtonRelease-1>", self.handle_canvas_release)
        self.root.protocol("WM_DELETE_WINDOW", self.exit_program)

    def run(self) -> None:
        self.reader.start()
        if self.touch_reader is not None:
            self.touch_reader.start()
        self.host_monitor.start()
        self.udp_sender.start()
        self.begin_calibration("startup")
        self.root.after(REFRESH_MS, self.update_loop)
        self.root.mainloop()

    def exit_program(self, _event: tk.Event | None = None) -> None:
        print("[exit] closing controller panel")
        self.udp_sender.stop()
        self.host_monitor.stop()
        self.reader.stop()
        if self.touch_reader is not None:
            self.touch_reader.stop()
            self.touch_reader.join(timeout=1.0)
        self.host_monitor.join(timeout=1.0)
        self.reader.join(timeout=1.0)
        self.root.destroy()

    def toggle_fullscreen(self, _event: tk.Event | None = None) -> None:
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)
        mode = "enabled" if self.fullscreen else "disabled"
        print(f"[ui] fullscreen {mode}")

    def get_touch_canvas_size(self) -> Tuple[int, int]:
        return self.touch_canvas_width, self.touch_canvas_height

    def handle_canvas_press(self, event: tk.Event) -> None:
        if self.state.touch_connected:
            return
        self.handle_canvas_touch_xy(float(event.x), float(event.y), source="mouse")

    def handle_canvas_release(self, event: tk.Event) -> None:
        _ = event
        if self.state.touch_connected:
            return
        self.release_active_touch_target()

    def handle_canvas_touch_xy(self, screen_x: float, screen_y: float, source: str = "touch") -> None:
        if self.map_editor_dialog is not None:
            try:
                if self.map_editor_dialog.handle_screen_touch(screen_x, screen_y):
                    if self.debug_touch:
                        print(f"[touch] {source} hit map editor at ({screen_x:.1f},{screen_y:.1f})")
                    return
            except tk.TclError:
                self.map_editor_dialog = None

        sx, sy, _s = self.scale()
        base_x = screen_x / sx
        base_y = screen_y / sy

        for button_id, spec in VIRTUAL_BUTTON_MAP.items():
            x1 = spec["x"]
            y1 = spec["y"]
            x2 = x1 + spec["w"]
            y2 = y1 + spec["h"]
            if x1 <= base_x <= x2 and y1 <= base_y <= y2:
                target = f"virtual:{button_id}"
                if self.touch_already_handled(target):
                    return
                self.open_map_editor_for_button(button_id)
                self.press_virtual_button(button_id)
                if self.debug_touch:
                    print(f"[touch] {source} hit {target} at ({screen_x:.1f},{screen_y:.1f})")
                self.redraw_now()
                return

        for action, spec in FOOTER_TOUCH_BUTTONS.items():
            x1 = spec["x"]
            y1 = spec["y"]
            x2 = x1 + spec["w"]
            y2 = y1 + spec["h"]
            if x1 <= base_x <= x2 and y1 <= base_y <= y2:
                target = f"footer:{action}"
                if self.touch_already_handled(target):
                    return
                if action == "clear_estop":
                    self.trigger_clear_estop()
                    self.redraw_now()
                elif action == "exit_fullscreen":
                    self.toggle_fullscreen()
                    self.redraw_now()
                elif action == "exit_app":
                    self.exit_program()
                if self.debug_touch:
                    print(f"[touch] {source} hit {target} at ({screen_x:.1f},{screen_y:.1f})")
                return

    def touch_already_handled(self, target: str) -> bool:
        if self.active_touch_target:
            return True
        self.active_touch_target = target
        return False

    def release_active_touch_target(self) -> None:
        target = self.active_touch_target
        self.active_touch_target = ""
        if not target.startswith("virtual:"):
            return

        try:
            button_id = int(target.split(":", 1)[1])
        except ValueError:
            return
        if self.virtual_button_mode(button_id) != "momentary":
            return

        self.state.virtual_button_toggle[button_id] = False
        spec = VIRTUAL_BUTTON_MAP.get(button_id, {})
        button_name = spec.get("name", BUTTON_NAMES.get(button_id, f"BUTTON_{button_id}"))
        print(f"[virtual] {button_id:02d} {button_name} momentary -> False")
        self.redraw_now()

    def redraw_now(self) -> None:
        self.draw()
        self.canvas.update_idletasks()

    def virtual_button_mode(self, button_id: int) -> str:
        spec = VIRTUAL_BUTTON_MAP.get(button_id, {})
        mode = self.virtual_button_modes.get(button_id, spec.get("mode", self.virtual_button_mode_default))
        return mode if mode in {"toggle", "momentary"} else DEFAULT_BUTTON_ACTIVATION_MODE

    def physical_button_mode(self, button_id: int) -> str:
        mode = self.physical_button_modes.get(button_id, self.physical_button_mode_default)
        return mode if mode in {"toggle", "momentary"} else DEFAULT_BUTTON_ACTIVATION_MODE

    def press_virtual_button(self, button_id: int) -> None:
        if self.virtual_button_mode(button_id) == "momentary":
            self.set_virtual_button(button_id, True, "momentary")
            return
        self.toggle_virtual_button(button_id)

    def open_map_editor_for_button(self, button_id: int) -> None:
        if MAP_EDITOR_TRIGGER_BUTTON_ID is None:
            return
        if int(button_id) != int(MAP_EDITOR_TRIGGER_BUTTON_ID):
            return
        self.open_map_editor()

    def open_map_editor(self) -> None:
        if self.map_editor_dialog is not None:
            try:
                self.map_editor_dialog.window.lift()
                return
            except tk.TclError:
                self.map_editor_dialog = None
        self.map_editor_dialog = TargetMapEditorDialog(
            self.root,
            theme=THEME,
            local_ip=self.local_ip,
            target_ip=self.remote_ip,
            target_port=self.map_message_port,
            on_close=self.clear_map_editor_reference,
        )

    def clear_map_editor_reference(self) -> None:
        self.map_editor_dialog = None

    def set_virtual_button(self, button_id: int, state: bool, reason: str) -> None:
        if self.state.virtual_button_toggle.get(button_id, False) == state:
            return
        self.state.virtual_button_toggle[button_id] = state
        spec = VIRTUAL_BUTTON_MAP.get(button_id, {})
        button_name = spec.get("name", BUTTON_NAMES.get(button_id, f"BUTTON_{button_id}"))
        print(f"[virtual] {button_id:02d} {button_name} {reason} -> {state}")

    def toggle_virtual_button(self, button_id: int) -> None:
        new_state = not self.state.virtual_button_toggle.get(button_id, False)
        self.set_virtual_button(button_id, new_state, "toggled")

    def trigger_clear_estop(self) -> None:
        estop_button_id = BUTTON_IDS["VIRTUAL_ESTOP"]
        reset_button_id = BUTTON_IDS["VIRTUAL_RESET"]
        steam_button_id = BUTTON_IDS["STEAM"]
        self.state.virtual_button_toggle[estop_button_id] = False
        self.state.virtual_button_toggle[reset_button_id] = False
        self.state.button_toggle[steam_button_id] = False
        self.virtual_button_until[reset_button_id] = time.monotonic() + max(RESET_PULSE_SECONDS, 0.75)
        print("[safety] local ESTOP sources cleared; VIRTUAL_RESET pulse sent to clear ESTOP latch")

    def reset_toggles(self, _event: tk.Event | None = None) -> None:
        for button_id in self.state.button_toggle:
            self.state.button_toggle[button_id] = False
        for button_id in self.state.virtual_button_toggle:
            self.state.virtual_button_toggle[button_id] = False
        print("[button] all toggle states cleared")

    def recalibrate_axes(self, _event: tk.Event | None = None) -> None:
        self.begin_calibration("manual")

    def begin_calibration(self, reason: str) -> None:
        self.calibrating = True
        self.calibration_deadline = time.monotonic() + CALIBRATION_SECONDS
        self.calibration_samples = {i: [] for i in AXIS_MAP}
        print(f"[axis] calibration started ({reason})")

    def finish_calibration_if_needed(self) -> None:
        if not self.calibrating or time.monotonic() < self.calibration_deadline:
            return

        for axis_id in AXIS_MAP:
            samples = self.calibration_samples.get(axis_id, [])
            if samples:
                self.state.center_offsets[axis_id] = float(statistics.median(samples))
            else:
                # 如果 1 秒内没有新事件，使用当前 raw 值作为中位偏移。
                self.state.center_offsets[axis_id] = float(self.state.raw_axes.get(axis_id, 0))

        self.calibrating = False
        offsets = ", ".join(f"{axis}:{self.state.center_offsets[axis]:.0f}" for axis in AXIS_MAP)
        print(f"[axis] calibration finished, center offsets: {offsets}")
        self.update_all_axis_values()

    def update_loop(self) -> None:
        self.process_events()
        self.finish_calibration_if_needed()
        self.draw()
        self.root.after(REFRESH_MS, self.update_loop)

    def get_controller_snapshot(self) -> dict:
        # UDP 发送锁存状态：实体键沿用按一下切换一次，屏幕虚拟键用中间大按钮切换。
        # 边缘实体键绿色只表示当前 physical pressed，不影响原有实体键锁存发送逻辑。
        now = time.monotonic()
        buttons = {
            button_id: self.state.button_toggle.get(button_id, False)
            for button_id in OUTPUT_PHYSICAL_BUTTON_IDS
        }
        buttons.update(
            {button_id: self.state.virtual_button_toggle.get(button_id, False) for button_id in VIRTUAL_BUTTON_IDS}
        )
        expired_virtual_buttons = []
        for button_id, active_until in self.virtual_button_until.items():
            active = now <= active_until
            buttons[button_id] = active
            if not active:
                expired_virtual_buttons.append(button_id)
        for button_id in expired_virtual_buttons:
            self.virtual_button_until.pop(button_id, None)

        return {
            "axes": {
                "lx": self.state.axis_values.get(0, 0.0),
                "ly": self.state.axis_values.get(1, 0.0),
                "rx": self.state.axis_values.get(2, 0.0),
                "ry": self.state.axis_values.get(3, 0.0),
            },
            "buttons": buttons,
            "enable": True,
            "estop": False,
        }

    def process_events(self) -> None:
        while True:
            try:
                item = self.event_queue.get_nowait()
            except queue.Empty:
                break

            kind = item[0]
            if kind == "device_status":
                _kind, connected, message = item
                self.state.connected = bool(connected)
                self.state.status_text = str(message)
                self.state.status_is_error = not connected
                continue

            if kind == "touch_status":
                _kind, connected, message, is_error = item
                self.state.touch_connected = bool(connected)
                self.state.touch_status_text = str(message)
                self.state.touch_status_is_error = bool(is_error)
                continue

            if kind == "touch_press":
                _kind, screen_x, screen_y = item
                self.handle_canvas_touch_xy(float(screen_x), float(screen_y), source="evdev")
                continue

            if kind == "touch_release":
                self.release_active_touch_target()
                continue

            if kind != "js_event":
                continue

            _kind, _event_time, value, raw_type, number = item
            is_init = bool(raw_type & JS_EVENT_INIT)
            event_type = raw_type & ~JS_EVENT_INIT

            if event_type == JS_EVENT_BUTTON:
                self.handle_button_event(number, value, is_init=is_init)
            elif event_type == JS_EVENT_AXIS:
                self.handle_axis_event(number, value)

    def handle_button_event(self, button_id: int, value: int, is_init: bool = False) -> None:
        if button_id not in OUTPUT_PHYSICAL_BUTTON_IDS:
            return

        was_pressed = self.state.button_physical.get(button_id, False)
        is_pressed = value != 0
        self.state.button_physical[button_id] = is_pressed

        # 初始化事件只同步当前物理状态，不视为一次真实按下。
        if is_init:
            if self.physical_button_mode(button_id) == "momentary":
                self.state.button_toggle[button_id] = is_pressed
            return

        mode = self.physical_button_mode(button_id)
        button_name = DISPLAY_BUTTON_MAP.get(button_id, {}).get("name", BUTTON_NAMES.get(button_id, f"BUTTON_{button_id}"))
        if is_pressed and not was_pressed:
            self.open_map_editor_for_button(button_id)
        if mode == "momentary":
            if self.state.button_toggle.get(button_id, False) != is_pressed:
                self.state.button_toggle[button_id] = is_pressed
                on_button_toggled(button_id, button_name, is_pressed)
                self.redraw_now()
            return

        # Toggle 模式只在 0 -> 1 上升沿切换状态，松开时不改变绿色显示。
        if is_pressed and not was_pressed:
            new_state = not self.state.button_toggle[button_id]
            self.state.button_toggle[button_id] = new_state
            on_button_toggled(button_id, button_name, new_state)
            self.redraw_now()

    def handle_axis_event(self, axis_id: int, raw_value: int) -> None:
        if axis_id not in AXIS_MAP:
            return

        self.state.raw_axes[axis_id] = raw_value
        if self.calibrating:
            self.calibration_samples[axis_id].append(raw_value)

        normalized = self.normalize_axis(axis_id, raw_value)
        self.state.axis_values[axis_id] = normalized
        on_axis_updated(axis_id, normalized)

    def update_all_axis_values(self) -> None:
        for axis_id, raw_value in self.state.raw_axes.items():
            self.state.axis_values[axis_id] = self.normalize_axis(axis_id, raw_value)

    def normalize_axis(self, axis_id: int, raw_value: int) -> float:
        # 中位校准 + 死区处理，与 jstest 的轴编号保持一致。
        raw_corrected = raw_value - self.state.center_offsets.get(axis_id, 0.0)
        normalized = max(-1.0, min(1.0, raw_corrected / 32767.0))
        if abs(normalized) < DEADZONE:
            return 0.0
        return normalized

    def scale(self) -> Tuple[float, float, float]:
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        sx = width / BASE_WIDTH
        sy = height / BASE_HEIGHT
        return sx, sy, min(sx, sy)

    def x(self, value: float) -> float:
        sx, _sy, _s = self.scale()
        return value * sx

    def y(self, value: float) -> float:
        _sx, sy, _s = self.scale()
        return value * sy

    def draw(self) -> None:
        self.update_animation_clock()
        self.canvas.delete("all")
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        self.touch_canvas_width = max(width, 1)
        self.touch_canvas_height = max(height, 1)
        self.canvas.create_rectangle(0, 0, width, height, fill=BG, outline="")

        self.draw_header()
        self.draw_edge_guides()
        self.draw_axis_widgets()
        self.draw_virtual_buttons()

        for button_id, spec in DISPLAY_BUTTON_MAP.items():
            self.draw_button(button_id, spec)

        self.draw_footer()

    def update_animation_clock(self) -> None:
        now = time.monotonic()
        self.animation_dt = min(max(now - self.last_animation_at, 0.0), 0.05)
        self.last_animation_at = now

    def button_light_level(self, kind: str, button_id: int, active: bool) -> float:
        key = (kind, button_id)
        current = self.button_light_levels.get(key, 0.0)
        target = 1.0 if active else 0.0
        step = self.animation_dt / 0.08
        if current < target:
            current = min(target, current + step)
        elif current > target:
            current = max(target, current - step)

        if current <= 0.0 and not active:
            self.button_light_levels.pop(key, None)
        else:
            self.button_light_levels[key] = current
        return current

    @staticmethod
    def ease_light(value: float) -> float:
        value = max(0.0, min(1.0, value))
        return value * value * (3.0 - 2.0 * value)

    def draw_header(self) -> None:
        device_color = GREEN if self.state.connected else RED
        metrics = self.udp_sender.snapshot_metrics()
        host_reachable, host_checked_at = self.host_monitor.snapshot()
        host_fresh = host_checked_at > 0.0 and time.monotonic() - host_checked_at <= 2.5
        host_ok = host_reachable and host_fresh
        host_color = GREEN if host_ok else RED
        if host_ok:
            host_text = f"HOST connected -> {metrics.target_ip}:{metrics.target_port}"
        elif not host_fresh:
            host_text = f"HOST checking -> {metrics.target_ip}:{metrics.target_port}"
            host_color = YELLOW
        else:
            host_text = f"HOST disconnected -> {metrics.target_ip}:{metrics.target_port}"
        device_text = self.state.status_text.splitlines()[0]
        self.rounded_rect(28, 24, 1252, 126, 8, fill=SURFACE, outline=LINE, width=2)
        self.draw_rainbow_title(54, 48, "SUSTECH-ARES")
        self.canvas.create_text(
            self.x(54),
            self.y(86),
            text="ROBOCON 2026 CONTROL DECK",
            fill=MUTED,
            font=("DejaVu Sans", 13, "bold"),
            anchor="w",
        )
        self.draw_status_pill(404, 40, 374, "DEVICE", device_text, device_color)
        self.draw_status_pill(804, 40, 420, "LINK", host_text, host_color)
        if self.state.status_is_error:
            detail_text = "sudo usermod -aG input $USER    sudo reboot"
            detail_color = RED
        elif self.calibrating:
            detail_text = "Calibrating stick centers..."
            detail_color = YELLOW
        else:
            if self.state.touch_connected:
                touch_color = GREEN
            elif self.state.touch_status_is_error:
                touch_color = RED
            else:
                touch_color = YELLOW
            detail_text = self.state.touch_status_text[:96]
            detail_color = touch_color
        self.canvas.create_text(
            self.x(640),
            self.y(118),
            text=detail_text,
            fill=detail_color,
            font=("DejaVu Sans Mono", 11),
        )

    def draw_rainbow_title(self, x: float, y: float, text: str) -> None:
        # Pixel-arcade title: the glyphs are made of blocks, and color flows
        # through those blocks instead of trailing outside the text.
        pixel = 4
        gap = 1
        char_gap = 4
        char_width = 5 * pixel + 4 * gap + char_gap
        top = y - 18
        phase = time.monotonic() * 6.0

        for char_index, char in enumerate(text):
            glyph = TITLE_PIXEL_FONT.get(char.upper())
            if glyph is None:
                continue
            char_x = x + char_index * char_width
            for row_index, row in enumerate(glyph):
                for col_index, cell in enumerate(row):
                    if cell != "1":
                        continue
                    px = char_x + col_index * (pixel + gap)
                    py = top + row_index * (pixel + gap)
                    color_index = int((char_index * 1.4 + col_index * 0.8 + row_index * 0.35 + phase) % len(TITLE_RAINBOW))
                    base = TITLE_RAINBOW[color_index]
                    shimmer = 0.5 + 0.5 * math.sin(phase + char_index * 0.8 + col_index * 0.9)
                    color = blend_color(base, ACTIVE_TEXT, shimmer * 0.22)
                    self.canvas.create_rectangle(
                        self.x(px + 2),
                        self.y(py + 2),
                        self.x(px + pixel + 2),
                        self.y(py + pixel + 2),
                        fill=TITLE_PIXEL_SHADOW,
                        outline="",
                    )
                    self.canvas.create_rectangle(
                        self.x(px),
                        self.y(py),
                        self.x(px + pixel),
                        self.y(py + pixel),
                        fill=color,
                        outline="",
                    )

    def draw_status_pill(self, x: float, y: float, width: float, title: str, value: str, color: str) -> None:
        self.rounded_rect(x, y, x + width, y + 54, 8, fill=PANEL_DARK, outline=LINE, width=2)
        self.circle(x + 20, y + 27, 5, fill=color, outline=color, width=1)
        self.canvas.create_text(
            self.x(x + 36),
            self.y(y + 18),
            text=title,
            fill=MUTED,
            font=("DejaVu Sans", 9, "bold"),
            anchor="w",
        )
        self.canvas.create_text(
            self.x(x + 36),
            self.y(y + 36),
            text=value[:46],
            fill=TEXT,
            font=("DejaVu Sans", 12, "bold"),
            anchor="w",
        )

    def draw_edge_guides(self) -> None:
        self.rounded_rect(24, 150, 148, 686, 8, fill=SURFACE, outline=LINE, width=2)
        self.rounded_rect(1132, 150, 1256, 686, 8, fill=SURFACE, outline=LINE, width=2)
        self.rounded_rect(162, 162, 1118, 586, 8, fill=PANEL_FIELD, outline=LINE, width=2)
        self.canvas.create_text(
            self.x(182),
            self.y(174),
            text="TOUCH ACTIONS",
            fill=MUTED,
            font=("DejaVu Sans", 11, "bold"),
            anchor="w",
        )

    def draw_axis_widgets(self) -> None:
        axes = self.state.axis_values
        self.draw_stick_widget(278, 654, "LEFT", axes.get(0, 0.0), axes.get(1, 0.0))
        self.draw_stick_widget(1002, 654, "RIGHT", axes.get(2, 0.0), axes.get(3, 0.0))

    def draw_stick_widget(self, cx: float, cy: float, label: str, ax: float, ay: float) -> None:
        self.rounded_rect(cx - 76, cy - 36, cx + 76, cy + 36, 8, fill=SURFACE, outline=LINE, width=2)
        self.circle(cx - 40, cy, 20, fill=STICK_BG, outline=LINE, width=2)
        self.canvas.create_line(self.x(cx - 60), self.y(cy), self.x(cx - 20), self.y(cy), fill=LINE, width=1)
        self.canvas.create_line(self.x(cx - 40), self.y(cy - 20), self.x(cx - 40), self.y(cy + 20), fill=LINE, width=1)
        self.circle(cx - 40 + ax * 15.0, cy + ay * 15.0, 5, fill=BLUE, outline=BLUE, width=1)
        self.canvas.create_text(
            self.x(cx - 2),
            self.y(cy - 10),
            text=label,
            fill=TEXT,
            font=("DejaVu Sans", 12, "bold"),
            anchor="w",
        )
        self.canvas.create_text(
            self.x(cx - 2),
            self.y(cy + 12),
            text=f"x={ax:+.2f}  y={ay:+.2f}",
            fill=MUTED,
            font=("DejaVu Sans Mono", 9),
            anchor="w",
        )

    def draw_virtual_buttons(self) -> None:
        for button_id, spec in VIRTUAL_BUTTON_MAP.items():
            active = self.state.virtual_button_toggle.get(button_id, False)
            light = self.ease_light(self.button_light_level("virtual", button_id, active))
            fill = blend_color(SURFACE_ALT, GREEN_DARK, light)
            pulse = self.active_pulse(button_id) * light
            outline = blend_color(LINE, blend_color(GREEN, ACTIVE_GLOW, pulse), light)
            if light > 0.02:
                self.rounded_rect(
                    spec["x"] - 5,
                    spec["y"] - 5,
                    spec["x"] + spec["w"] + 5,
                    spec["y"] + spec["h"] + 5,
                    spec["radius"] + 2,
                    fill="",
                    outline=blend_color(LINE, blend_color(GREEN_DARK, ACTIVE_GLOW, pulse), light),
                    width=2,
                )
            self.rounded_rect(
                spec["x"],
                spec["y"],
                spec["x"] + spec["w"],
                spec["y"] + spec["h"],
                spec["radius"],
                fill=fill,
                outline=outline,
                width=2 + round(light * 2),
            )
            self.canvas.create_text(
                self.x(spec["x"] + 18),
                self.y(spec["y"] + 20),
                text=f"{button_id}",
                fill=blend_color(MUTED, ACTIVE_TEXT, light),
                font=("DejaVu Sans Mono", 11, "bold"),
                anchor="w",
            )
            mode_label = "HOLD" if self.virtual_button_mode(button_id) == "momentary" else "TOGGLE"
            self.canvas.create_text(
                self.x(spec["x"] + spec["w"] - 18),
                self.y(spec["y"] + 20),
                text=mode_label,
                fill=blend_color(MUTED, ACTIVE_TEXT, light),
                font=("DejaVu Sans Mono", 10, "bold"),
                anchor="e",
            )
            self.canvas.create_text(
                self.x(spec["x"] + spec["w"] / 2),
                self.y(spec["y"] + spec["h"] / 2),
                text=spec["label"],
                fill=blend_color(TEXT, ACTIVE_TEXT, light),
                font=("DejaVu Sans", 21, "bold"),
                justify="center",
            )

    def draw_footer(self) -> None:
        for action, spec in FOOTER_TOUCH_BUTTONS.items():
            if action == "clear_estop":
                fill = WARN_BG
                outline = YELLOW
            elif action == "exit_fullscreen":
                fill = ACCENT_BG
                outline = BLUE
            else:
                fill = DANGER_BG
                outline = RED
            self.rounded_rect(
                spec["x"],
                spec["y"],
                spec["x"] + spec["w"],
                spec["y"] + spec["h"],
                8,
                fill=fill,
                outline=outline,
                width=2,
            )
            self.canvas.create_text(
                self.x(spec["x"] + spec["w"] / 2),
                self.y(spec["y"] + spec["h"] / 2),
                text=self.footer_button_label(action, spec),
                fill=TEXT,
                font=("DejaVu Sans", 13, "bold"),
            )

    def footer_button_label(self, action: str, spec: Dict) -> str:
        if action == "exit_fullscreen":
            return "EXIT FULLSCREEN" if self.fullscreen else "ENTER FULLSCREEN"
        return spec["label"]

    def draw_button(self, button_id: int, spec: Dict) -> None:
        toggled = self.state.button_toggle.get(button_id, False)
        pressed = self.state.button_physical.get(button_id, False)
        light = self.ease_light(self.button_light_level("physical", button_id, toggled))
        if light > 0.0:
            fill = blend_color(BUTTON_IDLE, GREEN_DARK, light)
            outline = blend_color(BUTTON_IDLE_OUTLINE, blend_color(GREEN, ACTIVE_GLOW, self.active_pulse(button_id) * light), light)
            width = 2 + round(light * 2)
        elif pressed:
            fill = BUTTON_PRESSED
            outline = BLUE
            width = 3
        else:
            fill = BUTTON_IDLE
            outline = BUTTON_IDLE_OUTLINE
            width = 2
        shape = spec["shape"]

        if shape == "circle":
            if light > 0.02:
                self.circle(spec["x"], spec["y"], spec["r"] + 5, fill="", outline=outline, width=2)
            self.circle(spec["x"], spec["y"], spec["r"], fill=fill, outline=outline, width=width)
        elif shape == "rounded_rect":
            if light > 0.02:
                self.rounded_rect(
                    spec["x"] - 4,
                    spec["y"] - 4,
                    spec["x"] + spec["w"] + 4,
                    spec["y"] + spec["h"] + 4,
                    min(spec.get("radius", 8), 8),
                    fill="",
                    outline=outline,
                    width=2,
                )
            self.rounded_rect(
                spec["x"],
                spec["y"],
                spec["x"] + spec["w"],
                spec["y"] + spec["h"],
                min(spec.get("radius", 8), 8),
                fill=fill,
                outline=outline,
                width=width,
            )

        self.draw_button_label(spec, light)

    def active_pulse(self, button_id: int) -> float:
        phase = time.monotonic() * 3.6 + button_id * 0.37
        return 0.5 + 0.5 * math.sin(phase)

    def draw_button_label(self, spec: Dict, light: float = 0.0) -> None:
        shape = spec["shape"]
        if shape == "circle":
            cx = spec["x"]
            cy = spec["y"]
            font_size = 16
        else:
            cx = spec["x"] + spec["w"] / 2
            cy = spec["y"] + spec["h"] / 2
            if spec["w"] < 35:
                font_size = 8
            elif spec["w"] < 60:
                font_size = 10
            elif spec["w"] < 90:
                font_size = 12
            else:
                font_size = 14

        self.canvas.create_text(
            self.x(cx),
            self.y(cy),
            text=spec["label"],
            fill=blend_color(TEXT, ACTIVE_TEXT, light),
            font=("DejaVu Sans", font_size, "bold"),
        )

    def circle(self, cx: float, cy: float, radius: float, **kwargs) -> None:
        sx, sy, s = self.scale()
        self.canvas.create_oval(
            cx * sx - radius * s,
            cy * sy - radius * s,
            cx * sx + radius * s,
            cy * sy + radius * s,
            **kwargs,
        )

    def rounded_rect(self, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs) -> None:
        sx, sy, s = self.scale()
        x1s, y1s, x2s, y2s = x1 * sx, y1 * sy, x2 * sx, y2 * sy
        r = radius * s
        points = [
            x1s + r,
            y1s,
            x2s - r,
            y1s,
            x2s,
            y1s,
            x2s,
            y1s + r,
            x2s,
            y2s - r,
            x2s,
            y2s,
            x2s - r,
            y2s,
            x1s + r,
            y2s,
            x1s,
            y2s,
            x1s,
            y2s - r,
            x1s,
            y1s + r,
            x1s,
            y1s,
        ]
        self.canvas.create_polygon(points, smooth=True, splinesteps=12, **kwargs)
