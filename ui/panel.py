#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import queue
import statistics
import time
import tkinter as tk
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from core.protocol import BUTTON_IDS, BUTTON_NAMES
from core.udp_sender import ControllerUdpSender
from ui.config import (
    AXIS_MAP,
    BASE_HEIGHT,
    BASE_WIDTH,
    CALIBRATION_SECONDS,
    DEADZONE,
    DEVICE_PATH,
    DISPLAY_BUTTON_MAP,
    FOOTER_TOUCH_BUTTONS,
    JS_EVENT_AXIS,
    JS_EVENT_BUTTON,
    JS_EVENT_INIT,
    OUTPUT_PHYSICAL_BUTTON_IDS,
    REFRESH_MS,
    RESET_PULSE_SECONDS,
    VIRTUAL_BUTTON_IDS,
    VIRTUAL_BUTTON_MAP,
)
from ui.inputs import HostReachabilityMonitor, JoystickReader, TouchReader

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
        send_hz: float,
        failsafe_timeout_ms: int,
        touch_device: str,
        no_touch_reader: bool,
        touch_swap_xy: bool,
        touch_invert_x: bool,
        touch_invert_y: bool,
        debug_touch: bool,
    ) -> None:
        self.root = tk.Tk()
        self.root.title("SUSTECH-ARES ROBOCON2026")
        self.root.configure(bg="#111418")
        self.root.geometry(f"{BASE_WIDTH}x{BASE_HEIGHT}")
        self.fullscreen = True
        self.root.attributes("-fullscreen", self.fullscreen)

        self.canvas = tk.Canvas(self.root, bg="#111418", highlightthickness=0)
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
        self.active_touch_target = ""

    def handle_canvas_touch_xy(self, screen_x: float, screen_y: float, source: str = "touch") -> None:
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
                self.toggle_virtual_button(button_id)
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

    def redraw_now(self) -> None:
        self.draw()
        self.canvas.update_idletasks()

    def toggle_virtual_button(self, button_id: int) -> None:
        new_state = not self.state.virtual_button_toggle.get(button_id, False)
        self.state.virtual_button_toggle[button_id] = new_state
        spec = VIRTUAL_BUTTON_MAP.get(button_id, {})
        button_name = spec.get("name", BUTTON_NAMES.get(button_id, f"BUTTON_{button_id}"))
        print(f"[virtual] {button_id:02d} {button_name} toggled -> {new_state}")

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
                self.active_touch_target = ""
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
            return

        # 只在 0 -> 1 上升沿切换 toggle 状态，松开时不改变绿色显示。
        if is_pressed and not was_pressed:
            new_state = not self.state.button_toggle[button_id]
            self.state.button_toggle[button_id] = new_state
            button_name = DISPLAY_BUTTON_MAP.get(button_id, {}).get("name", BUTTON_NAMES.get(button_id, f"BUTTON_{button_id}"))
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
        self.canvas.delete("all")
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        self.touch_canvas_width = max(width, 1)
        self.touch_canvas_height = max(height, 1)
        self.canvas.create_rectangle(0, 0, width, height, fill="#111418", outline="")

        self.draw_header()
        self.draw_edge_guides()
        self.draw_virtual_buttons()

        for button_id, spec in DISPLAY_BUTTON_MAP.items():
            self.draw_button(button_id, spec)

        self.draw_footer()

    def draw_header(self) -> None:
        device_color = "#6ee7a8" if self.state.connected else "#ff6b6b"
        metrics = self.udp_sender.snapshot_metrics()
        host_reachable, host_checked_at = self.host_monitor.snapshot()
        host_fresh = host_checked_at > 0.0 and time.monotonic() - host_checked_at <= 2.5
        host_ok = host_reachable and host_fresh
        host_color = "#6ee7a8" if host_ok else "#ff8b8b"
        if host_ok:
            host_text = f"HOST connected -> {metrics.target_ip}:{metrics.target_port}"
        elif not host_fresh:
            host_text = f"HOST checking -> {metrics.target_ip}:{metrics.target_port}"
            host_color = "#ffd447"
        else:
            host_text = f"HOST disconnected -> {metrics.target_ip}:{metrics.target_port}"
        device_text = self.state.status_text.splitlines()[0]
        self.canvas.create_text(
            self.x(640),
            self.y(36),
            text="SUSTECH-ARES ROBOCON2026",
            fill="#f2f4f8",
            font=("DejaVu Sans", 25, "bold"),
        )
        self.canvas.create_text(
            self.x(465),
            self.y(78),
            text=device_text,
            fill=device_color,
            font=("DejaVu Sans", 14, "bold"),
        )
        self.canvas.create_text(
            self.x(820),
            self.y(78),
            text=host_text,
            fill=host_color,
            font=("DejaVu Sans", 14, "bold"),
        )
        if self.state.status_is_error:
            self.canvas.create_text(
                self.x(640),
                self.y(112),
                text="sudo usermod -aG input $USER    sudo reboot",
                fill="#ff9d9d",
                font=("DejaVu Sans Mono", 13),
            )
        elif self.calibrating:
            self.canvas.create_text(
                self.x(640),
                self.y(112),
                text="Calibrating stick centers...",
                fill="#ffd447",
                font=("DejaVu Sans", 14, "bold"),
            )
        else:
            if self.state.touch_connected:
                touch_color = "#6ee7a8"
            elif self.state.touch_status_is_error:
                touch_color = "#ff8b8b"
            else:
                touch_color = "#ffd447"
            self.canvas.create_text(
                self.x(640),
                self.y(112),
                text=self.state.touch_status_text[:96],
                fill=touch_color,
                font=("DejaVu Sans Mono", 11),
            )
        self.canvas.create_line(self.x(145), self.y(132), self.x(1135), self.y(132), fill="#242a32", width=2)

    def draw_edge_guides(self) -> None:
        self.canvas.create_line(self.x(145), self.y(132), self.x(145), self.y(690), fill="#20262e", width=2)
        self.canvas.create_line(self.x(1135), self.y(132), self.x(1135), self.y(690), fill="#20262e", width=2)

    def draw_virtual_buttons(self) -> None:
        for button_id, spec in VIRTUAL_BUTTON_MAP.items():
            active = self.state.virtual_button_toggle.get(button_id, False)
            fill = "#1fbf75" if active else "#29313a"
            outline = "#7df0b4" if active else "#596575"
            self.rounded_rect(
                spec["x"],
                spec["y"],
                spec["x"] + spec["w"],
                spec["y"] + spec["h"],
                spec["radius"],
                fill=fill,
                outline=outline,
                width=3,
            )
            self.canvas.create_text(
                self.x(spec["x"] + spec["w"] / 2),
                self.y(spec["y"] + spec["h"] / 2),
                text=spec["label"],
                fill="#f2f4f8",
                font=("DejaVu Sans", 18, "bold"),
                justify="center",
            )

    def draw_footer(self) -> None:
        for action, spec in FOOTER_TOUCH_BUTTONS.items():
            fill = "#2c3440"
            if action == "clear_estop":
                outline = "#ffd447"
            elif action == "exit_fullscreen":
                outline = "#6ee7a8"
            else:
                outline = "#ff8b8b"
            self.rounded_rect(
                spec["x"],
                spec["y"],
                spec["x"] + spec["w"],
                spec["y"] + spec["h"],
                16,
                fill=fill,
                outline=outline,
                width=2,
            )
            self.canvas.create_text(
                self.x(spec["x"] + spec["w"] / 2),
                self.y(spec["y"] + spec["h"] / 2),
                text=self.footer_button_label(action, spec),
                fill="#f2f4f8",
                font=("DejaVu Sans", 15, "bold"),
            )

    def footer_button_label(self, action: str, spec: Dict) -> str:
        if action == "exit_fullscreen":
            return "EXIT FULLSCREEN" if self.fullscreen else "ENTER FULLSCREEN"
        return spec["label"]

    def draw_button(self, button_id: int, spec: Dict) -> None:
        toggled = self.state.button_toggle.get(button_id, False)
        fill = "#1fbf75" if toggled else "#29313a"
        outline = "#7df0b4" if toggled else "#596575"
        width = 3 if toggled else 2
        shape = spec["shape"]

        if shape == "circle":
            self.circle(spec["x"], spec["y"], spec["r"], fill=fill, outline=outline, width=width)
        elif shape == "rounded_rect":
            self.rounded_rect(
                spec["x"],
                spec["y"],
                spec["x"] + spec["w"],
                spec["y"] + spec["h"],
                spec.get("radius", 12),
                fill=fill,
                outline=outline,
                width=width,
            )

        self.draw_button_label(spec)

    def draw_button_label(self, spec: Dict) -> None:
        shape = spec["shape"]
        if shape == "circle":
            cx = spec["x"]
            cy = spec["y"]
            font_size = 16
        else:
            cx = spec["x"] + spec["w"] / 2
            cy = spec["y"] + spec["h"] / 2
            if spec["w"] < 35:
                font_size = 9
            elif spec["w"] < 60:
                font_size = 11
            elif spec["w"] < 90:
                font_size = 13
            else:
                font_size = 15

        self.canvas.create_text(
            self.x(cx),
            self.y(cy),
            text=spec["label"],
            fill="#f2f4f8",
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
