#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UDP receiver for LAN testing the Steam Deck controller sender.

Run on the Windows laptop:
    python udp_receiver.py --bind-ip 10.20.99.23 --port 5005
"""

from __future__ import annotations

import argparse
import json
import socket
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Tuple


DEFAULT_BIND_IP = "10.20.99.23"
DEFAULT_PORT = 5005
PRINT_INTERVAL_SECONDS = 1.0
STALE_SECONDS = 2.0

BUTTON_LABELS = {
    "2": "...",
    "3": "A",
    "4": "B",
    "5": "X",
    "6": "Y",
    "7": "LB",
    "8": "RB",
    "9": "LT",
    "10": "RT",
    "11": "VIEW",
    "12": "MENU",
    "13": "STEAM",
    "14": "L3",
    "15": "R3",
    "16": "UP",
    "17": "DOWN",
    "18": "LEFT",
    "19": "RIGHT",
    "20": "L4",
    "21": "R4",
    "22": "L5",
    "23": "R5",
}


@dataclass
class ReceiverStats:
    packet_count: int = 0
    ack_count: int = 0
    lost_count: int = 0
    out_of_order_count: int = 0
    decode_errors: int = 0
    last_seq: int | None = None
    last_addr: Tuple[str, int] | None = None
    last_packet_at: float = 0.0
    last_interval_ms: float = 0.0
    jitter_ms: float = 0.0
    rx_times: Deque[float] = field(default_factory=deque)
    latest_axes: Dict[str, float] = field(default_factory=dict)
    latest_buttons: Dict[str, bool] = field(default_factory=dict)

    def note_packet(self, seq: int, addr: Tuple[str, int], now: float) -> None:
        self.packet_count += 1
        self.last_addr = addr
        self.rx_times.append(now)

        if self.last_packet_at:
            interval_ms = (now - self.last_packet_at) * 1000.0
            if self.last_interval_ms:
                self.jitter_ms = self.jitter_ms * 0.85 + abs(interval_ms - self.last_interval_ms) * 0.15
            self.last_interval_ms = interval_ms
        self.last_packet_at = now

        if self.last_seq is not None:
            if seq > self.last_seq + 1:
                self.lost_count += seq - self.last_seq - 1
            elif seq <= self.last_seq:
                self.out_of_order_count += 1
        self.last_seq = seq

    def rx_rate(self, now: float) -> float:
        while self.rx_times and now - self.rx_times[0] > 1.0:
            self.rx_times.popleft()
        return float(len(self.rx_times))

    def loss_percent(self) -> float:
        total_expected = self.packet_count + self.lost_count
        if not total_expected:
            return 0.0
        return self.lost_count * 100.0 / total_expected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Receive Steam Deck controller UDP packets and send ACKs.")
    parser.add_argument("--bind-ip", default=DEFAULT_BIND_IP, help="Windows LAN IP to bind.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="UDP port to listen on.")
    parser.add_argument("--print-interval", type=float, default=PRINT_INTERVAL_SECONDS, help="Seconds between status lines.")
    return parser.parse_args()


def format_axes(axes: Dict[str, float]) -> str:
    left_x = float(axes.get("0", 0.0))
    left_y = float(axes.get("1", 0.0))
    right_x = float(axes.get("2", 0.0))
    right_y = float(axes.get("3", 0.0))
    return f"L({left_x:+.2f},{left_y:+.2f}) R({right_x:+.2f},{right_y:+.2f})"


def format_buttons(buttons: Dict[str, bool]) -> str:
    pressed = [BUTTON_LABELS.get(key, key) for key, value in buttons.items() if value]
    return ",".join(pressed[:8]) if pressed else "-"


def handle_packet(sock: socket.socket, payload: bytes, addr: Tuple[str, int], stats: ReceiverStats) -> None:
    now = time.monotonic()
    try:
        packet = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        stats.decode_errors += 1
        return

    if packet.get("type") != "controller_state":
        return

    seq = packet.get("seq")
    if not isinstance(seq, int):
        stats.decode_errors += 1
        return

    stats.note_packet(seq, addr, now)
    stats.latest_axes = packet.get("axes", {})
    stats.latest_buttons = packet.get("buttons_physical", {})

    ack = {
        "type": "ack",
        "seq": seq,
        "receiver": "windows_udp_receiver",
        "rx_unix": time.time(),
    }
    sock.sendto(json.dumps(ack, separators=(",", ":")).encode("utf-8"), addr)
    stats.ack_count += 1


def print_status(stats: ReceiverStats) -> None:
    now = time.monotonic()
    age_ms = (now - stats.last_packet_at) * 1000.0 if stats.last_packet_at else 0.0
    state = "online" if stats.last_packet_at and now - stats.last_packet_at <= STALE_SECONDS else "waiting"
    addr_text = f"{stats.last_addr[0]}:{stats.last_addr[1]}" if stats.last_addr else "-"
    seq_text = str(stats.last_seq) if stats.last_seq is not None else "-"
    print(
        f"[{time.strftime('%H:%M:%S')}] {state:<7} from={addr_text:<21} "
        f"seq={seq_text:<9} rx={stats.rx_rate(now):4.0f}/s ack={stats.ack_count:<7} "
        f"lost={stats.lost_count}({stats.loss_percent():.2f}%) ooo={stats.out_of_order_count} "
        f"jitter={stats.jitter_ms:5.1f}ms age={age_ms:5.0f}ms "
        f"axes={format_axes(stats.latest_axes)} buttons={format_buttons(stats.latest_buttons)}"
    )


def main() -> None:
    args = parse_args()
    stats = ReceiverStats()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind_ip, args.port))
    sock.settimeout(0.2)

    print(f"[udp] listening on {args.bind_ip}:{args.port}")
    print("[udp] allow Python through Windows Firewall if packets do not arrive.")

    next_print_at = time.monotonic()
    try:
        while True:
            try:
                payload, addr = sock.recvfrom(65535)
            except socket.timeout:
                pass
            else:
                handle_packet(sock, payload, addr, stats)

            now = time.monotonic()
            if now >= next_print_at:
                print_status(stats)
                next_print_at = now + max(args.print_interval, 0.2)
    except KeyboardInterrupt:
        print("\n[udp] stopped")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
