#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import ast
import json
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.params import get_section
from core.protocol import AXIS_KEYS, BUTTON_IDS, BUTTON_NAMES
from core.udp_receiver import BIND_IP, CONTROL_HZ, PORT, ControllerUdpReceiver


DEFAULT_CONTROLLER_TOPIC = "/controller"
DEFAULT_TX_ID_TOPIC = "/aruco_comm/tx_id"
DEFAULT_DEBUG_LOG = True
DEFAULT_DEBUG_LOG_HZ = 1.0
DEFAULT_DEBUG_LOG_FORMAT = "block"
DEFAULT_DEBUG_LOG_COLOR = True
DEFAULT_TX_ID_ZERO_FRAMES = 3
DEFAULT_TX_ID_VALUE_FRAMES = 1
ANSI_RESET = "\033[0m"
ANSI_DIM = "\033[2m"
ANSI_GREEN = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_RED = "\033[91m"
ANSI_CYAN = "\033[96m"
RESERVED_BUTTON_NAMES = frozenset(
    {
        "QUICK_ACCESS",
        "STEAM",
        "MENU",
    }
)
JOY_BUTTON_COUNT = max(BUTTON_NAMES) + 1


def parse_button_to_tx_id(value: Any) -> Dict[str, int]:
    if value in (None, "", {}):
        return {}
    if isinstance(value, dict):
        raw_mapping = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            raw_mapping = json.loads(text)
        except json.JSONDecodeError:
            raw_mapping = ast.literal_eval(text)
    else:
        raise ValueError(f"button_to_tx_id must be a dict or JSON string, got {type(value).__name__}")

    if not isinstance(raw_mapping, dict):
        raise ValueError("button_to_tx_id must decode to a dict")

    mapping: Dict[str, int] = {}
    for key, tx_id in raw_mapping.items():
        button_name = normalize_button_name(key)
        mapping[button_name] = int(tx_id)
    return mapping


def normalize_button_name(value: Any) -> str:
    if isinstance(value, int):
        if value not in BUTTON_NAMES:
            raise ValueError(f"unknown button id: {value}")
        return BUTTON_NAMES[value]

    text = str(value).strip()
    if text.isdigit():
        button_id = int(text)
        if button_id not in BUTTON_NAMES:
            raise ValueError(f"unknown button id: {button_id}")
        return BUTTON_NAMES[button_id]

    name = text.upper()
    if name not in BUTTON_IDS:
        raise ValueError(f"unknown button name: {value!r}")
    return name


def filter_reserved_tx_id_mapping(mapping: Dict[str, int], logger: Any | None = None) -> Dict[str, int]:
    filtered: Dict[str, int] = {}
    for button_name, tx_id in mapping.items():
        if button_name in RESERVED_BUTTON_NAMES:
            message = f"button_to_tx_id ignores reserved button {button_name}={BUTTON_IDS[button_name]}"
            if logger is not None:
                logger.warning(message)
            else:
                print(f"[ros] warning: {message}")
            continue
        filtered[button_name] = int(tx_id)
    return filtered


def joy_axes_from_state(state: dict) -> list[float]:
    axes = state.get("axes", {})
    return [float(axes.get(axis_key, 0.0)) for axis_key in AXIS_KEYS]


def joy_buttons_from_state(state: dict) -> list[int]:
    buttons = [0] * JOY_BUTTON_COUNT
    state_buttons = state.get("buttons", {})
    for button_id, button_name in BUTTON_NAMES.items():
        buttons[button_id] = 1 if bool(state_buttons.get(button_name, False)) else 0
    return buttons


def rising_tx_ids(state: dict, previous_buttons: Dict[str, bool], mapping: Dict[str, int]) -> list[int]:
    state_buttons = state.get("buttons", {})
    tx_ids: list[int] = []
    for button_name, tx_id in mapping.items():
        current = bool(state_buttons.get(button_name, False))
        previous = bool(previous_buttons.get(button_name, False))
        if current and not previous:
            tx_ids.append(int(tx_id))
    return tx_ids


def build_tx_id_sequence(tx_id: int, zero_frames: int = DEFAULT_TX_ID_ZERO_FRAMES, value_frames: int = DEFAULT_TX_ID_VALUE_FRAMES) -> list[int]:
    return [0] * max(int(zero_frames), 0) + [int(tx_id)] * max(int(value_frames), 0)


def snapshot_buttons(state: dict, button_names: Iterable[str] | None = None) -> Dict[str, bool]:
    state_buttons = state.get("buttons", {})
    names = button_names if button_names is not None else BUTTON_NAMES.values()
    return {button_name: bool(state_buttons.get(button_name, False)) for button_name in names}


def format_pressed_buttons(state: dict) -> str:
    pressed = [name for name, active in state.get("buttons", {}).items() if active]
    return ",".join(pressed) if pressed else "-"


def format_axes(state: dict) -> str:
    axes = state.get("axes", {})
    return (
        f"lx={float(axes.get('lx', 0.0)):+.2f} "
        f"ly={float(axes.get('ly', 0.0)):+.2f} "
        f"rx={float(axes.get('rx', 0.0)):+.2f} "
        f"ry={float(axes.get('ry', 0.0)):+.2f}"
    )


