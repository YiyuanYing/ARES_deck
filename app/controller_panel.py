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
from core.udp_sender import FAILSAFE_TIMEOUT_MS, LOCAL_IP, SEND_HZ, TARGET_IP, TARGET_PORT, parse_udp_target, normalize_udp_targets
from ui.config import (
    BUTTON_ACTIVATION_MODES,
    DEFAULT_BUTTON_ACTIVATION_MODE,
    DEFAULT_MAP_MESSAGE_PORT,
    PHYSICAL_BUTTON_MODE_MAP,
    TOUCH_DEVICE_PATH,
    TOUCH_INVERT_X,
    TOUCH_INVERT_Y,
    TOUCH_SWAP_XY,
)
from ui.panel import ControllerPanel


def parse_button_modes(value: str | None) -> dict[int, str]:
    modes: dict[int, str] = {}
    if not value:
        return modes

    for item in str(value).split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            key_text, mode = item.split("=", 1)
        elif ":" in item:
            key_text, mode = item.split(":", 1)
        else:
            raise argparse.ArgumentTypeError(f"button mode item must be ID=mode: {item}")

        try:
            button_id = int(key_text.strip())
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid button id in mode item: {item}") from exc

        mode = mode.strip().lower()
        if mode not in BUTTON_ACTIVATION_MODES:
            choices = ", ".join(BUTTON_ACTIVATION_MODES)
            raise argparse.ArgumentTypeError(f"invalid activation mode '{mode}', expected one of: {choices}")
        modes[button_id] = mode
    return modes


def parse_args() -> argparse.Namespace:
    params = get_section("controller_panel")
    parser = argparse.ArgumentParser(description="Steam Deck controller GUI + ControllerFrame V2 UDP sender.")
    parser.add_argument("--local-ip", default=params.get("local_ip", LOCAL_IP), help="Steam Deck LAN IP used for UDP bind.")
    parser.add_argument("--remote-ip", "--target-ip", dest="remote_ip", default=params.get("remote_ip", TARGET_IP), help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=params.get("port", TARGET_PORT), help="UDP receiver port.")
    parser.add_argument(
        "--map-port",
        type=int,
        default=params.get("map_port", DEFAULT_MAP_MESSAGE_PORT),
        help="Low-rate target-map/action-command UDP JSON receiver port.",
    )
    parser.add_argument("--send-hz", type=float, default=params.get("send_hz", SEND_HZ), help="Controller packets per second.")
    parser.add_argument("--failsafe-timeout-ms", type=int, default=params.get("failsafe_timeout_ms", FAILSAFE_TIMEOUT_MS), help="Failsafe timeout encoded in each frame.")
    parser.add_argument("--touch-device", default=params.get("touch_device", TOUCH_DEVICE_PATH), help="Linux evdev touchscreen path, e.g. /dev/input/event4.")
    parser.add_argument("--no-touch-reader", action="store_true", default=params.get("no_touch_reader", False), help="Disable evdev touchscreen reader; keep mouse fallback.")
    parser.add_argument("--touch-swap-xy", action="store_true", default=params.get("touch_swap_xy", TOUCH_SWAP_XY), help="Swap touchscreen X/Y axes.")
    parser.add_argument("--touch-invert-x", action="store_true", default=params.get("touch_invert_x", TOUCH_INVERT_X), help="Invert touchscreen X axis.")
    parser.add_argument("--touch-invert-y", action="store_true", default=params.get("touch_invert_y", TOUCH_INVERT_Y), help="Invert touchscreen Y axis.")
    parser.add_argument("--debug-touch", action="store_true", default=params.get("debug_touch", False), help="Print raw and mapped touchscreen coordinates.")
    parser.add_argument(
        "--target",
        action="append",
        default=None,
        help="UDP receiver target as IP:PORT[:MAP_PORT]. Repeat to send to multiple targets.",
    )
    parser.add_argument(
        "--virtual-button-mode-default",
        choices=BUTTON_ACTIVATION_MODES,
        default=DEFAULT_BUTTON_ACTIVATION_MODE,
        help="Default activation mode for virtual touch buttons.",
    )
    parser.add_argument(
        "--virtual-button-modes",
        type=parse_button_modes,
        default=None,
        help="Temporary virtual activation override, e.g. 32=toggle,33=momentary.",
    )
    parser.add_argument(
        "--physical-button-mode-default",
        choices=BUTTON_ACTIVATION_MODES,
        default=DEFAULT_BUTTON_ACTIVATION_MODE,
        help="Default activation mode for physical controller buttons.",
    )
    parser.add_argument(
        "--physical-button-modes",
        type=parse_button_modes,
        default=None,
        help="Temporary physical activation override, e.g. 3=momentary,4=toggle.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    params = get_section("controller_panel")
    target_entries = args.target if args.target is not None else params.get("targets")
    targets = normalize_udp_targets(
        [parse_udp_target(item, args.port, args.map_port) for item in target_entries] if args.target is not None else target_entries,
        fallback_ip=args.remote_ip,
        fallback_port=args.port,
        fallback_map_port=args.map_port,
    )
    virtual_button_modes = dict(args.virtual_button_modes or {})
    physical_button_modes = dict(PHYSICAL_BUTTON_MODE_MAP)
    physical_button_modes.update(args.physical_button_modes or {})
    panel = ControllerPanel(
        args.local_ip,
        args.remote_ip,
        args.port,
        args.map_port,
        args.send_hz,
        args.failsafe_timeout_ms,
        args.touch_device,
        args.no_touch_reader,
        args.touch_swap_xy,
        args.touch_invert_x,
        args.touch_invert_y,
        args.debug_touch,
        args.virtual_button_mode_default,
        virtual_button_modes,
        args.physical_button_mode_default,
        physical_button_modes,
        targets,
    )
    panel.run()


if __name__ == "__main__":
    main()
