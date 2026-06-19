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
    build_status_block,
    build_status_line,
)


def parse_args() -> argparse.Namespace:
    params = get_section("udp_receiver")
    default_log_hz = params.get("log_hz")
    default_print_interval = params.get("print_interval")
    if default_print_interval is None:
        default_print_interval = 1.0 / max(float(default_log_hz), 0.01) if default_log_hz else PRINT_INTERVAL_SECONDS

    parser = argparse.ArgumentParser(description="ControllerFrame V2 UDP receiver with 100 Hz state loop.")
    parser.add_argument("--bind-ip", default=params.get("bind_ip", BIND_IP))
    parser.add_argument("--port", type=int, default=params.get("port", PORT))
    parser.add_argument("--control-hz", type=float, default=params.get("control_hz", CONTROL_HZ))
    parser.add_argument("--print-interval", type=float, default=default_print_interval)
    parser.add_argument(
        "--log-hz",
        type=float,
        default=default_log_hz,
        help="Receiver debug output frequency in Hz. Overrides --print-interval when set.",
    )
    parser.add_argument(
        "--log-format",
        choices=("block", "line"),
        default=params.get("log_format", "block"),
        help="Receiver debug output style. 'block' is easier to scan; 'line' is compact.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    receiver = ControllerUdpReceiver(bind_ip=args.bind_ip, port=args.port)
    receiver.start()

    period = 1.0 / max(args.control_hz, 1.0)
    print_interval = 1.0 / max(args.log_hz, 0.01) if args.log_hz else args.print_interval
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
                if args.log_format == "line":
                    print(build_status_line(state), flush=True)
                else:
                    print(build_status_block(state), flush=True)
                next_print = now + max(print_interval, 0.01)

            next_tick += period
            if next_tick < now - period:
                next_tick = now + period
    except KeyboardInterrupt:
        print("[udp] stopped")
    finally:
        receiver.stop()


if __name__ == "__main__":
    main()
