#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Low-rate target-map UDP messages.

This channel is intentionally separate from ControllerFrame V2 so map editing
cannot disturb the real-time controller stream.
"""

from __future__ import annotations

import copy
import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from core.udp_sender import LOCAL_IP, TARGET_IP, TARGET_PORT

MAP_MESSAGE_PORT = TARGET_PORT + 1
MAP_MESSAGE_TYPE = "target_map"
MAP_WIDTH = 3
MAP_HEIGHT = 6
MAP_ALLOWED_VALUES = {0, 1, 2, 3}


@dataclass
class MapReceiverStats:
    valid_count: int = 0
    bad_count: int = 0
    last_addr: Tuple[str, int] | None = None
    last_received_at: float = 0.0
    last_error: str = ""


def build_target_map_payload(mode: str, grid: List[List[int]], timestamp: float | None = None) -> Dict[str, Any]:
    payload = {
        "type": MAP_MESSAGE_TYPE,
        "mode": str(mode),
        "width": MAP_WIDTH,
        "height": MAP_HEIGHT,
        "grid": grid,
        "timestamp": time.time() if timestamp is None else float(timestamp),
    }
    validate_target_map_payload(payload)
    return payload


def validate_target_map_payload(payload: Dict[str, Any]) -> None:
    if payload.get("type") != MAP_MESSAGE_TYPE:
        raise ValueError(f"invalid map message type: {payload.get('type')!r}")
    if int(payload.get("width", 0)) != MAP_WIDTH:
        raise ValueError(f"invalid map width: {payload.get('width')!r}")
    if int(payload.get("height", 0)) != MAP_HEIGHT:
        raise ValueError(f"invalid map height: {payload.get('height')!r}")

    grid = payload.get("grid")
    if not isinstance(grid, list) or len(grid) != MAP_HEIGHT:
        raise ValueError("grid must be a 6x3 list")
    for row_index, row in enumerate(grid):
        if not isinstance(row, list) or len(row) != MAP_WIDTH:
            raise ValueError(f"grid row {row_index} must contain 3 cells")
        for value in row:
            if int(value) not in MAP_ALLOWED_VALUES:
                raise ValueError(f"invalid cell value: {value!r}")


def send_target_map_payload(
    payload: Dict[str, Any],
    local_ip: str = LOCAL_IP,
    target_ip: str = TARGET_IP,
    target_port: int = MAP_MESSAGE_PORT,
) -> int:
    validate_target_map_payload(payload)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((local_ip, 0))
        return sock.sendto(data, (target_ip, int(target_port)))
    finally:
        sock.close()


def format_target_map(payload: Dict[str, Any]) -> str:
    mode = payload.get("mode", "-")
    grid = payload.get("grid", [])
    rows = ["".join(str(cell) for cell in row) for row in grid]
    return f"mode={mode} grid={'/'.join(rows)}"


class TargetMapUdpReceiver:
    def __init__(self, bind_ip: str = "0.0.0.0", port: int = MAP_MESSAGE_PORT) -> None:
        self.bind_ip = bind_ip
        self.port = int(port)
        self.sock: socket.socket | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.stats = MapReceiverStats()
        self.latest_target_map: Dict[str, Any] | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.bind_ip, self.port))
        self.sock.settimeout(0.05)
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._receive_loop, name="TargetMapUdpReceiver", daemon=True)
        self.thread.start()
        print(f"[map] listening for target-map JSON on {self.bind_ip}:{self.port}")

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1.0)
        if self.sock:
            self.sock.close()
            self.sock = None

    def get_latest_target_map(self) -> Dict[str, Any] | None:
        with self.lock:
            return copy.deepcopy(self.latest_target_map)

    def _receive_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                assert self.sock is not None
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                payload = json.loads(data.decode("utf-8"))
                validate_target_map_payload(payload)
            except Exception as exc:
                self._note_bad_packet(str(exc))
                continue

            self._note_valid_map(payload, addr)

    def _note_bad_packet(self, reason: str) -> None:
        with self.lock:
            self.stats.bad_count += 1
            self.stats.last_error = reason
        print(f"[map] bad target-map packet: {reason}")

    def _note_valid_map(self, payload: Dict[str, Any], addr: Tuple[str, int]) -> None:
        now = time.time()
        with self.lock:
            self.latest_target_map = copy.deepcopy(payload)
            self.stats.valid_count += 1
            self.stats.last_addr = addr
            self.stats.last_received_at = now
            self.stats.last_error = ""
        print(f"[map] received from {addr[0]}:{addr[1]} {format_target_map(payload)}")
        self.handle_target_map(payload)

    def handle_target_map(self, payload: Dict[str, Any]) -> None:
        # TODO: 接入 R1 -> 后续节点的 ROS2 Action / apriltag 通信代码。
        _ = payload
