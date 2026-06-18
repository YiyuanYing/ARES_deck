#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UDP transport for ControllerFrame V2 sender.

The binary protocol itself lives in core/protocol.py. This module only
handles the UDP socket and the fixed-rate send loop.
"""

from __future__ import annotations

import argparse
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List

from core.protocol import BUTTON_NAMES, build_controller_frame


LOCAL_IP = "10.20.12.220"
TARGET_IP = "10.20.99.23"
TARGET_PORT = 5005
SEND_HZ = 100.0
FAILSAFE_TIMEOUT_MS = 150


@dataclass
class SenderMetrics:
    enabled: bool = True
    connected: bool = False
    status_text: str = "UDP sender starting"
    last_error: str = ""
    local_ip: str = LOCAL_IP
    bind_ip: str = LOCAL_IP
    target_ip: str = TARGET_IP
    target_port: int = TARGET_PORT
    tx_count: int = 0
    tx_rate: float = 0.0
    seq: int = 0
    payload_bytes: int = 0
    latest_axes: Dict[str, float] = field(default_factory=lambda: {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0})
    latest_buttons: Dict[int, bool] = field(default_factory=dict)


def detect_local_ip(target_ip: str) -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((target_ip, 9))
        return probe.getsockname()[0]
    except OSError:
        return "unknown"
    finally:
        probe.close()


def format_axes(axes: Dict[str, float]) -> str:
    return (
        f"L({axes.get('lx', 0.0):+.2f},{axes.get('ly', 0.0):+.2f}) "
        f"R({axes.get('rx', 0.0):+.2f},{axes.get('ry', 0.0):+.2f})"
    )


def format_buttons(buttons: Dict[int, bool]) -> str:
    pressed = [BUTTON_NAMES.get(button_id, str(button_id)) for button_id, value in sorted(buttons.items()) if value]
    return ",".join(pressed) if pressed else "-"


def empty_state_snapshot() -> dict:
    return {
        "axes": {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0},
        "buttons": {},
        "enable": True,
        "estop": False,
    }


class ControllerUdpSender:
    """Fixed-rate UDP sender for ControllerFrame V2."""

    def __init__(
        self,
        state_provider: Callable[[], dict] | None = None,
        local_ip: str = LOCAL_IP,
        target_ip: str = TARGET_IP,
        target_port: int = TARGET_PORT,
        send_hz: float = SEND_HZ,
        failsafe_timeout_ms: int = FAILSAFE_TIMEOUT_MS,
        print_status: bool = False,
    ) -> None:
        self.state_provider = state_provider or empty_state_snapshot
        self.local_ip = local_ip
        self.target_ip = target_ip
        self.target_port = target_port
        self.target_addr = (target_ip, target_port)
        self.period = 1.0 / max(send_hz, 1.0)
        self.failsafe_timeout_ms = failsafe_timeout_ms
        self.print_status = print_status
        self.metrics = SenderMetrics(
            local_ip=detect_local_ip(target_ip),
            bind_ip=local_ip,
            target_ip=target_ip,
            target_port=target_port,
        )

        self.sock: socket.socket | None = None
        self.seq = 0
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.tx_window: List[float] = []
        self.last_print_at = 0.0

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="ControllerUdpSender", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1.0)
        self._close_socket()

    def snapshot_metrics(self) -> SenderMetrics:
        with self.lock:
            return SenderMetrics(
                enabled=self.metrics.enabled,
                connected=self.metrics.connected,
                status_text=self.metrics.status_text,
                last_error=self.metrics.last_error,
                local_ip=self.metrics.local_ip,
                bind_ip=self.metrics.bind_ip,
                target_ip=self.metrics.target_ip,
                target_port=self.metrics.target_port,
                tx_count=self.metrics.tx_count,
                tx_rate=self.metrics.tx_rate,
                seq=self.metrics.seq,
                payload_bytes=self.metrics.payload_bytes,
                latest_axes=dict(self.metrics.latest_axes),
                latest_buttons=dict(self.metrics.latest_buttons),
            )

    def _open_socket(self) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind((self.local_ip, 0))
        except OSError as exc:
            with self.lock:
                self.metrics.enabled = False
                self.metrics.connected = False
                self.metrics.status_text = "UDP bind failed"
                self.metrics.last_error = str(exc)
            print(f"[udp] bind {self.local_ip}:0 failed: {exc}")
            self._close_socket()
            return False

        with self.lock:
            self.metrics.bind_ip = self.sock.getsockname()[0]
            self.metrics.connected = True
            self.metrics.status_text = f"UDP binary -> {self.target_ip}:{self.target_port}"
        print(f"[udp] sending ControllerFrame V2 from {self.sock.getsockname()} to {self.target_addr}")
        return True

    def _close_socket(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def _run(self) -> None:
        if not self._open_socket():
            return

        next_tick = time.perf_counter()
        while not self.stop_event.is_set():
            now = time.perf_counter()
            if now < next_tick:
                self.stop_event.wait(min(next_tick - now, self.period))
                continue

            self._send_once(now)
            next_tick += self.period
            if next_tick < now - self.period:
                next_tick = now + self.period

        self._close_socket()

    def _send_once(self, now: float) -> None:
        if self.sock is None:
            return

        snapshot = self.state_provider()
        axes = snapshot.get("axes", {})
        buttons = snapshot.get("buttons", {})
        enable = bool(snapshot.get("enable", True))
        estop = bool(snapshot.get("estop", False))

        frame = build_controller_frame(
            seq=self.seq,
            axes=axes,
            buttons=buttons,
            enable=enable,
            estop=estop,
            failsafe_timeout_ms=self.failsafe_timeout_ms,
        )
        try:
            self.sock.sendto(frame, self.target_addr)
        except OSError as exc:
            with self.lock:
                self.metrics.connected = False
                self.metrics.status_text = "UDP send failed"
                self.metrics.last_error = str(exc)
            return

        self.tx_window.append(now)
        cutoff = now - 1.0
        self.tx_window = [item for item in self.tx_window if item >= cutoff]
        with self.lock:
            self.metrics.connected = True
            self.metrics.status_text = f"UDP binary -> {self.target_ip}:{self.target_port}"
            self.metrics.last_error = ""
            self.metrics.tx_count += 1
            self.metrics.tx_rate = float(len(self.tx_window))
            self.metrics.seq = self.seq
            self.metrics.payload_bytes = len(frame)
            self.metrics.latest_axes = dict(axes)
            self.metrics.latest_buttons = {int(key): bool(value) for key, value in buttons.items()}

        if self.print_status and now - self.last_print_at >= 1.0:
            metrics = self.snapshot_metrics()
            print(
                f"tx={metrics.tx_rate:.0f}/s seq={metrics.seq} "
                f"axes={format_axes(metrics.latest_axes)} buttons={format_buttons(metrics.latest_buttons)}"
            )
            self.last_print_at = now

        self.seq = (self.seq + 1) & 0xFFFF
