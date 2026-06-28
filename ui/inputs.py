#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import platform
import queue
import select
import struct
import subprocess
import threading
import time
from typing import Callable, Dict, List, Tuple

try:
    from evdev import InputDevice, ecodes, list_devices
except ImportError:
    InputDevice = None
    ecodes = None
    list_devices = None

from ui.config import BASE_HEIGHT, BASE_WIDTH, JS_EVENT_SIZE

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


class TouchReader(threading.Thread):
    """后台读取 Linux evdev 触屏事件，绕开 Tkinter/libinput 鼠标转换延迟。"""

    TOUCH_NAME_KEYWORDS = ("touch", "touchscreen", "valve", "steam deck")

    def __init__(
        self,
        device_path: str,
        event_queue: "queue.Queue[Tuple]",
        swap_xy: bool = False,
        invert_x: bool = False,
        invert_y: bool = False,
        debug_touch: bool = False,
        screen_size_provider: Callable[[], Tuple[int, int]] | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.device_path = device_path
        self.event_queue = event_queue
        self.swap_xy = swap_xy
        self.invert_x = invert_x
        self.invert_y = invert_y
        self.debug_touch = debug_touch
        self.screen_size_provider = screen_size_provider or (lambda: (BASE_WIDTH, BASE_HEIGHT))
        self.stop_event = threading.Event()
        self.device = None
        self.x_code: int | None = None
        self.y_code: int | None = None
        self.min_x = 0
        self.max_x = 1
        self.min_y = 0
        self.max_y = 1
        self.raw_x: int | None = None
        self.raw_y: int | None = None
        self.touching = False
        self.press_sent = False

    def stop(self) -> None:
        self.stop_event.set()

    def _close_device(self) -> None:
        if self.device is not None:
            try:
                self.device.close()
            except OSError:
                pass
            self.device = None

    def run(self) -> None:
        if InputDevice is None or ecodes is None or list_devices is None:
            message = "TOUCH disabled: install evdev with `pip install evdev`"
            print(f"[touch] {message}")
            self.event_queue.put(("touch_status", False, message, True))
            return

        path = self.device_path or self.find_touch_device()
        if not path:
            message = "TOUCH not found; mouse fallback enabled"
            print(f"[touch] {message}")
            self.event_queue.put(("touch_status", False, message, False))
            return

        self.device_path = path
        try:
            self.device = InputDevice(path)
            self._apply_device_transform_hints()
            self._configure_abs_ranges()
        except FileNotFoundError:
            message = f"TOUCH not found -> {path}"
            print(f"[touch] {message}")
            self.event_queue.put(("touch_status", False, message, True))
            return
        except PermissionError:
            message = (
                f"TOUCH permission denied -> {path}; "
                "run: sudo usermod -aG input $USER && sudo reboot"
            )
            print(f"[touch] {message}")
            self.event_queue.put(("touch_status", False, message, True))
            return
        except OSError as exc:
            message = f"TOUCH open failed -> {path}: {exc}"
            print(f"[touch] {message}")
            self.event_queue.put(("touch_status", False, message, True))
            self._close_device()
            return

        message = f"TOUCH connected -> {path}"
        print(f"[touch] {message} ({self.device.name})")
        self.event_queue.put(("touch_status", True, message, False))

        while not self.stop_event.is_set():
            try:
                readable, _writeable, _errors = select.select([self.device.fd], [], [], 0.05)
            except (OSError, ValueError) as exc:
                message = f"TOUCH disconnected -> {path}: {exc}"
                print(f"[touch] {message}")
                self.event_queue.put(("touch_status", False, message, True))
                break

            if not readable:
                continue

            try:
                for event in self.device.read():
                    self._handle_event(event)
            except BlockingIOError:
                continue
            except OSError as exc:
                message = f"TOUCH read failed -> {path}: {exc}"
                print(f"[touch] {message}")
                self.event_queue.put(("touch_status", False, message, True))
                break

        self._close_device()

    def _apply_device_transform_hints(self) -> None:
        name = (self.device.name or "").lower()
        if ("fts3528" in name or "2808:1015" in name) and not (self.swap_xy or self.invert_x or self.invert_y):
            self.swap_xy = True
            self.invert_x = True
            print("[touch] applying Steam Deck FTS3528 transform hint: --touch-swap-xy --touch-invert-x")

    def find_touch_device(self) -> str:
        candidates: List[Tuple[int, str]] = []
        for path in list_devices():
            try:
                device = InputDevice(path)
                score = self._touch_device_score(device)
                device.close()
            except OSError:
                continue
            if score > 0:
                candidates.append((score, path))

        if not candidates:
            return ""

        candidates.sort(reverse=True)
        chosen = candidates[0][1]
        print(f"[touch] auto-selected {chosen}")
        return chosen

    def _touch_device_score(self, device) -> int:
        caps = device.capabilities(absinfo=True)
        abs_infos = self._abs_info_dict(caps)
        key_codes = self._event_codes(caps, ecodes.EV_KEY)
        abs_codes = set(abs_infos)

        has_x = ecodes.ABS_X in abs_codes or ecodes.ABS_MT_POSITION_X in abs_codes
        has_y = ecodes.ABS_Y in abs_codes or ecodes.ABS_MT_POSITION_Y in abs_codes
        has_touch_key = ecodes.BTN_TOUCH in key_codes or ecodes.BTN_TOOL_FINGER in key_codes
        has_mt = ecodes.ABS_MT_POSITION_X in abs_codes and ecodes.ABS_MT_POSITION_Y in abs_codes
        if not (has_x and has_y and (has_touch_key or has_mt)):
            return 0

        name = (device.name or "").lower()
        score = 10
        if any(keyword in name for keyword in self.TOUCH_NAME_KEYWORDS):
            score += 20
        if has_mt:
            score += 5
        return score

    def _configure_abs_ranges(self) -> None:
        caps = self.device.capabilities(absinfo=True)
        abs_infos = self._abs_info_dict(caps)
        self.x_code = ecodes.ABS_MT_POSITION_X if ecodes.ABS_MT_POSITION_X in abs_infos else ecodes.ABS_X
        self.y_code = ecodes.ABS_MT_POSITION_Y if ecodes.ABS_MT_POSITION_Y in abs_infos else ecodes.ABS_Y
        if self.x_code not in abs_infos or self.y_code not in abs_infos:
            raise OSError("touch device lacks ABS_X/ABS_Y position ranges")

        x_info = abs_infos[self.x_code]
        y_info = abs_infos[self.y_code]
        self.min_x, self.max_x = int(x_info.min), int(x_info.max)
        self.min_y, self.max_y = int(y_info.min), int(y_info.max)
        if self.max_x == self.min_x or self.max_y == self.min_y:
            raise OSError("touch device has invalid ABS coordinate range")

    def _handle_event(self, event) -> None:
        if event.type == ecodes.EV_ABS:
            if event.code == self.x_code:
                self.raw_x = int(event.value)
            elif event.code == self.y_code:
                self.raw_y = int(event.value)
        elif event.type == ecodes.EV_KEY and event.code == ecodes.BTN_TOUCH:
            if event.value:
                self.touching = True
                self.press_sent = False
                self._emit_press_if_ready()
                if self.debug_touch:
                    print("[touch] down")
            else:
                self.touching = False
                self.press_sent = False
                self.event_queue.put(("touch_release",))
                if self.debug_touch:
                    print("[touch] up")
        elif event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
            if self.touching:
                self._emit_press_if_ready()

    def _emit_press_if_ready(self) -> None:
        if self.press_sent or self.raw_x is None or self.raw_y is None:
            return

        screen_x, screen_y = self.map_raw_to_screen(self.raw_x, self.raw_y)
        self.event_queue.put(("touch_press", screen_x, screen_y))
        self.press_sent = True
        if self.debug_touch:
            print(
                f"[touch] raw=({self.raw_x},{self.raw_y}) "
                f"screen=({screen_x:.1f},{screen_y:.1f})"
            )

    def map_raw_to_screen(self, raw_x: int, raw_y: int) -> Tuple[float, float]:
        width_value, height_value = self.screen_size_provider()
        width = float(max(width_value, 1))
        height = float(max(height_value, 1))
        norm_x = (raw_x - self.min_x) / float(self.max_x - self.min_x)
        norm_y = (raw_y - self.min_y) / float(self.max_y - self.min_y)
        norm_x = max(0.0, min(1.0, norm_x))
        norm_y = max(0.0, min(1.0, norm_y))
        if self.invert_x:
            norm_x = 1.0 - norm_x
        if self.invert_y:
            norm_y = 1.0 - norm_y
        if self.swap_xy:
            norm_x, norm_y = norm_y, norm_x
        return norm_x * width, norm_y * height

    @staticmethod
    def _abs_info_dict(caps) -> Dict[int, object]:
        return {int(code): info for code, info in caps.get(ecodes.EV_ABS, [])}

    @staticmethod
    def _event_codes(caps, event_type: int) -> set:
        codes = set()
        for item in caps.get(event_type, []):
            if isinstance(item, tuple):
                codes.add(int(item[0]))
            else:
                codes.add(int(item))
        return codes


class HostReachabilityMonitor(threading.Thread):
    """后台 ping 目标主机，避免 UDP socket 在线但主机实际断开的假绿状态。"""

    def __init__(self, target_ip: str | list[str], interval: float = 1.0) -> None:
        super().__init__(daemon=True)
        if isinstance(target_ip, str):
            self.target_ips = [target_ip]
        else:
            self.target_ips = [str(item) for item in target_ip]
        if not self.target_ips:
            self.target_ips = ["127.0.0.1"]
        self.target_ip = self.target_ips[0]
        self.interval = interval
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.hosts: Dict[str, tuple[bool, float]] = {ip: (False, 0.0) for ip in self.target_ips}
        self.workers: List[threading.Thread] = []

    def stop(self) -> None:
        self.stop_event.set()

    def snapshot(self) -> tuple[bool, float]:
        with self.lock:
            reachable = any(item[0] for item in self.hosts.values())
            last_checked_at = max((item[1] for item in self.hosts.values()), default=0.0)
            return reachable, last_checked_at

    def snapshot_hosts(self) -> list[tuple[str, bool, float]]:
        with self.lock:
            return [(ip, reachable, checked_at) for ip, (reachable, checked_at) in self.hosts.items()]

    def run(self) -> None:
        self.workers = [
            threading.Thread(
                target=self._monitor_host,
                args=(ip,),
                name=f"HostPing-{ip}",
                daemon=True,
            )
            for ip in self.target_ips
        ]
        for worker in self.workers:
            worker.start()

        self.stop_event.wait()
        for worker in self.workers:
            worker.join(timeout=0.6)

    def _monitor_host(self, target_ip: str) -> None:
        while not self.stop_event.is_set():
            reachable = self._ping_once(target_ip)
            checked_at = time.monotonic()
            with self.lock:
                self.hosts[target_ip] = (reachable, checked_at)
            self.stop_event.wait(self.interval)

    def _ping_once(self, target_ip: str) -> bool:
        if platform.system().lower().startswith("win"):
            command = ["ping", "-n", "1", "-w", "800", target_ip]
        else:
            command = ["ping", "-c", "1", "-W", "0.3", target_ip]
        try:
            result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0
