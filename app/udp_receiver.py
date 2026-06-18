#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.params import get_section
from core.udp_receiver import (
    BIND_IP,
    CONTROL_HZ,
    PORT,
    PRINT_INTERVAL_SECONDS,
    ControllerUdpReceiver,
    build_status_line,
)


def parse_args() -> argparse.Namespace:
    params = get_section("udp_receiver")
    parser = argparse.ArgumentParser(description="ControllerFrame V2 UDP receiver with 100 Hz state loop.")
    parser.add_argument("--bind-ip", default=params.get("bind_ip", BIND_IP))
    parser.add_argument("--port", type=int, default=params.get("port", PORT))
    parser.add_argument("--control-hz", type=float, default=params.get("control_hz", CONTROL_HZ))
    parser.add_argument("--print-interval", type=float, default=params.get("print_interval", PRINT_INTERVAL_SECONDS))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    receiver = ControllerUdpReceiver(bind_ip=args.bind_ip, port=args.port)
    receiver.start()

    period = 1.0 / max(args.control_hz, 1.0)
    next_tick = time.perf_counter()
    next_print = next_tick
    try:
        while True:
            now = time.perf_counter()
            if now < next_tick:
                time.sleep(min(next_tick - now, period))
                continue

            state = receiver.update_state()
            if now >= next_print:
                print(f"\r{build_status_line(state):<700}", end="", flush=True)
                next_print = now + max(args.print_interval, 0.01)

            next_tick += period
            if next_tick < now - period:
                next_tick = now + period
    except KeyboardInterrupt:
        print("\n[udp] stopped")
    finally:
        receiver.stop()


if __name__ == "__main__":
    main()
