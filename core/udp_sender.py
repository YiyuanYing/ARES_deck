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
from typing import Any, Callable, Dict, Iterable, List

from core.protocol import BUTTON_NAMES, build_controller_frame


LOCAL_IP = "10.20.12.220"
TARGET_IP = "10.20.99.23"
TARGET_PORT = 5005
SEND_HZ = 100.0
FAILSAFE_TIMEOUT_MS = 150


@dataclass(frozen=True)
class UdpTarget:
    ip: str
    port: int = TARGET_PORT
    map_port: int = TARGET_PORT + 1

    @property
    def control_addr(self) -> tuple[str, int]:
        return self.ip, int(self.port)

    @property
    def map_addr(self) -> tuple[str, int]:
        return self.ip, int(self.map_port)

    def label(self) -> str:
        return f"{self.ip}:{int(self.port)}"


@dataclass
class TargetSendMetrics:
    ip: str
    port: int
    map_port: int
    connected: bool = False
    last_error: str = ""
    tx_count: int = 0
    tx_rate: float = 0.0

    def label(self) -> str:
        return f"{self.ip}:{int(self.port)}"


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
    targets: List[TargetSendMetrics] = field(default_factory=list)
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


def parse_udp_target(value: str, default_port: int = TARGET_PORT, default_map_port: int | None = None) -> UdpTarget:
    text = str(value).strip()
    if not text:
        raise ValueError("target must not be empty")

    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"target must be IP:PORT[:MAP_PORT], got {value!r}")

    ip = parts[0].strip()
    if not ip:
        raise ValueError(f"target IP must not be empty: {value!r}")

    port = int(parts[1]) if len(parts) >= 2 and parts[1] else int(default_port)
    map_port = int(parts[2]) if len(parts) >= 3 and parts[2] else int(default_map_port if default_map_port is not None else port + 1)
    return UdpTarget(ip=ip, port=port, map_port=map_port)


def normalize_udp_targets(
    targets: Iterable[Any] | None = None,
    *,
    fallback_ip: str = TARGET_IP,
    fallback_port: int = TARGET_PORT,
    fallback_map_port: int | None = None,
) -> List[UdpTarget]:
    normalized: List[UdpTarget] = []
    if targets:
        for item in targets:
            if isinstance(item, UdpTarget):
                target = item
            elif isinstance(item, str):
                target = parse_udp_target(item, fallback_port, fallback_map_port)
            elif isinstance(item, dict):
                ip = str(item.get("ip", item.get("target_ip", ""))).strip()
                if not ip:
                    raise ValueError(f"target entry missing ip: {item!r}")
                port = int(item.get("port", item.get("target_port", fallback_port)))
                map_port = int(item.get("map_port", port + 1 if fallback_map_port is None else fallback_map_port))
                target = UdpTarget(ip=ip, port=port, map_port=map_port)
            else:
                raise ValueError(f"unsupported target entry: {item!r}")
            normalized.append(target)

    if not normalized:
        port = int(fallback_port)
        normalized.append(UdpTarget(str(fallback_ip), port, int(fallback_map_port if fallback_map_port is not None else port + 1)))
    return normalized


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
        targets: Iterable[Any] | None = None,
        send_hz: float = SEND_HZ,
        failsafe_timeout_ms: int = FAILSAFE_TIMEOUT_MS,
        print_status: bool = False,
    ) -> None:
        self.state_provider = state_provider or empty_state_snapshot
        self.local_ip = local_ip
        self.targets = normalize_udp_targets(targets, fallback_ip=target_ip, fallback_port=target_port)
        self.target_ip = self.targets[0].ip
        self.target_port = self.targets[0].port
        self.target_addr = self.targets[0].control_addr
        self.period = 1.0 / max(send_hz, 1.0)
        self.failsafe_timeout_ms = failsafe_timeout_ms
        self.print_status = print_status
        self.metrics = SenderMetrics(
            local_ip=detect_local_ip(self.target_ip),
            bind_ip=local_ip,
            target_ip=self.target_ip,
            target_port=self.target_port,
            targets=[TargetSendMetrics(target.ip, target.port, target.map_port) for target in self.targets],
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
                targets=[
                    TargetSendMetrics(
                        target.ip,
                        target.port,
                        target.map_port,
                        target.connected,
                        target.last_error,
                        target.tx_count,
                        target.tx_rate,
                    )
                    for target in self.metrics.targets
                ],
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
            self.metrics.status_text = f"UDP binary -> {self.target_summary()}"
        print(f"[udp] sending ControllerFrame V2 from {self.sock.getsockname()} to {self.target_summary()}")
        return True

    def target_summary(self) -> str:
        if len(self.targets) == 1:
            return self.targets[0].label()
        return ", ".join(target.label() for target in self.targets[:2]) + (f", +{len(self.targets) - 2} more" if len(self.targets) > 2 else "")

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
        successes = 0
        errors: List[str] = []
        for index, target in enumerate(self.targets):
            try:
                self.sock.sendto(frame, target.control_addr)
            except OSError as exc:
                errors.append(f"{target.label()}: {exc}")
                with self.lock:
                    if index < len(self.metrics.targets):
                        self.metrics.targets[index].connected = False
                        self.metrics.targets[index].last_error = str(exc)
                continue
            successes += 1
            with self.lock:
                if index < len(self.metrics.targets):
                    self.metrics.targets[index].connected = True
                    self.metrics.targets[index].last_error = ""
                    self.metrics.targets[index].tx_count += 1

        self.tx_window.append(now)
        cutoff = now - 1.0
        self.tx_window = [item for item in self.tx_window if item >= cutoff]
        with self.lock:
            self.metrics.connected = successes > 0
            self.metrics.status_text = f"UDP binary -> {successes}/{len(self.targets)} targets"
            self.metrics.last_error = "; ".join(errors)
            self.metrics.tx_count += successes
            self.metrics.tx_rate = float(len(self.tx_window))
            for target_metric in self.metrics.targets:
                target_metric.tx_rate = float(len(self.tx_window)) if target_metric.connected else 0.0
            self.metrics.seq = self.seq
            self.metrics.payload_bytes = len(frame)
            self.metrics.latest_axes = dict(axes)
            self.metrics.latest_buttons = {int(key): bool(value) for key, value in buttons.items()}

        if self.print_status and now - self.last_print_at >= 1.0:
            metrics = self.snapshot_metrics()
            print(
                f"tx={metrics.tx_rate:.0f}/s targets={len(metrics.targets)} seq={metrics.seq} "
                f"axes={format_axes(metrics.latest_axes)} buttons={format_buttons(metrics.latest_buttons)}"
            )
            self.last_print_at = now

        self.seq = (self.seq + 1) & 0xFFFF
