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
from core.udp_sender import (
    FAILSAFE_TIMEOUT_MS,
    LOCAL_IP,
    SEND_HZ,
    TARGET_IP,
    TARGET_PORT,
    ControllerUdpSender,
)


def parse_args() -> argparse.Namespace:
    params = get_section("udp_sender")
    parser = argparse.ArgumentParser(description="Standalone ControllerFrame V2 UDP sender.")
    parser.add_argument("--local-ip", default=params.get("local_ip", LOCAL_IP))
    parser.add_argument("--target-ip", default=params.get("target_ip", TARGET_IP))
    parser.add_argument("--target-port", type=int, default=params.get("target_port", TARGET_PORT))
    parser.add_argument("--send-hz", type=float, default=params.get("send_hz", SEND_HZ))
    parser.add_argument("--failsafe-timeout-ms", type=int, default=params.get("failsafe_timeout_ms", FAILSAFE_TIMEOUT_MS))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sender = ControllerUdpSender(
        local_ip=args.local_ip,
        target_ip=args.target_ip,
        target_port=args.target_port,
        send_hz=args.send_hz,
        failsafe_timeout_ms=args.failsafe_timeout_ms,
        print_status=True,
    )
    sender.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[udp] stopped")
    finally:
        sender.stop()


if __name__ == "__main__":
    main()
