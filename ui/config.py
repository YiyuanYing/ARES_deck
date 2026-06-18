#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.udp_sender import FAILSAFE_TIMEOUT_MS, LOCAL_IP, SEND_HZ, TARGET_IP, TARGET_PORT

DEVICE_PATH = "/dev/input/js0"
TOUCH_DEVICE_PATH = ""
TOUCH_SWAP_XY = False
TOUCH_INVERT_X = False
TOUCH_INVERT_Y = False
DEADZONE = 0.20
BASE_WIDTH = 1280
BASE_HEIGHT = 800
REFRESH_MS = 20  # 50Hz GUI/UDP update loop
CALIBRATION_SECONDS = 1.0

DEFAULT_LOCAL_IP = LOCAL_IP
DEFAULT_REMOTE_IP = TARGET_IP
DEFAULT_UDP_PORT = TARGET_PORT
UDP_SEND_HZ = SEND_HZ
RESET_PULSE_SECONDS = 0.25

JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80
JS_EVENT_SIZE = 8

VIRTUAL_BUTTON_MAP = {
    32: {"name": "Button1", "label": "Button1", "x": 153, "y": 150, "w": 237, "h": 260, "radius": 18},
    33: {"name": "Button2", "label": "Button2", "x": 398, "y": 150, "w": 237, "h": 260, "radius": 18},
    34: {"name": "Button3", "label": "Button3", "x": 643, "y": 150, "w": 237, "h": 260, "radius": 18},
    35: {"name": "Button4", "label": "Button4", "x": 888, "y": 150, "w": 237, "h": 260, "radius": 18},
    36: {"name": "Button5", "label": "Button5", "x": 153, "y": 418, "w": 237, "h": 260, "radius": 18},
    37: {"name": "Button6", "label": "Button6", "x": 398, "y": 418, "w": 237, "h": 260, "radius": 18},
    38: {"name": "Button7", "label": "Button7", "x": 643, "y": 418, "w": 237, "h": 260, "radius": 18},
    39: {"name": "Button8", "label": "Button8", "x": 888, "y": 418, "w": 237, "h": 260, "radius": 18},
}

VIRTUAL_BUTTON_IDS = tuple(VIRTUAL_BUTTON_MAP)

FOOTER_TOUCH_BUTTONS = {
    "clear_estop": {
        "label": "CLEAR ESTOP",
        "x": 250,
        "y": 724,
        "w": 230,
        "h": 54,
    },
    "exit_fullscreen": {
        "x": 525,
        "y": 724,
        "w": 230,
        "h": 54,
    },
    "exit_app": {
        "label": "EXIT APP",
        "x": 800,
        "y": 724,
        "w": 230,
        "h": 54,
    },
}


# =========================
# Steam Deck 当前 /dev/input/js0 映射
# 坐标基于 1280x800 设计，绘制时会按窗口尺寸缩放。
# =========================

AXIS_MAP = {
    0: {"name": "Left Stick X", "stick": "left", "component": "x"},
    1: {"name": "Left Stick Y", "stick": "left", "component": "y"},
    2: {"name": "Right Stick X", "stick": "right", "component": "x"},
    3: {"name": "Right Stick Y", "stick": "right", "component": "y"},
}

DISPLAY_BUTTON_MAP = {
    2: {
        "name": "Quick Access / ...",
        "label": "...",
        "shape": "rounded_rect",
        "x": 1208,
        "y": 625,
        "w": 46,
        "h": 48,
        "radius": 12,
    },
    3: {"name": "A", "label": "A", "shape": "circle", "x": 1210, "y": 495, "r": 20},
    4: {"name": "B", "label": "B", "shape": "circle", "x": 1245, "y": 460, "r": 20},
    5: {"name": "X", "label": "X", "shape": "circle", "x": 1175, "y": 460, "r": 20},
    6: {"name": "Y", "label": "Y", "shape": "circle", "x": 1210, "y": 425, "r": 20},
    7: {
        "name": "LB",
        "label": "LB",
        "shape": "rounded_rect",
        "x": 28,
        "y": 112,
        "w": 91,
        "h": 42,
        "radius": 12,
    },
    8: {
        "name": "RB",
        "label": "RB",
        "shape": "rounded_rect",
        "x": 1161,
        "y": 112,
        "w": 91,
        "h": 42,
        "radius": 12,
    },
    9: {
        "name": "LT Full Press",
        "label": "LT",
        "shape": "rounded_rect",
        "x": 28,
        "y": 62,
        "w": 91,
        "h": 42,
        "radius": 12,
    },
    10: {
        "name": "RT Full Press",
        "label": "RT",
        "shape": "rounded_rect",
        "x": 1161,
        "y": 62,
        "w": 91,
        "h": 42,
        "radius": 12,
    },
    11: {
        "name": "View / Select",
        "label": "VIEW",
        "shape": "rounded_rect",
        "x": 78,
        "y": 625,
        "w": 46,
        "h": 48,
        "radius": 12,
    },
    12: {
        "name": "Menu / Start",
        "label": "MENU",
        "shape": "rounded_rect",
        "x": 1161,
        "y": 625,
        "w": 46,
        "h": 48,
        "radius": 12,
    },
    13: {
        "name": "Steam",
        "label": "STEAM",
        "shape": "rounded_rect",
        "x": 28,
        "y": 625,
        "w": 41,
        "h": 48,
        "radius": 12,
    },
    16: {"name": "D-pad Up", "label": "UP", "shape": "rounded_rect", "x": 58, "y": 420, "w": 28, "h": 34, "radius": 8},
    17: {"name": "D-pad Down", "label": "DOWN", "shape": "rounded_rect", "x": 58, "y": 496, "w": 28, "h": 34, "radius": 8},
    18: {"name": "D-pad Left", "label": "LEFT", "shape": "rounded_rect", "x": 18, "y": 458, "w": 28, "h": 34, "radius": 8},
    19: {"name": "D-pad Right", "label": "RIGHT", "shape": "rounded_rect", "x": 98, "y": 458, "w": 28, "h": 34, "radius": 8},
    20: {
        "name": "L4",
        "label": "L4",
        "shape": "rounded_rect",
        "x": 28,
        "y": 208,
        "w": 41,
        "h": 110,
        "radius": 14,
    },
    21: {
        "name": "R4",
        "label": "R4",
        "shape": "rounded_rect",
        "x": 1161,
        "y": 208,
        "w": 41,
        "h": 110,
        "radius": 14,
    },
    22: {
        "name": "L5",
        "label": "L5",
        "shape": "rounded_rect",
        "x": 78,
        "y": 208,
        "w": 41,
        "h": 110,
        "radius": 14,
    },
    23: {
        "name": "R5",
        "label": "R5",
        "shape": "rounded_rect",
        "x": 1208,
        "y": 208,
        "w": 41,
        "h": 110,
        "radius": 14,
    },
}

OUTPUT_PHYSICAL_BUTTON_IDS = tuple(range(2, 24))