def color_text(text: str, color: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{color}{text}{ANSI_RESET}"


def host_status(state: dict) -> tuple[str, str]:
    if state.get("remote_timeout", False):
        return "LOST", ANSI_RED
    if state.get("warning", False):
        return "WARN", ANSI_YELLOW
    if state.get("online", False):
        return "OK", ANSI_GREEN
    return "WAITING", ANSI_DIM


def format_debug_block(
    state: dict,
    controller_topic: str,
    tx_id_topic: str,
    publish_rate: float,
    mapped_buttons: Dict[str, int],
    tx_id_queue_len: int = 0,
    color: bool = False,
) -> str:
    flags = state.get("flags", {})
    tx_mapping = ",".join(f"{button}->{tx_id}" for button, tx_id in mapped_buttons.items()) if mapped_buttons else "-"
    host, host_color = host_status(state)
    estop = bool(flags.get("estop", False))
    timeout = bool(state.get("remote_timeout", False))
    enable = bool(flags.get("enable", False))
    safe_text = f"estop={estop} timeout={timeout} enable={enable}"
    safe_color = ANSI_RED if estop or timeout else ANSI_GREEN
    return "\n".join(
        [
            color_text("ROS UDP receiver", ANSI_CYAN, color),
            (
                f"  HOST   {color_text(host, host_color, color):<18} "
                f"udp_rx={float(state.get('rx_rate', 0.0)):.0f}/s "
                f"seq={state.get('seq')} age={float(state.get('age_ms', 0.0)):.0f}ms"
            ),
            f"  SAFE   {color_text(safe_text, safe_color, color)}",
            (
                f"  JOY    pub={publish_rate:.0f}/s "
                f"lost={state.get('lost', 0)} jitter={float(state.get('jitter_ms', 0.0)):.1f}ms"
            ),
            f"  AXES   {format_axes(state)}",
            f"  BTN    {format_pressed_buttons(state)}",
            f"  TOPIC  joy={controller_topic} tx_id={tx_id_topic}",
            f"  TXID   map={tx_mapping} queue={tx_id_queue_len}",
        ]
    )


def format_debug_line(state: dict, controller_topic: str, publish_rate: float, color: bool = False) -> str:
    flags = state.get("flags", {})
    host, host_color = host_status(state)
    return (
        f"{controller_topic} pub={publish_rate:.0f}/s "
        f"host={color_text(host, host_color, color)} "
        f"udp_rx={float(state.get('rx_rate', 0.0)):.0f}/s "
        f"online={bool(state.get('online', False))} "
        f"timeout={bool(state.get('remote_timeout', False))} "
        f"estop={bool(flags.get('estop', False))} "
        f"seq={state.get('seq')} age={float(state.get('age_ms', 0.0)):.0f}ms "
        f"{format_axes(state)} buttons={format_pressed_buttons(state)}"
    )


def parse_args() -> argparse.Namespace:
    params = get_section("ros_udp_receiver")
    parser = argparse.ArgumentParser(description="ROS2 ControllerFrame V2 UDP receiver publisher.")
    parser.add_argument("--bind-ip", default=params.get("bind_ip", BIND_IP))
    parser.add_argument("--port", type=int, default=params.get("port", PORT))
    parser.add_argument("--publish-hz", type=float, default=params.get("publish_hz", CONTROL_HZ))
    parser.add_argument("--controller-topic", default=params.get("controller_topic", DEFAULT_CONTROLLER_TOPIC))
    parser.add_argument("--tx-id-topic", default=params.get("tx_id_topic", DEFAULT_TX_ID_TOPIC))
    parser.add_argument("--tx-id-zero-frames", type=int, default=params.get("tx_id_zero_frames", DEFAULT_TX_ID_ZERO_FRAMES))
    parser.add_argument("--tx-id-value-frames", type=int, default=params.get("tx_id_value_frames", DEFAULT_TX_ID_VALUE_FRAMES))
    parser.add_argument(
        "--debug-log",
        action=argparse.BooleanOptionalAction,
        default=params.get("debug_log", DEFAULT_DEBUG_LOG),
        help="Print periodic receiver/publisher status logs.",
    )
    parser.add_argument("--debug-log-hz", type=float, default=params.get("debug_log_hz", DEFAULT_DEBUG_LOG_HZ))
    parser.add_argument(
        "--debug-log-format",
        choices=("block", "line"),
        default=params.get("debug_log_format", DEFAULT_DEBUG_LOG_FORMAT),
    )
    parser.add_argument(
        "--debug-log-color",
        action=argparse.BooleanOptionalAction,
        default=params.get("debug_log_color", DEFAULT_DEBUG_LOG_COLOR),
        help="Colorize debug logs with ANSI escape codes.",
    )
    parser.add_argument(
        "--button-to-tx-id",
        default=params.get("button_to_tx_id", "{}"),
        help='JSON dict mapping button names/ids to Int32 values, e.g. \'{"A": 1, "RB": 2}\'.',
    )
    return parser.parse_args()


class ControllerRosPublisher:
    def __init__(self, args: argparse.Namespace) -> None:
        import rclpy
        from rclpy.node import Node
        from sensor_msgs.msg import Joy
        from std_msgs.msg import Int32

        class _Node(Node):
            pass

        self.rclpy = rclpy
        self.Joy = Joy
        self.Int32 = Int32
        self.node = _Node("controller_udp_receiver")
        raw_mapping = parse_button_to_tx_id(args.button_to_tx_id)
        self.button_to_tx_id = filter_reserved_tx_id_mapping(raw_mapping, self.node.get_logger())
        self.receiver = ControllerUdpReceiver(bind_ip=args.bind_ip, port=args.port)
        self.controller_pub = self.node.create_publisher(Joy, args.controller_topic, 10)
        self.tx_id_pub = self.node.create_publisher(Int32, args.tx_id_topic, 10)
        self.previous_buttons: Dict[str, bool] = {}
        self.tx_id_queue: Deque[int] = deque()
        self.tx_id_zero_frames = max(int(args.tx_id_zero_frames), 0)
        self.tx_id_value_frames = max(int(args.tx_id_value_frames), 0)
        self.period = 1.0 / max(float(args.publish_hz), 1.0)
        self.debug_log = bool(args.debug_log)
        self.debug_log_interval = 1.0 / max(float(args.debug_log_hz), 0.01)
        self.debug_log_format = str(args.debug_log_format)
        self.debug_log_color = bool(args.debug_log_color)
        self.next_debug_log_at = 0.0
        self.publish_count = 0
        self.publish_window_start = time.monotonic()
        self.publish_rate = 0.0
        self.controller_topic = str(args.controller_topic)
        self.tx_id_topic = str(args.tx_id_topic)
        self.timer = self.node.create_timer(self.period, self.publish_once)

        self.node.get_logger().info(
            f"publishing Joy {args.controller_topic} at {1.0 / self.period:.1f}Hz, "
            f"tx_id topic {args.tx_id_topic}, mapped buttons={self.button_to_tx_id}, "
            f"tx_id sequence zero_frames={self.tx_id_zero_frames} value_frames={self.tx_id_value_frames}, "
            f"debug_log={self.debug_log} format={self.debug_log_format} color={self.debug_log_color}"
        )

    def start(self) -> None:
        self.receiver.start()

    def stop(self) -> None:
        self.receiver.stop()
        self.node.destroy_node()

    def publish_once(self) -> None:
        state = self.receiver.update_state()
        joy = self.Joy()
        joy.header.stamp = self.node.get_clock().now().to_msg()
        joy.header.frame_id = "controller"
        joy.axes = joy_axes_from_state(state)
        joy.buttons = joy_buttons_from_state(state)
        self.controller_pub.publish(joy)
        self.note_joy_published()

        for tx_id in rising_tx_ids(state, self.previous_buttons, self.button_to_tx_id):
            self.enqueue_tx_id(tx_id)
        self.previous_buttons = snapshot_buttons(state, self.button_to_tx_id.keys())
        self.publish_next_tx_id()
        self.log_debug_state(state)

    def enqueue_tx_id(self, tx_id: int) -> None:
        sequence = build_tx_id_sequence(tx_id, self.tx_id_zero_frames, self.tx_id_value_frames)
        self.tx_id_queue.extend(sequence)
        self.node.get_logger().info(f"queued {self.tx_id_topic}: {sequence} queue={len(self.tx_id_queue)}")

    def publish_next_tx_id(self) -> None:
        if not self.tx_id_queue:
            return
        tx_id = self.tx_id_queue.popleft()
        message = self.Int32()
        message.data = int(tx_id)
        self.tx_id_pub.publish(message)
        self.node.get_logger().info(f"published {self.tx_id_topic}: {tx_id} queue={len(self.tx_id_queue)}")

    def note_joy_published(self) -> None:
        now = time.monotonic()
        self.publish_count += 1
        elapsed = now - self.publish_window_start
        if elapsed >= 1.0:
            self.publish_rate = self.publish_count / elapsed
            self.publish_count = 0
            self.publish_window_start = now

    def log_debug_state(self, state: dict) -> None:
        if not self.debug_log:
            return
        now = time.monotonic()
        if now < self.next_debug_log_at:
            return
        self.next_debug_log_at = now + self.debug_log_interval

        if self.debug_log_format == "line":
            message = format_debug_line(state, self.controller_topic, self.publish_rate, self.debug_log_color)
        else:
            message = format_debug_block(
                state,
                self.controller_topic,
                self.tx_id_topic,
                self.publish_rate,
                self.button_to_tx_id,
                len(self.tx_id_queue),
                self.debug_log_color,
            )
        self.node.get_logger().info(message)


def main() -> None:
    args = parse_args()
    try:
        import rclpy
    except ImportError as exc:
        raise SystemExit("ROS2 rclpy is required. Source your ROS2 environment before running this node.") from exc

    rclpy.init(args=None)
    publisher = ControllerRosPublisher(args)
    publisher.start()
    try:
        rclpy.spin(publisher.node)
    except KeyboardInterrupt:
        publisher.node.get_logger().info("stopped")
    finally:
        publisher.stop()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
