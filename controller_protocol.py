#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ControllerFrame V2 binary protocol.

The protocol layer is transport-agnostic: UDP, serial radio, H100 data link, or
ROS2 code can reuse build_controller_frame() and parse_controller_frame().
"""

from __future__ import annotations

import binascii
import struct
import time
from typing import Dict, Tuple


MAGIC = 0xA55A
VERSION = 2
MSG_TYPE_CONTROL = 1
FRAME_LENGTH = 48
FRAME_FMT_WITHOUT_CRC = "<HBBHHHHIQQ4h4s"
FRAME_FMT = "<HBBHHHHIQQ4h4sI"
FRAME_LENGTH_WITHOUT_CRC = 44

FLAG_ENABLE = 1 << 0
FLAG_ESTOP = 1 << 1
FLAG_FULL_STATE = 1 << 2
FLAG_HEARTBEAT = 1 << 3
FLAG_MANUAL_MODE = 1 << 4
FLAG_AUTO_MODE = 1 << 5

DEFAULT_FLAGS = FLAG_FULL_STATE | FLAG_HEARTBEAT | FLAG_MANUAL_MODE
DEFAULT_FAILSAFE_TIMEOUT_MS = 150

BUTTON_NAMES = {
    0: "LEFT_TRACKPAD",
    1: "RIGHT_TRACKPAD",
    2: "QUICK_ACCESS",
    3: "A",
    4: "B",
    5: "X",
    6: "Y",
    7: "LB",
    8: "RB",
    9: "LT_FULL",
    10: "RT_FULL",
    11: "VIEW",
    12: "MENU",
    13: "STEAM",
    14: "L3",
    15: "R3",
    16: "DPAD_UP",
    17: "DPAD_DOWN",
    18: "DPAD_LEFT",
    19: "DPAD_RIGHT",
    20: "L4",
    21: "R4",
    22: "L5",
    23: "R5",
    32: "VIRTUAL_ESTOP",
    33: "VIRTUAL_ENABLE",
    34: "VIRTUAL_LOW_SPEED",
    35: "VIRTUAL_HIGH_SPEED",
    36: "VIRTUAL_AUTO_MODE",
    37: "VIRTUAL_RESET",
}
BUTTON_IDS = {name: button_id for button_id, name in BUTTON_NAMES.items()}

AXIS_KEYS = ("lx", "ly", "rx", "ry")


class ControllerFrameError(ValueError):
    """Raised when a ControllerFrame V2 packet fails validation."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def encode_axis(axis_float) -> int:
    axis_int = round(float(axis_float) * 1000.0)
    return int(clamp(axis_int, -1000, 1000))


def decode_axis(axis_int) -> float:
    return int(axis_int) / 1000.0


def set_button_bit(buttons_low: int, buttons_high: int, button_id: int, pressed: bool) -> Tuple[int, int]:
    button_id = int(button_id)
    if button_id < 0 or button_id > 127:
        raise ValueError(f"button_id out of range: {button_id}")

    if button_id < 64:
        bit = 1 << button_id
        buttons_low = buttons_low | bit if pressed else buttons_low & ~bit
    else:
        bit = 1 << (button_id - 64)
        buttons_high = buttons_high | bit if pressed else buttons_high & ~bit
    return buttons_low, buttons_high


def get_button_bit(buttons_low: int, buttons_high: int, button_id: int) -> bool:
    button_id = int(button_id)
    if button_id < 0 or button_id > 127:
        raise ValueError(f"button_id out of range: {button_id}")
    if button_id < 64:
        return bool(buttons_low & (1 << button_id))
    return bool(buttons_high & (1 << (button_id - 64)))


def _button_key_to_id(key) -> int:
    if isinstance(key, int):
        return key
    if isinstance(key, str):
        if key.isdigit():
            return int(key)
        if key in BUTTON_IDS:
            return BUTTON_IDS[key]
    raise KeyError(f"unknown button key: {key!r}")


def buttons_dict_to_bitmask(buttons: dict) -> Tuple[int, int]:
    buttons_low = 0
    buttons_high = 0
    for key, pressed in buttons.items():
        button_id = _button_key_to_id(key)
        buttons_low, buttons_high = set_button_bit(buttons_low, buttons_high, button_id, bool(pressed))
    return buttons_low, buttons_high


def bitmask_to_buttons_dict(buttons_low: int, buttons_high: int) -> dict:
    return {
        name: get_button_bit(buttons_low, buttons_high, button_id)
        for button_id, name in BUTTON_NAMES.items()
    }


def _flags_to_dict(flags: int) -> dict:
    return {
        "enable": bool(flags & FLAG_ENABLE),
        "estop": bool(flags & FLAG_ESTOP),
        "full_state": bool(flags & FLAG_FULL_STATE),
        "heartbeat": bool(flags & FLAG_HEARTBEAT),
        "manual_mode": bool(flags & FLAG_MANUAL_MODE),
        "auto_mode": bool(flags & FLAG_AUTO_MODE),
    }


def _dict_to_axes_ints(axes: dict) -> Tuple[int, int, int, int]:
    return tuple(encode_axis(axes.get(key, 0.0)) for key in AXIS_KEYS)  # type: ignore[return-value]


