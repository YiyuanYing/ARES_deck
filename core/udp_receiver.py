#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ControllerFrame V2 UDP receiver with a fixed 100 Hz state loop.
"""

from __future__ import annotations

import argparse
import copy
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Tuple

from core.protocol import (
    BUTTON_IDS,
    ControllerFrameError,
    clamp,
    parse_controller_frame,
)


BIND_IP = "0.0.0.0"
PORT = 5005
CONTROL_HZ = 100.0
PRINT_INTERVAL_SECONDS = 0.2
WARNING_TIMEOUT_MS = 50.0
MIN_FAILSAFE_TIMEOUT_MS = 50
MAX_FAILSAFE_TIMEOUT_MS = 300
DEFAULT_FAILSAFE_TIMEOUT_MS = 150


@dataclass
class ReceiverStats:
    valid_count: int = 0
    lost: int = 0
    ooo: int = 0
    jitter_ms: float = 0.0
    last_interval_ms: float = 0.0
    last_seq: int | None = None
    last_addr: Tuple[str, int] | None = None
    last_frame_at: float = 0.0
    rx_times: Deque[float] = field(default_factory=deque)
    bad_packets: Dict[str, int] = field(
        default_factory=lambda: {
            "bad_length": 0,
            "bad_magic": 0,
            "bad_version": 0,
            "bad_msg_type": 0,
            "bad_length_field": 0,
            "bad_crc": 0,
            "other": 0,
        }
    )

    def rx_rate(self, now: float) -> float:
        while self.rx_times and now - self.rx_times[0] > 1.0:
            self.rx_times.popleft()
        return float(len(self.rx_times))

    def lost_percent(self) -> float:
        expected = self.valid_count + self.lost
        if expected <= 0:
            return 0.0
        return self.lost * 100.0 / expected


class ControllerUdpReceiver:
    def __init__(self, bind_ip: str = BIND_IP, port: int = PORT) -> None:
        self.bind_ip = bind_ip
        self.port = port
        self.sock: socket.socket | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.stats = ReceiverStats()
        self.latest_frame: dict | None = None
        self.latest_state = self._empty_state()
        self.timeout_ms = DEFAULT_FAILSAFE_TIMEOUT_MS
        self.estop_latched = False

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.bind_ip, self.port))
        self.sock.settimeout(0.02)
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._receive_loop, name="ControllerUdpReceiver", daemon=True)
        self.thread.start()
        print(f"[udp] listening for ControllerFrame V2 on {self.bind_ip}:{self.port}")

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1.0)
        if self.sock:
            self.sock.close()
            self.sock = None

    def _receive_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                assert self.sock is not None
                data, addr = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                frame = parse_controller_frame(data)
            except ControllerFrameError as exc:
                self._note_bad_packet(exc.reason)
                continue
            except Exception:
                self._note_bad_packet("other")
                continue

            self._note_valid_frame(frame, addr, time.perf_counter())

    def _note_bad_packet(self, reason: str) -> None:
        with self.lock:
            if reason not in self.stats.bad_packets:
                reason = "other"
            self.stats.bad_packets[reason] += 1

    def _note_valid_frame(self, frame: dict, addr: Tuple[str, int], now: float) -> None:
        with self.lock:
            self.stats.valid_count += 1
            self.stats.last_addr = addr
            self.stats.rx_times.append(now)

            if self.stats.last_frame_at:
                interval_ms = (now - self.stats.last_frame_at) * 1000.0
                if self.stats.last_interval_ms:
                    self.stats.jitter_ms = self.stats.jitter_ms * 0.85 + abs(interval_ms - self.stats.last_interval_ms) * 0.15
                self.stats.last_interval_ms = interval_ms
            self.stats.last_frame_at = now

            seq = int(frame["seq"])
            if self.stats.last_seq is not None:
                expected_seq = (self.stats.last_seq + 1) & 0xFFFF
                if seq != expected_seq:
                    ahead = (seq - expected_seq) & 0xFFFF
                    if ahead < 0x8000:
                        self.stats.lost += ahead
                    else:
                        self.stats.ooo += 1
            self.stats.last_seq = seq

            self.timeout_ms = int(clamp(frame.get("failsafe_timeout_ms", DEFAULT_FAILSAFE_TIMEOUT_MS), MIN_FAILSAFE_TIMEOUT_MS, MAX_FAILSAFE_TIMEOUT_MS))
            reset_requested = bool(frame["buttons"].get("VIRTUAL_RESET", False))
            frame_estop = bool(frame["flags"].get("estop", False))
            if reset_requested:
                self.estop_latched = False
            elif frame_estop:
                self.estop_latched = True
            # Reset has priority over an ESTOP bit in the same frame so a clear pulse
            # can recover from stale local ESTOP toggles on the sender.
            self.latest_frame = frame

    def update_state(self) -> dict:
        now = time.perf_counter()
        with self.lock:
            self.latest_state = self._build_state_locked(now)
            return copy.deepcopy(self.latest_state)

    def get_latest_state(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.latest_state)

    def _build_state_locked(self, now: float) -> dict:
        if self.latest_frame is None or not self.stats.last_frame_at:
            state = self._empty_state()
            state["stats"]["bad_packets"] = dict(self.stats.bad_packets)
            return state

        age_ms = (now - self.stats.last_frame_at) * 1000.0
        warning = age_ms > WARNING_TIMEOUT_MS
        remote_timeout = age_ms > self.timeout_ms
        if remote_timeout:
            self.estop_latched = True

        frame = self.latest_frame
        flags = dict(frame["flags"])
        flags["estop"] = bool(self.estop_latched)

        safe_output = warning or remote_timeout or self.estop_latched

        axes = dict(frame["axes"])
        buttons = dict(frame["buttons"])
        if safe_output:
            axes = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0}
            buttons = {name: False for name in buttons}

        now_rate = self.stats.rx_rate(now)
        return {
            "online": not remote_timeout,
            "warning": warning and not remote_timeout,
            "remote_timeout": remote_timeout,
            "seq": frame["seq"],
            "age_ms": age_ms,
            "jitter_ms": self.stats.jitter_ms,
            "lost": self.stats.lost,
            "ooo": self.stats.ooo,
            "lost_percent": self.stats.lost_percent(),
            "rx_rate": now_rate,
            "from": self.stats.last_addr,
            "failsafe_timeout_ms": self.timeout_ms,
            "flags": flags,
            "axes": axes,
            "buttons": buttons,
            "frame": copy.deepcopy(frame),
            "stats": {
                "valid_count": self.stats.valid_count,
                "bad_packets": dict(self.stats.bad_packets),
            },
        }

    @staticmethod
    def _empty_state() -> dict:
        return {
            "online": False,
            "warning": False,
            "remote_timeout": False,
            "seq": None,
            "age_ms": 0.0,
            "jitter_ms": 0.0,
            "lost": 0,
            "ooo": 0,
            "lost_percent": 0.0,
            "rx_rate": 0.0,
            "from": None,
            "failsafe_timeout_ms": DEFAULT_FAILSAFE_TIMEOUT_MS,
            "flags": {
                "enable": False,
                "estop": False,
                "full_state": False,
                "heartbeat": False,
                "manual_mode": False,
                "auto_mode": False,
            },
            "axes": {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0},
            "buttons": {},
            "frame": None,
            "stats": {"valid_count": 0, "bad_packets": {}},
        }


def format_axes(axes: dict) -> str:
    return (
        f"L({axes.get('lx', 0.0):+.2f},{axes.get('ly', 0.0):+.2f}) "
        f"R({axes.get('rx', 0.0):+.2f},{axes.get('ry', 0.0):+.2f})"
    )


def format_buttons(buttons: dict) -> str:
    pressed = [name for name, value in buttons.items() if value]
    return ",".join(pressed) if pressed else "-"


def format_frame(frame: dict | None) -> str:
    if not frame:
        return "{}"
    raw = frame.get("raw", {})
    compact = {
        "magic": f"0x{frame.get('magic', 0):04X}",
        "version": frame.get("version"),
        "msg_type": frame.get("msg_type"),
        "length": frame.get("length"),
        "flags_raw": frame.get("flags_raw"),
        "seq": frame.get("seq"),
        "failsafe_timeout_ms": frame.get("failsafe_timeout_ms"),
        "timestamp_ms": frame.get("timestamp_ms"),
        "buttons_low": raw.get("buttons_low"),
        "buttons_high": raw.get("buttons_high"),
        "axis_lx": raw.get("axis_lx"),
        "axis_ly": raw.get("axis_ly"),
        "axis_rx": raw.get("axis_rx"),
        "axis_ry": raw.get("axis_ry"),
        "reserved": raw.get("reserved", b"").hex() if isinstance(raw.get("reserved"), (bytes, bytearray)) else raw.get("reserved"),
        "crc32": f"0x{raw.get('crc32', 0):08X}",
    }
    return repr(compact)


def format_flags(flags: dict) -> str:
    active = [name for name, value in flags.items() if value]
    return ",".join(active) if active else "-"


def format_bad_packets(bad_packets: dict) -> str:
    active = [f"{name}={count}" for name, count in bad_packets.items() if count]
    return " ".join(active) if active else "-"


def build_status_block(state: dict) -> str:
    timestamp = time.strftime("%H:%M:%S")
    addr = state.get("from")
    addr_text = f"{addr[0]}:{addr[1]}" if addr else "-"
    bad_packets = state["stats"].get("bad_packets", {})
    bad_total = sum(bad_packets.values())

    if state["remote_timeout"]:
        status_text = "TIMEOUT -> ESTOP"
    elif state["flags"].get("estop", False):
        status_text = "ESTOP"
    elif state.get("warning"):
        status_text = "WARN"
    elif state.get("online"):
        status_text = "ONLINE"
    else:
        status_text = "WAITING"

    lines = [
        f"[{timestamp}] ControllerFrame V2 receiver  status={status_text}",
        (
            f"  link      from={addr_text} seq={state['seq']} "
            f"rx={state['rx_rate']:.0f}/s age={state['age_ms']:.0f}ms "
            f"failsafe={state['failsafe_timeout_ms']}ms"
        ),
        (
            f"  quality   lost={state['lost']} ({state['lost_percent']:.2f}%) "
            f"ooo={state['ooo']} jitter={state['jitter_ms']:.1f}ms "
            f"bad={bad_total}"
        ),
        f"  axes      {format_axes(state['axes'])}",
        f"  flags     {format_flags(state['flags'])}",
        f"  buttons   {format_buttons(state['buttons'])}",
    ]
    if bad_total:
        lines.append(f"  bad_pkts  {format_bad_packets(bad_packets)}")
    if state.get("frame"):
        frame = state["frame"]
        raw = frame.get("raw", {})
        lines.append(
            "  frame     "
            f"magic=0x{frame.get('magic', 0):04X} ver={frame.get('version')} "
            f"type={frame.get('msg_type')} len={frame.get('length')} "
            f"flags_raw={frame.get('flags_raw')} ts={frame.get('timestamp_ms')} "
            f"crc=0x{raw.get('crc32', 0):08X}"
        )
    return "\n".join(lines)


def build_status_line(state: dict) -> str:
    timestamp = time.strftime("%H:%M:%S")
    axes_text = format_axes(state["axes"])
    frame_text = format_frame(state.get("frame"))
    if state["remote_timeout"]:
        return f"[{timestamp}] TIMEOUT age={state['age_ms']:.0f}ms -> ESTOP axes={axes_text} frame={frame_text}"

    addr = state.get("from")
    addr_text = f"{addr[0]}:{addr[1]}" if addr else "-"
    if state["flags"].get("estop", False):
        state_text = "ESTOP"
    elif state.get("warning"):
        state_text = "WARN"
    elif state.get("online"):
        state_text = "online"
    else:
        state_text = "waiting"

    bad_packets = state["stats"].get("bad_packets", {})
    bad_total = sum(bad_packets.values())
    bad_text = f" bad={bad_total}" if bad_total else ""
    return (
        f"[{timestamp}] {state_text:<7} from={addr_text:<21} seq={str(state['seq']):<5} "
        f"rx={state['rx_rate']:3.0f}/s lost={state['lost']}({state['lost_percent']:.2f}%) "
        f"ooo={state['ooo']} jitter={state['jitter_ms']:4.1f}ms age={state['age_ms']:4.0f}ms "
        f"axes={axes_text} buttons={format_buttons(state['buttons'])}{bad_text} frame={frame_text}"
    )
