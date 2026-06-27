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
from core.protocol import BUTTON_IDS, BUTTON_NAMES
from core.udp_sender import (
    FAILSAFE_TIMEOUT_MS,
    LOCAL_IP,
    SEND_HZ,
    TARGET_IP,
    TARGET_PORT,
    ControllerUdpSender,
    normalize_udp_targets,
    parse_udp_target,
)


def parse_button(value: str) -> tuple[int, str]:
    text = str(value).strip()
    try:
        button_id = int(text, 10)
    except ValueError:
        button_id = BUTTON_IDS.get(text.upper(), -1)

    if button_id not in BUTTON_NAMES:
        raise argparse.ArgumentTypeError(f"未知按钮 {value!r}，请使用协议按钮名称或 ID 0..47")
    return button_id, BUTTON_NAMES[button_id]


def parse_args() -> argparse.Namespace:
    params = get_section("udp_sender")
    parser = argparse.ArgumentParser(description="无 GUI 的 ControllerFrame V2 实体按钮循环模拟器。")
    parser.add_argument("--local-ip", default=params.get("local_ip", LOCAL_IP))
    parser.add_argument("--target-ip", default=params.get("target_ip", TARGET_IP), help=argparse.SUPPRESS)
    parser.add_argument("--target-port", type=int, default=params.get("target_port", TARGET_PORT), help=argparse.SUPPRESS)
    parser.add_argument("--target", action="append", default=None, help="接收端 IP:PORT，可重复指定多个目标。")
    parser.add_argument("--send-hz", type=float, default=params.get("send_hz", SEND_HZ))
    parser.add_argument("--failsafe-timeout-ms", type=int, default=params.get("failsafe_timeout_ms", FAILSAFE_TIMEOUT_MS))
    parser.add_argument("--button", type=parse_button, default=parse_button("A"), help="模拟按钮名称或 ID，默认 A。")
    parser.add_argument("--press-seconds", type=float, default=0.5, help="每周期按下时长，默认 0.5 秒。")
    parser.add_argument("--period-seconds", type=float, default=1.0, help="按键循环周期，默认 1 秒。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.press_seconds <= 0:
        raise SystemExit("--press-seconds 必须大于 0")
    if args.period_seconds <= args.press_seconds:
        raise SystemExit("--period-seconds 必须大于 --press-seconds")

    params = get_section("udp_sender")
    target_entries = args.target if args.target is not None else params.get("targets")
    targets = normalize_udp_targets(
        [parse_udp_target(item, args.target_port) for item in target_entries] if args.target is not None else target_entries,
        fallback_ip=args.target_ip,
        fallback_port=args.target_port,
    )
    button_id, button_name = args.button
    started_at = time.monotonic()

    def state_provider() -> dict:
        elapsed_in_period = (time.monotonic() - started_at) % args.period_seconds
        pressed = elapsed_in_period < args.press_seconds
        return {
            "axes": {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0},
            "buttons": {button_id: pressed},
            "enable": True,
            "estop": False,
        }

    sender = ControllerUdpSender(
        state_provider=state_provider,
        local_ip=args.local_ip,
        target_ip=args.target_ip,
        target_port=args.target_port,
        targets=targets,
        send_hz=args.send_hz,
        failsafe_timeout_ms=args.failsafe_timeout_ms,
        print_status=True,
    )
    print(
        f"[sim] button={button_name}({button_id}) "
        f"pressed={args.press_seconds:.3f}s period={args.period_seconds:.3f}s"
    )
    sender.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[sim] stopped")
    finally:
        sender.stop()


if __name__ == "__main__":
    main()
