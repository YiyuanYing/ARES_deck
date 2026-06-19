#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Low-rate UDP JSON messages.

This channel is intentionally separate from ControllerFrame V2 so map editing
and discrete action commands cannot disturb the real-time controller stream.
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
ACTION_COMMAND_MESSAGE_TYPE = "action_command"
MAP_WIDTH = 3
MAP_HEIGHT = 6
MAP_ALLOWED_VALUES = {0, 1, 2, 3}
ACTION_COMMAND_ACTIONS = {"select", "place", "release"}
ACTION_COMMAND_ROWS = {2, 3}
ACTION_COMMAND_COLS = {"left", "mid", "right"}


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


def build_action_command_payload(
    action: str,
    row: int | None = None,
    col: str | None = None,
    timestamp: float | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "type": ACTION_COMMAND_MESSAGE_TYPE,
        "action": str(action),
        "timestamp": time.time() if timestamp is None else float(timestamp),
    }
    if action == "select":
        payload["row"] = int(row) if row is not None else row
        payload["col"] = str(col).lower() if col is not None else col
    validate_action_command_payload(payload)
    return payload


def validate_action_command_payload(payload: Dict[str, Any]) -> None:
    if payload.get("type") != ACTION_COMMAND_MESSAGE_TYPE:
        raise ValueError(f"invalid action command message type: {payload.get('type')!r}")

    action = payload.get("action")
    if action not in ACTION_COMMAND_ACTIONS:
        raise ValueError(f"invalid action command: {action!r}")

    if action == "select":
        row = int(payload.get("row", 0))
        col = payload.get("col")
        if row not in ACTION_COMMAND_ROWS:
            raise ValueError(f"invalid action row: {payload.get('row')!r}")
        if col not in ACTION_COMMAND_COLS:
            raise ValueError(f"invalid action col: {col!r}")


def validate_low_rate_payload(payload: Dict[str, Any]) -> None:
    message_type = payload.get("type")
    if message_type == MAP_MESSAGE_TYPE:
        validate_target_map_payload(payload)
        return
    if message_type == ACTION_COMMAND_MESSAGE_TYPE:
        validate_action_command_payload(payload)
        return
    raise ValueError(f"invalid low-rate message type: {message_type!r}")


def send_low_rate_payload(
    payload: Dict[str, Any],
    local_ip: str = LOCAL_IP,
    target_ip: str = TARGET_IP,
    target_port: int = MAP_MESSAGE_PORT,
) -> int:
    validate_low_rate_payload(payload)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((local_ip, 0))
        return sock.sendto(data, (target_ip, int(target_port)))
    finally:
        sock.close()


def send_target_map_payload(
    payload: Dict[str, Any],
    local_ip: str = LOCAL_IP,
    target_ip: str = TARGET_IP,
    target_port: int = MAP_MESSAGE_PORT,
) -> int:
    validate_target_map_payload(payload)
    return send_low_rate_payload(payload, local_ip, target_ip, target_port)


def send_action_command_payload(
    payload: Dict[str, Any],
    local_ip: str = LOCAL_IP,
    target_ip: str = TARGET_IP,
    target_port: int = MAP_MESSAGE_PORT,
) -> int:
    validate_action_command_payload(payload)
    return send_low_rate_payload(payload, local_ip, target_ip, target_port)


def format_target_map(payload: Dict[str, Any]) -> str:
    mode = payload.get("mode", "-")
    grid = payload.get("grid", [])
    rows = ["".join(str(cell) for cell in row) for row in grid]
    return f"mode={mode} grid={'/'.join(rows)}"


def format_action_command(payload: Dict[str, Any]) -> str:
    action = payload.get("action", "-")
    if action == "select":
        return f"action=select row={payload.get('row')} col={payload.get('col')}"
    return f"action={action}"


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
        self.latest_action_command: Dict[str, Any] | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.bind_ip, self.port))
        self.sock.settimeout(0.05)
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._receive_loop, name="TargetMapUdpReceiver", daemon=True)
        self.thread.start()
        print(f"[json] listening for target-map/action-command JSON on {self.bind_ip}:{self.port}")

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

    def get_latest_action_command(self) -> Dict[str, Any] | None:
        with self.lock:
            return copy.deepcopy(self.latest_action_command)

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
                validate_low_rate_payload(payload)
            except Exception as exc:
                self._note_bad_packet(str(exc))
                continue

            self._note_valid_payload(payload, addr)

    def _note_bad_packet(self, reason: str) -> None:
        with self.lock:
            self.stats.bad_count += 1
            self.stats.last_error = reason
        print(f"[json] bad low-rate packet: {reason}")

    def _note_valid_payload(self, payload: Dict[str, Any], addr: Tuple[str, int]) -> None:
        now = time.time()
        with self.lock:
            if payload.get("type") == MAP_MESSAGE_TYPE:
                self.latest_target_map = copy.deepcopy(payload)
            elif payload.get("type") == ACTION_COMMAND_MESSAGE_TYPE:
                self.latest_action_command = copy.deepcopy(payload)
            self.stats.valid_count += 1
            self.stats.last_addr = addr
            self.stats.last_received_at = now
            self.stats.last_error = ""
        if payload.get("type") == MAP_MESSAGE_TYPE:
            print(f"[map] received from {addr[0]}:{addr[1]} {format_target_map(payload)}")
            self.handle_target_map(payload)
        elif payload.get("type") == ACTION_COMMAND_MESSAGE_TYPE:
            print(f"[action] received from {addr[0]}:{addr[1]} {format_action_command(payload)}")
            self.handle_action_command(payload)

    def handle_target_map(self, payload: Dict[str, Any]) -> None:
        # TODO: 接入 R1 -> 后续节点的 ROS2 Action / apriltag 通信代码。
        _ = payload

    def handle_action_command(self, payload: Dict[str, Any]) -> None:
        # TODO: 接入 R1 -> 后续节点的 ROS2 Action / apriltag 通信代码。
        _ = payload
