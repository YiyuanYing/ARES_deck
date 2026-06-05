#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Steam Deck 本地图形化手柄状态面板。

特点：
- 不依赖浏览器/Steam Input/网页 UI，直接读取 Linux joystick 接口 /dev/input/js0。
- 使用 Tkinter Canvas，全屏显示 Steam Deck 俯视图风格的按钮和摇杆状态。
- 按钮使用 toggle 显示：上升沿切换绿色激活状态，物理按住时显示黄色描边。
- 预留 on_button_toggled / on_axis_updated，后续可在其中加入串口、UDP、ROS2 等机器人通信。
"""

from __future__ import annotations

import os
import argparse
import queue
import statistics
import struct
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from controller_protocol import BUTTON_NAMES
from controller_udp_sender import (
    ControllerUdpSender,
    FAILSAFE_TIMEOUT_MS,
    LOCAL_IP,
    SEND_HZ,
    TARGET_IP,
    TARGET_PORT,
)


# =========================
# 可配置参数
# =========================

DEVICE_PATH = "/dev/input/js0"
DEADZONE = 0.20
BASE_WIDTH = 1280
BASE_HEIGHT = 800
REFRESH_MS = 20  # 50Hz GUI/UDP update loop
CALIBRATION_SECONDS = 1.0

DEFAULT_LOCAL_IP = LOCAL_IP
DEFAULT_REMOTE_IP = TARGET_IP
DEFAULT_UDP_PORT = TARGET_PORT
UDP_SEND_HZ = SEND_HZ

JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80
JS_EVENT_SIZE = 8

FOOTER_TOUCH_BUTTONS = {
    "exit_fullscreen": {
        "x": 390,
        "y": 724,
        "w": 230,
        "h": 54,
    },
    "exit_app": {
        "label": "EXIT APP",
        "x": 660,
        "y": 724,
        "w": 230,
        "h": 54,
    },
}


# =========================
# Steam Deck 当前 /dev/input/js0 映射
# 坐标基于 1280x800 设计，绘制时会按窗口尺寸缩放。
# =========================

AXIS_MAP = {
    0: {"name": "Left Stick X", "stick": "left", "component": "x"},
    1: {"name": "Left Stick Y", "stick": "left", "component": "y"},
    2: {"name": "Right Stick X", "stick": "right", "component": "x"},
    3: {"name": "Right Stick Y", "stick": "right", "component": "y"},
}

BUTTON_MAP = {
    2: {
        "name": "Quick Access / ...",
        "label": "...",
        "shape": "rounded_rect",
        "x": 705,
        "y": 625,
        "w": 80,
        "h": 46,
        "radius": 16,
    },
    3: {"name": "A", "label": "A", "shape": "circle", "x": 1040, "y": 310, "r": 30},
    4: {"name": "B", "label": "B", "shape": "circle", "x": 1090, "y": 260, "r": 30},
    5: {"name": "X", "label": "X", "shape": "circle", "x": 990, "y": 260, "r": 30},
    6: {"name": "Y", "label": "Y", "shape": "circle", "x": 1040, "y": 210, "r": 30},
    7: {
        "name": "LB",
        "label": "LB",
        "shape": "rounded_rect",
        "x": 90,
        "y": 105,
        "w": 220,
        "h": 46,
        "radius": 14,
    },
    8: {
        "name": "RB",
        "label": "RB",
        "shape": "rounded_rect",
        "x": 970,
        "y": 105,
        "w": 220,
        "h": 46,
        "radius": 14,
    },
    9: {
        "name": "LT Full Press",
        "label": "LT",
        "shape": "rounded_rect",
        "x": 90,
        "y": 48,
        "w": 220,
        "h": 44,
        "radius": 14,
    },
    10: {
        "name": "RT Full Press",
        "label": "RT",
        "shape": "rounded_rect",
        "x": 970,
        "y": 48,
        "w": 220,
        "h": 44,
        "radius": 14,
    },
    11: {
        "name": "View / Select",
        "label": "VIEW",
        "shape": "rounded_rect",
        "x": 455,
        "y": 205,
        "w": 82,
        "h": 42,
        "radius": 14,
    },
    12: {
        "name": "Menu / Start",
        "label": "MENU",
        "shape": "rounded_rect",
        "x": 743,
        "y": 205,
        "w": 82,
        "h": 42,
        "radius": 14,
    },
    13: {
        "name": "Steam",
        "label": "STEAM",
        "shape": "rounded_rect",
        "x": 495,
        "y": 625,
        "w": 100,
        "h": 46,
        "radius": 16,
    },
    14: {"name": "L3", "label": "L3", "shape": "stick_circle", "x": 300, "y": 265, "r": 88},
    15: {"name": "R3", "label": "R3", "shape": "stick_circle", "x": 980, "y": 420, "r": 88},
    16: {"name": "D-pad Up", "label": "UP", "shape": "rounded_rect", "x": 210, "y": 386, "w": 62, "h": 56, "radius": 10},
    17: {"name": "D-pad Down", "label": "DOWN", "shape": "rounded_rect", "x": 210, "y": 504, "w": 62, "h": 56, "radius": 10},
    18: {"name": "D-pad Left", "label": "LEFT", "shape": "rounded_rect", "x": 151, "y": 445, "w": 62, "h": 56, "radius": 10},
    19: {"name": "D-pad Right", "label": "RIGHT", "shape": "rounded_rect", "x": 269, "y": 445, "w": 62, "h": 56, "radius": 10},
    20: {
        "name": "L4",
        "label": "L4",
        "shape": "rounded_rect",
        "x": 22,
        "y": 230,
        "w": 70,
        "h": 104,
        "radius": 18,
    },
    21: {
        "name": "R4",
        "label": "R4",
        "shape": "rounded_rect",
        "x": 1188,
        "y": 230,
        "w": 70,
        "h": 104,
        "radius": 18,
    },
    22: {
        "name": "L5",
        "label": "L5",
        "shape": "rounded_rect",
        "x": 22,
        "y": 456,
        "w": 70,
        "h": 104,
        "radius": 18,
    },
    23: {
        "name": "R5",
        "label": "R5",
        "shape": "rounded_rect",
        "x": 1188,
        "y": 456,
        "w": 70,
        "h": 104,
        "radius": 18,
    },
}

PHYSICAL_BUTTON_IDS = tuple(range(24))


def on_button_toggled(button_id: int, name: str, state: bool) -> None:
    """TODO: 后续在这里加入机器人控制指令发送逻辑。"""
    print(f"[button] {button_id:02d} {name} toggled -> {state}")


def on_axis_updated(axis_id: int, value: float) -> None:
    """TODO: 后续在这里加入摇杆控制指令发送逻辑。当前只保留接口。"""
    _ = axis_id, value


@dataclass
class ControllerState:
    """GUI 主线程维护的手柄状态。"""

    button_physical: Dict[int, bool] = field(default_factory=lambda: {i: False for i in PHYSICAL_BUTTON_IDS})
    button_toggle: Dict[int, bool] = field(default_factory=lambda: {i: False for i in PHYSICAL_BUTTON_IDS})
    raw_axes: Dict[int, int] = field(default_factory=lambda: {i: 0 for i in AXIS_MAP})
    axis_values: Dict[int, float] = field(default_factory=lambda: {i: 0.0 for i in AXIS_MAP})
    center_offsets: Dict[int, float] = field(default_factory=lambda: {i: 0.0 for i in AXIS_MAP})
    connected: bool = False
    status_text: str = f"{DEVICE_PATH} disconnected"
    status_is_error: bool = True


class JoystickReader(threading.Thread):
    """后台读取线程：只负责打开设备、读取二进制事件、投递到队列。"""

    def __init__(self, device_path: str, event_queue: "queue.Queue[Tuple]") -> None:
        super().__init__(daemon=True)
        self.device_path = device_path
        self.event_queue = event_queue
        self.stop_event = threading.Event()
        self.fd: int | None = None
        self.last_error = ""

    def stop(self) -> None:
        self.stop_event.set()
        self._close_device()

    def _close_device(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    def _open_device(self) -> bool:
        try:
            self.fd = os.open(self.device_path, os.O_RDONLY | os.O_NONBLOCK)
        except FileNotFoundError:
            message = f"{self.device_path} not found"
        except PermissionError:
            message = (
                f"{self.device_path} permission denied\n"
                "Run:\n"
                "sudo usermod -aG input $USER\n"
                "sudo reboot"
            )
        except OSError as exc:
            message = f"{self.device_path} open failed: {exc}"
        else:
            self.last_error = ""
            self.event_queue.put(("device_status", True, f"{self.device_path} connected"))
            print(f"[device] opened {self.device_path}")
            return True

        if message != self.last_error:
            print(f"[device] {message}")
            self.last_error = message
        self.event_queue.put(("device_status", False, message))
        return False

    def run(self) -> None:
        while not self.stop_event.is_set():
            if self.fd is None and not self._open_device():
                self.stop_event.wait(2.0)
                continue

            try:
                data = os.read(self.fd, JS_EVENT_SIZE)
            except BlockingIOError:
                self.stop_event.wait(0.005)
                continue
            except OSError as exc:
                message = f"{self.device_path} disconnected: {exc}"
                print(f"[device] {message}")
                self.event_queue.put(("device_status", False, message))
                self._close_device()
                self.stop_event.wait(1.0)
                continue

            if len(data) != JS_EVENT_SIZE:
                self.stop_event.wait(0.005)
                continue

            event_time, value, event_type, number = struct.unpack("IhBB", data)
            # joystick event type 可能带 JS_EVENT_INIT，需要由 GUI 主线程屏蔽初始化位后处理。
            self.event_queue.put(("js_event", event_time, value, event_type, number))

        self._close_device()


class ControllerPanel:
    def __init__(
        self,
        local_ip: str,
        remote_ip: str,
        udp_port: int,
        send_hz: float,
        failsafe_timeout_ms: int,
    ) -> None:
        self.root = tk.Tk()
        self.root.title("Steam Deck Controller Panel")
        self.root.configure(bg="#111418")
        self.root.geometry(f"{BASE_WIDTH}x{BASE_HEIGHT}")
        self.fullscreen = True
        self.root.attributes("-fullscreen", self.fullscreen)

        self.canvas = tk.Canvas(self.root, bg="#111418", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.state = ControllerState()
        self.event_queue: "queue.Queue[Tuple]" = queue.Queue()
        self.reader = JoystickReader(DEVICE_PATH, self.event_queue)
        self.udp_sender = ControllerUdpSender(
            state_provider=self.get_controller_snapshot,
            local_ip=local_ip,
            target_ip=remote_ip,
            target_port=udp_port,
            send_hz=send_hz,
            failsafe_timeout_ms=failsafe_timeout_ms,
        )

        self.calibrating = False
        self.calibration_deadline = 0.0
        self.calibration_samples: Dict[int, List[int]] = {i: [] for i in AXIS_MAP}

        self.root.bind("<Escape>", self.exit_program)
        self.root.bind("<F11>", self.toggle_fullscreen)
        self.root.bind("<r>", self.reset_toggles)
        self.root.bind("<R>", self.reset_toggles)
        self.root.bind("<c>", self.recalibrate_axes)
        self.root.bind("<C>", self.recalibrate_axes)
        self.canvas.bind("<ButtonRelease-1>", self.handle_canvas_touch)
        self.root.protocol("WM_DELETE_WINDOW", self.exit_program)

    def run(self) -> None:
        self.reader.start()
        self.udp_sender.start()
        self.begin_calibration("startup")
        self.root.after(REFRESH_MS, self.update_loop)
        self.root.mainloop()

    def exit_program(self, _event: tk.Event | None = None) -> None:
        print("[exit] closing controller panel")
        self.udp_sender.stop()
        self.reader.stop()
        self.reader.join(timeout=1.0)
        self.root.destroy()

    def toggle_fullscreen(self, _event: tk.Event | None = None) -> None:
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)
        mode = "enabled" if self.fullscreen else "disabled"
        print(f"[ui] fullscreen {mode}")

    def handle_canvas_touch(self, event: tk.Event) -> None:
        sx, sy, _s = self.scale()
        base_x = event.x / sx
        base_y = event.y / sy

        # Steam Deck 触屏会映射成鼠标点击事件；这里直接用基础坐标做命中检测。
        for action, spec in FOOTER_TOUCH_BUTTONS.items():
            x1 = spec["x"]
            y1 = spec["y"]
            x2 = x1 + spec["w"]
            y2 = y1 + spec["h"]
            if x1 <= base_x <= x2 and y1 <= base_y <= y2:
                if action == "exit_fullscreen":
                    self.toggle_fullscreen()
                elif action == "exit_app":
                    self.exit_program()
                return

    def reset_toggles(self, _event: tk.Event | None = None) -> None:
        for button_id in self.state.button_toggle:
            self.state.button_toggle[button_id] = False
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
        # UDP 发送 toggle 状态：按一下锁存为 True，再按一下解除，类似航模遥控器拨杆。
        # 黄色描边仍然只表示当前 physical pressed；绿色按钮才会进入控制帧 bitmask。
        # TODO: 后续可把屏幕触摸按钮映射到 32~95 的 virtual buttons。
        return {
            "axes": {
                "lx": self.state.axis_values.get(0, 0.0),
                "ly": self.state.axis_values.get(1, 0.0),
                "rx": self.state.axis_values.get(2, 0.0),
                "ry": self.state.axis_values.get(3, 0.0),
            },
            "buttons": {button_id: self.state.button_toggle.get(button_id, False) for button_id in PHYSICAL_BUTTON_IDS},
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
        if button_id not in PHYSICAL_BUTTON_IDS:
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
            button_name = BUTTON_MAP.get(button_id, {}).get("name", BUTTON_NAMES.get(button_id, f"BUTTON_{button_id}"))
            on_button_toggled(button_id, button_name, new_state)

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
        self.canvas.create_rectangle(0, 0, width, height, fill="#111418", outline="")

        self.draw_header()
        self.draw_deck_outline()
        self.draw_network_panel()

        # 先画普通按钮，再画摇杆的小圆点，避免摇杆点被覆盖。
        for button_id, spec in BUTTON_MAP.items():
            self.draw_button(button_id, spec)

        self.draw_stick_dot("left", center_button_id=14, axis_x=0, axis_y=1)
        self.draw_stick_dot("right", center_button_id=15, axis_x=2, axis_y=3)
        self.draw_footer()

    def draw_header(self) -> None:
        status_color = "#6ee7a8" if self.state.connected else "#ff6b6b"
        self.canvas.create_text(
            self.x(640),
            self.y(42),
            text="Steam Deck Controller Panel",
            fill="#f2f4f8",
            font=("DejaVu Sans", 26, "bold"),
        )
        self.canvas.create_text(
            self.x(640),
            self.y(78),
            text=self.state.status_text,
            fill=status_color,
            font=("DejaVu Sans", 15, "bold"),
        )
        if self.state.status_is_error:
            self.canvas.create_text(
                self.x(640),
                self.y(119),
                text="sudo usermod -aG input $USER    sudo reboot",
                fill="#ff9d9d",
                font=("DejaVu Sans Mono", 13),
            )
        elif self.calibrating:
            self.canvas.create_text(
                self.x(640),
                self.y(119),
                text="Calibrating stick centers...",
                fill="#ffd447",
                font=("DejaVu Sans", 14, "bold"),
            )

        self.canvas.create_text(
            self.x(640),
            self.y(165),
            text=time.strftime("%Y-%m-%d %H:%M:%S"),
            fill="#9aa4b2",
            font=("DejaVu Sans Mono", 14),
        )

    def draw_footer(self) -> None:
        for action, spec in FOOTER_TOUCH_BUTTONS.items():
            fill = "#2c3440"
            outline = "#6ee7a8" if action == "exit_fullscreen" else "#ff8b8b"
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

    def draw_deck_outline(self) -> None:
        # 一条低调的外轮廓，帮助形成 Steam Deck 俯视图的空间关系。
        self.rounded_rect(120, 145, 1160, 705, 96, fill="", outline="#2a3038", width=3)
        self.rounded_rect(470, 285, 810, 585, 30, fill="", outline="#252b33", width=2)

    def draw_network_panel(self) -> None:
        metrics = self.udp_sender.snapshot_metrics()
        status_color = "#6ee7a8" if metrics.connected else "#ffd447"
        if not metrics.enabled or metrics.last_error:
            status_color = "#ff8b8b"

        self.rounded_rect(482, 300, 798, 570, 24, fill="#14181e", outline="#2d3540", width=2)
        self.canvas.create_text(
            self.x(640),
            self.y(324),
            text="CONTROLLERFRAME V2",
            fill="#f2f4f8",
            font=("DejaVu Sans", 14, "bold"),
        )
        self.canvas.create_text(
            self.x(640),
            self.y(350),
            text=metrics.status_text,
            fill=status_color,
            font=("DejaVu Sans", 12, "bold"),
        )

        rows = [
            ("local", metrics.local_ip),
            ("bind", f"{metrics.bind_ip}:auto"),
            ("target", f"{metrics.target_ip}:{metrics.target_port}"),
            ("mode", "100Hz UDP binary"),
            ("tx", f"{metrics.tx_rate:4.0f}/s"),
            ("seq", f"{metrics.seq}"),
            ("payload", f"{metrics.payload_bytes} bytes"),
            ("buttons", f"{sum(1 for value in metrics.latest_buttons.values() if value)} physical"),
            (
                "axes",
                f"{metrics.latest_axes.get('lx', 0.0):+.2f},{metrics.latest_axes.get('ly', 0.0):+.2f} "
                f"{metrics.latest_axes.get('rx', 0.0):+.2f},{metrics.latest_axes.get('ry', 0.0):+.2f}",
            ),
        ]
        y = 382
        for label, value in rows:
            self.canvas.create_text(
                self.x(508),
                self.y(y),
                text=label,
                anchor="w",
                fill="#8f99a8",
                font=("DejaVu Sans Mono", 10),
            )
            self.canvas.create_text(
                self.x(608),
                self.y(y),
                text=value,
                anchor="w",
                fill="#d9e2ef",
                font=("DejaVu Sans Mono", 10),
            )
            y += 19

        if metrics.last_error:
            error_text = metrics.last_error[:42]
            self.canvas.create_text(
                self.x(640),
                self.y(555),
                text=error_text,
                fill="#ff9d9d",
                font=("DejaVu Sans Mono", 9),
            )

    def draw_button(self, button_id: int, spec: Dict) -> None:
        toggled = self.state.button_toggle.get(button_id, False)
        physical = self.state.button_physical.get(button_id, False)
        fill = "#1fbf75" if toggled else "#343a42"
        outline = "#ffd447" if physical else "#687180"
        width = 5 if physical else 2
        shape = spec["shape"]

        if shape in ("circle", "stick_circle"):
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

        if shape == "stick_circle":
            axis_x, axis_y = (0, 1) if button_id == 14 else (2, 3)
            value_text = f"{self.state.axis_values[axis_x]: .2f}, {self.state.axis_values[axis_y]: .2f}"
            self.canvas.create_text(
                self.x(spec["x"]),
                self.y(spec["y"] + spec["r"] + 25),
                text=value_text,
                fill="#c5ccd6",
                font=("DejaVu Sans Mono", 13),
            )

    def draw_button_label(self, spec: Dict) -> None:
        shape = spec["shape"]
        if shape in ("circle", "stick_circle"):
            cx = spec["x"]
            cy = spec["y"]
            font_size = 16 if shape == "circle" else 18
        else:
            cx = spec["x"] + spec["w"] / 2
            cy = spec["y"] + spec["h"] / 2
            font_size = 13 if spec["w"] < 90 else 15

        self.canvas.create_text(
            self.x(cx),
            self.y(cy),
            text=spec["label"],
            fill="#f2f4f8",
            font=("DejaVu Sans", font_size, "bold"),
        )

    def draw_stick_dot(self, stick: str, center_button_id: int, axis_x: int, axis_y: int) -> None:
        spec = BUTTON_MAP[center_button_id]
        radius = spec["r"]
        value_x = self.state.axis_values[axis_x]
        value_y = self.state.axis_values[axis_y]
        # Linux joystick Y 轴通常向下为正，屏幕坐标也向下为正，所以这里不反转。
        dot_x = spec["x"] + value_x * radius * 0.68
        dot_y = spec["y"] + value_y * radius * 0.68
        self.circle(dot_x, dot_y, 16, fill="#dfe7f3", outline="#101216", width=3)

        label = "Left Stick" if stick == "left" else "Right Stick"
        self.canvas.create_text(
            self.x(spec["x"]),
            self.y(spec["y"] - spec["r"] - 20),
            text=label,
            fill="#9aa4b2",
            font=("DejaVu Sans", 14, "bold"),
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Steam Deck controller GUI + ControllerFrame V2 UDP sender.")
    parser.add_argument("--local-ip", default=DEFAULT_LOCAL_IP, help="Steam Deck LAN IP used for UDP bind.")
    parser.add_argument("--remote-ip", "--target-ip", dest="remote_ip", default=DEFAULT_REMOTE_IP, help="Receiver LAN IP.")
    parser.add_argument("--port", type=int, default=DEFAULT_UDP_PORT, help="UDP receiver port.")
    parser.add_argument("--send-hz", type=float, default=UDP_SEND_HZ, help="Controller packets per second.")
    parser.add_argument("--failsafe-timeout-ms", type=int, default=FAILSAFE_TIMEOUT_MS, help="Failsafe timeout encoded in each frame.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    panel = ControllerPanel(args.local_ip, args.remote_ip, args.port, args.send_hz, args.failsafe_timeout_ms)
    panel.run()


if __name__ == "__main__":
    main()
