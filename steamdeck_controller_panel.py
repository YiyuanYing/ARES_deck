#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Steam Deck 本地图形化手柄状态面板。

特点：
- 不依赖浏览器/Steam Input/网页 UI，直接读取 Linux joystick 接口 /dev/input/js0。
- 使用 Tkinter Canvas，全屏显示边缘实体按键状态和中间触屏虚拟按键。
- 实体按键边缘映射绿色表示当前按下；触屏虚拟按键绿色表示持续发送对应 bit。
- 预留 on_button_toggled / on_axis_updated，后续可在其中加入串口、UDP、ROS2 等机器人通信。
"""

from __future__ import annotations

import os
import argparse
import platform
import queue
import statistics
import struct
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from controller_protocol import BUTTON_IDS, BUTTON_NAMES
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
RESET_PULSE_SECONDS = 0.25

JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80
JS_EVENT_SIZE = 8

VIRTUAL_BUTTON_MAP = {
    32: {"name": "VIRTUAL_ESTOP", "label": "Button1", "x": 153, "y": 150, "w": 237, "h": 260, "radius": 18},
    33: {"name": "VIRTUAL_ENABLE", "label": "Button2", "x": 398, "y": 150, "w": 237, "h": 260, "radius": 18},
    34: {"name": "VIRTUAL_LOW_SPEED", "label": "Button3", "x": 643, "y": 150, "w": 237, "h": 260, "radius": 18},
    35: {"name": "VIRTUAL_HIGH_SPEED", "label": "Button4", "x": 888, "y": 150, "w": 237, "h": 260, "radius": 18},
    36: {"name": "VIRTUAL_AUTO_MODE", "label": "Button5", "x": 153, "y": 418, "w": 237, "h": 260, "radius": 18},
    37: {"name": "VIRTUAL_RESET", "label": "Button6", "x": 398, "y": 418, "w": 237, "h": 260, "radius": 18},
    38: {"name": "VIRTUAL_AUX_1", "label": "Button7", "x": 643, "y": 418, "w": 237, "h": 260, "radius": 18},
    39: {"name": "VIRTUAL_AUX_2", "label": "Button8", "x": 888, "y": 418, "w": 237, "h": 260, "radius": 18},
}

VIRTUAL_BUTTON_IDS = tuple(VIRTUAL_BUTTON_MAP)

FOOTER_TOUCH_BUTTONS = {
    "clear_estop": {
        "label": "CLEAR ESTOP",
        "x": 250,
        "y": 724,
        "w": 230,
        "h": 54,
    },
    "exit_fullscreen": {
        "x": 525,
        "y": 724,
        "w": 230,
        "h": 54,
    },
    "exit_app": {
        "label": "EXIT APP",
        "x": 800,
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

DISPLAY_BUTTON_MAP = {
    2: {
        "name": "Quick Access / ...",
        "label": "...",
        "shape": "rounded_rect",
        "x": 1208,
        "y": 625,
        "w": 46,
        "h": 48,
        "radius": 12,
    },
    3: {"name": "A", "label": "A", "shape": "circle", "x": 1234, "y": 486, "r": 12},
    4: {"name": "B", "label": "B", "shape": "circle", "x": 1260, "y": 459, "r": 12},
    5: {"name": "X", "label": "X", "shape": "circle", "x": 1208, "y": 459, "r": 12},
    6: {"name": "Y", "label": "Y", "shape": "circle", "x": 1234, "y": 432, "r": 12},
    7: {
        "name": "LB",
        "label": "LB",
        "shape": "rounded_rect",
        "x": 28,
        "y": 112,
        "w": 91,
        "h": 42,
        "radius": 12,
    },
    8: {
        "name": "RB",
        "label": "RB",
        "shape": "rounded_rect",
        "x": 1161,
        "y": 112,
        "w": 91,
        "h": 42,
        "radius": 12,
    },
    9: {
        "name": "LT Full Press",
        "label": "LT",
        "shape": "rounded_rect",
        "x": 28,
        "y": 62,
        "w": 91,
        "h": 42,
        "radius": 12,
    },
    10: {
        "name": "RT Full Press",
        "label": "RT",
        "shape": "rounded_rect",
        "x": 1161,
        "y": 62,
        "w": 91,
        "h": 42,
        "radius": 12,
    },
    11: {
        "name": "View / Select",
        "label": "VIEW",
        "shape": "rounded_rect",
        "x": 78,
        "y": 625,
        "w": 46,
        "h": 48,
        "radius": 12,
    },
    12: {
        "name": "Menu / Start",
        "label": "MENU",
        "shape": "rounded_rect",
        "x": 1161,
        "y": 625,
        "w": 46,
        "h": 48,
        "radius": 12,
    },
    13: {
        "name": "Steam",
        "label": "STEAM",
        "shape": "rounded_rect",
        "x": 28,
        "y": 625,
        "w": 41,
        "h": 48,
        "radius": 12,
    },
    16: {"name": "D-pad Up", "label": "UP", "shape": "rounded_rect", "x": 58, "y": 420, "w": 28, "h": 34, "radius": 8},
    17: {"name": "D-pad Down", "label": "DOWN", "shape": "rounded_rect", "x": 58, "y": 496, "w": 28, "h": 34, "radius": 8},
    18: {"name": "D-pad Left", "label": "LEFT", "shape": "rounded_rect", "x": 18, "y": 458, "w": 28, "h": 34, "radius": 8},
    19: {"name": "D-pad Right", "label": "RIGHT", "shape": "rounded_rect", "x": 98, "y": 458, "w": 28, "h": 34, "radius": 8},
    20: {
        "name": "L4",
        "label": "L4",
        "shape": "rounded_rect",
        "x": 28,
        "y": 208,
        "w": 41,
        "h": 110,
        "radius": 14,
    },
    21: {
        "name": "R4",
        "label": "R4",
        "shape": "rounded_rect",
        "x": 1161,
        "y": 208,
        "w": 41,
        "h": 110,
        "radius": 14,
    },
    22: {
        "name": "L5",
        "label": "L5",
        "shape": "rounded_rect",
        "x": 78,
        "y": 208,
        "w": 41,
        "h": 110,
        "radius": 14,
    },
    23: {
        "name": "R5",
        "label": "R5",
        "shape": "rounded_rect",
        "x": 1208,
        "y": 208,
        "w": 41,
        "h": 110,
        "radius": 14,
    },
}

OUTPUT_PHYSICAL_BUTTON_IDS = tuple(range(2, 24))


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


class HostReachabilityMonitor(threading.Thread):
    """后台 ping 目标主机，避免 UDP socket 在线但主机实际断开的假绿状态。"""

    def __init__(self, target_ip: str, interval: float = 1.0) -> None:
        super().__init__(daemon=True)
        self.target_ip = target_ip
        self.interval = interval
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.reachable = False
        self.last_checked_at = 0.0

    def stop(self) -> None:
        self.stop_event.set()

    def snapshot(self) -> tuple[bool, float]:
        with self.lock:
            return self.reachable, self.last_checked_at

    def run(self) -> None:
        while not self.stop_event.is_set():
            reachable = self._ping_once()
            with self.lock:
                self.reachable = reachable
                self.last_checked_at = time.monotonic()
            self.stop_event.wait(self.interval)

    def _ping_once(self) -> bool:
        if platform.system().lower().startswith("win"):
            command = ["ping", "-n", "1", "-w", "800", self.target_ip]
        else:
            command = ["ping", "-c", "1", "-W", "1", self.target_ip]
        try:
            result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.5)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0


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
        self.calibration_deadline = 0.0
        self.calibration_samples: Dict[int, List[int]] = {i: [] for i in AXIS_MAP}
        self.virtual_button_until: Dict[int, float] = {}
        self.physical_button_flash_until: Dict[int, float] = {}
        self.last_touch_at = 0.0
        self.last_touch_target = ""

        self.root.bind("<Escape>", self.exit_program)
        self.root.bind("<F11>", self.toggle_fullscreen)
        self.root.bind("<r>", self.reset_toggles)
        self.root.bind("<R>", self.reset_toggles)
        self.root.bind("<c>", self.recalibrate_axes)
        self.root.bind("<C>", self.recalibrate_axes)
        self.canvas.bind("<ButtonPress-1>", self.handle_canvas_touch)
        self.root.protocol("WM_DELETE_WINDOW", self.exit_program)

    def run(self) -> None:
        self.reader.start()
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
        self.host_monitor.join(timeout=1.0)
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
        for button_id, spec in VIRTUAL_BUTTON_MAP.items():
            x1 = spec["x"]
            y1 = spec["y"]
            x2 = x1 + spec["w"]
            y2 = y1 + spec["h"]
            if x1 <= base_x <= x2 and y1 <= base_y <= y2:
                if self.touch_is_duplicate(f"virtual:{button_id}"):
                    return
                self.toggle_virtual_button(button_id)
                return

        for action, spec in FOOTER_TOUCH_BUTTONS.items():
            x1 = spec["x"]
            y1 = spec["y"]
            x2 = x1 + spec["w"]
            y2 = y1 + spec["h"]
            if x1 <= base_x <= x2 and y1 <= base_y <= y2:
                if self.touch_is_duplicate(f"footer:{action}"):
                    return
                if action == "clear_estop":
                    self.trigger_clear_estop()
                elif action == "exit_fullscreen":
                    self.toggle_fullscreen()
                elif action == "exit_app":
                    self.exit_program()
                return

    def touch_is_duplicate(self, target: str) -> bool:
        now = time.monotonic()
        is_duplicate = target == self.last_touch_target and now - self.last_touch_at < 0.18
        self.last_touch_target = target
        self.last_touch_at = now
        return is_duplicate

    def toggle_virtual_button(self, button_id: int) -> None:
        new_state = not self.state.virtual_button_toggle.get(button_id, False)
        self.state.virtual_button_toggle[button_id] = new_state
        spec = VIRTUAL_BUTTON_MAP.get(button_id, {})
        button_name = spec.get("name", BUTTON_NAMES.get(button_id, f"BUTTON_{button_id}"))
        print(f"[virtual] {button_id:02d} {button_name} toggled -> {new_state}")

    def trigger_clear_estop(self) -> None:
        reset_button_id = BUTTON_IDS["VIRTUAL_RESET"]
        self.virtual_button_until[reset_button_id] = time.monotonic() + RESET_PULSE_SECONDS
        print("[safety] VIRTUAL_RESET pulse sent to clear ESTOP latch")

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
        if is_pressed:
            self.physical_button_flash_until[button_id] = time.monotonic() + 0.12

        # 初始化事件只同步当前物理状态，不视为一次真实按下。
        if is_init:
            return

        # 只在 0 -> 1 上升沿切换 toggle 状态，松开时不改变绿色显示。
        if is_pressed and not was_pressed:
            new_state = not self.state.button_toggle[button_id]
            self.state.button_toggle[button_id] = new_state
            button_name = DISPLAY_BUTTON_MAP.get(button_id, {}).get("name", BUTTON_NAMES.get(button_id, f"BUTTON_{button_id}"))
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
        physical = self.state.button_physical.get(button_id, False)
        visible_pressed = physical or time.monotonic() <= self.physical_button_flash_until.get(button_id, 0.0)
        fill = "#1fbf75" if visible_pressed else "#29313a"
        outline = "#7df0b4" if visible_pressed else "#596575"
        width = 3 if visible_pressed or toggled else 2
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