def build_controller_frame(
    seq,
    axes,
    buttons,
    enable=True,
    estop=False,
    failsafe_timeout_ms=DEFAULT_FAILSAFE_TIMEOUT_MS,
) -> bytes:
    buttons_low, buttons_high = buttons_dict_to_bitmask(buttons)
    axis_lx, axis_ly, axis_rx, axis_ry = _dict_to_axes_ints(axes)
    timestamp_ms = int(time.monotonic() * 1000.0) & 0xFFFFFFFF
    seq = int(seq) & 0xFFFF
    failsafe_timeout_ms = int(clamp(int(failsafe_timeout_ms), 0, 0xFFFF))

    inferred_estop = (
        bool(estop)
        or get_button_bit(buttons_low, buttons_high, BUTTON_IDS["STEAM"])
        or get_button_bit(buttons_low, buttons_high, BUTTON_IDS["VIRTUAL_ESTOP"])
    )
    inferred_enable = (
        bool(enable)
        or get_button_bit(buttons_low, buttons_high, BUTTON_IDS["VIRTUAL_ENABLE"])
    )

    flags = DEFAULT_FLAGS
    if inferred_enable:
        flags |= FLAG_ENABLE
    if inferred_estop:
        flags |= FLAG_ESTOP
    if get_button_bit(buttons_low, buttons_high, BUTTON_IDS["VIRTUAL_AUTO_MODE"]):
        flags = (flags & ~FLAG_MANUAL_MODE) | FLAG_AUTO_MODE

    frame_without_crc = struct.pack(
        FRAME_FMT_WITHOUT_CRC,
        MAGIC,
        VERSION,
        MSG_TYPE_CONTROL,
        FRAME_LENGTH,
        flags,
        seq,
        failsafe_timeout_ms,
        timestamp_ms,
        buttons_low,
        buttons_high,
        axis_lx,
        axis_ly,
        axis_rx,
        axis_ry,
        b"\x00\x00\x00\x00",
    )
    crc32 = binascii.crc32(frame_without_crc) & 0xFFFFFFFF
    frame = frame_without_crc + struct.pack("<I", crc32)
    if len(frame) != FRAME_LENGTH:
        raise AssertionError(f"ControllerFrame V2 length is {len(frame)}, expected {FRAME_LENGTH}")
    return frame


def parse_controller_frame(data: bytes) -> dict:
    if len(data) != FRAME_LENGTH:
        raise ControllerFrameError("bad_length", f"bad frame length {len(data)}, expected {FRAME_LENGTH}")

    header = struct.unpack_from("<HBBH", data, 0)
    magic, version, msg_type, length = header
    if magic != MAGIC:
        raise ControllerFrameError("bad_magic", f"bad magic 0x{magic:04X}")
    if version != VERSION:
        raise ControllerFrameError("bad_version", f"bad version {version}")
    if msg_type != MSG_TYPE_CONTROL:
        raise ControllerFrameError("bad_msg_type", f"bad msg_type {msg_type}")
    if length != FRAME_LENGTH:
        raise ControllerFrameError("bad_length_field", f"bad length field {length}")

    expected_crc = binascii.crc32(data[:FRAME_LENGTH_WITHOUT_CRC]) & 0xFFFFFFFF
    actual_crc = struct.unpack_from("<I", data, FRAME_LENGTH_WITHOUT_CRC)[0]
    if actual_crc != expected_crc:
        raise ControllerFrameError("bad_crc", f"bad crc32 0x{actual_crc:08X}, expected 0x{expected_crc:08X}")

    (
        _magic,
        _version,
        _msg_type,
        _length,
        flags,
        seq,
        failsafe_timeout_ms,
        timestamp_ms,
        buttons_low,
        buttons_high,
        axis_lx,
        axis_ly,
        axis_rx,
        axis_ry,
        reserved,
        crc32,
    ) = struct.unpack(FRAME_FMT, data)

    return {
        "magic": _magic,
        "version": _version,
        "msg_type": _msg_type,
        "length": _length,
        "seq": seq,
        "timestamp_ms": timestamp_ms,
        "failsafe_timeout_ms": failsafe_timeout_ms,
        "flags_raw": flags,
        "flags": _flags_to_dict(flags),
        "axes": {
            "lx": decode_axis(axis_lx),
            "ly": decode_axis(axis_ly),
            "rx": decode_axis(axis_rx),
            "ry": decode_axis(axis_ry),
        },
        "buttons": bitmask_to_buttons_dict(buttons_low, buttons_high),
        "raw": {
            "buttons_low": buttons_low,
            "buttons_high": buttons_high,
            "axis_lx": axis_lx,
            "axis_ly": axis_ly,
            "axis_rx": axis_rx,
            "axis_ry": axis_ry,
            "reserved": reserved,
            "crc32": crc32,
        },
    }


def _self_test() -> None:
    assert struct.calcsize(FRAME_FMT_WITHOUT_CRC) == FRAME_LENGTH_WITHOUT_CRC
    assert struct.calcsize(FRAME_FMT) == FRAME_LENGTH

    axes = {"lx": 0.123, "ly": -0.35, "rx": 0.0, "ry": 1.25}
    buttons = {"A": True, "B": False, "RB": True, "STEAM": False, "VIRTUAL_ENABLE": True}
    frame = build_controller_frame(65535, axes, buttons, enable=False)
    parsed = parse_controller_frame(frame)
    assert len(frame) == FRAME_LENGTH
    assert parsed["seq"] == 65535
    assert parsed["axes"]["lx"] == 0.123
    assert parsed["axes"]["ly"] == -0.35
    assert parsed["axes"]["ry"] == 1.0
    assert parsed["buttons"]["A"] is True
    assert parsed["buttons"]["RB"] is True
    assert parsed["buttons"]["B"] is False
    assert parsed["flags"]["enable"] is True
    assert parsed["flags"]["estop"] is False

    bad = bytearray(frame)
    bad[20] ^= 0x01
    try:
        parse_controller_frame(bytes(bad))
    except ControllerFrameError as exc:
        assert exc.reason == "bad_crc"
    else:
        raise AssertionError("CRC self-test did not fail on corrupted frame")

    print("ControllerFrame V2 self-test passed")


if __name__ == "__main__":
    _self_test()
