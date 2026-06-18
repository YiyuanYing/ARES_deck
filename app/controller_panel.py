#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.params import get_section
from core.udp_sender import FAILSAFE_TIMEOUT_MS, LOCAL_IP, SEND_HZ, TARGET_IP, TARGET_PORT
from ui.config import TOUCH_DEVICE_PATH, TOUCH_INVERT_X, TOUCH_INVERT_Y, TOUCH_SWAP_XY
from ui.panel import ControllerPanel

def parse_args() -> argparse.Namespace:
    params = get_section("controller_panel")
    parser = argparse.ArgumentParser(description="Steam Deck controller GUI + ControllerFrame V2 UDP sender.")
    parser.add_argument("--local-ip", default=params.get("local_ip", LOCAL_IP), help="Steam Deck LAN IP used for UDP bind.")
    parser.add_argument("--remote-ip", "--target-ip", dest="remote_ip", default=params.get("remote_ip", TARGET_IP), help="Receiver LAN IP.")
    parser.add_argument("--port", type=int, default=params.get("port", TARGET_PORT), help="UDP receiver port.")
    parser.add_argument("--send-hz", type=float, default=params.get("send_hz", SEND_HZ), help="Controller packets per second.")
    parser.add_argument("--failsafe-timeout-ms", type=int, default=params.get("failsafe_timeout_ms", FAILSAFE_TIMEOUT_MS), help="Failsafe timeout encoded in each frame.")
    parser.add_argument("--touch-device", default=params.get("touch_device", TOUCH_DEVICE_PATH), help="Linux evdev touchscreen path, e.g. /dev/input/event4.")
    parser.add_argument("--no-touch-reader", action="store_true", default=params.get("no_touch_reader", False), help="Disable evdev touchscreen reader; keep mouse fallback.")
    parser.add_argument("--touch-swap-xy", action="store_true", default=params.get("touch_swap_xy", TOUCH_SWAP_XY), help="Swap touchscreen X/Y axes.")
    parser.add_argument("--touch-invert-x", action="store_true", default=params.get("touch_invert_x", TOUCH_INVERT_X), help="Invert touchscreen X axis.")
    parser.add_argument("--touch-invert-y", action="store_true", default=params.get("touch_invert_y", TOUCH_INVERT_Y), help="Invert touchscreen Y axis.")
    parser.add_argument("--debug-touch", action="store_true", default=params.get("debug_touch", False), help="Print raw and mapped touchscreen coordinates.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    panel = ControllerPanel(
        args.local_ip,
        args.remote_ip,
        args.port,
        args.send_hz,
        args.failsafe_timeout_ms,
        args.touch_device,
        args.no_touch_reader,
        args.touch_swap_xy,
        args.touch_invert_x,
        args.touch_invert_y,
        args.debug_touch,
    )
    panel.run()


if __name__ == "__main__":
    main()
