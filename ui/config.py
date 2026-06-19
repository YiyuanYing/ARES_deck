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

UI_COLOR_THEME = "burgundy"  # 可选: "burgundy" 酒红色, "midnight_blue" 墨蓝色
UI_COLOR_THEMES = {
    "burgundy": {
        "bg": "#130b10",
        "surface": "#201219",
        "surface_alt": "#321823",
        "line": "#5b2a38",
        "text": "#fff5f7",
        "muted": "#c5a1ab",
        "ok": "#ffb3c0",
        "ok_dark": "#b82f50",
        "active_glow": "#ffe1e7",
        "active_text": "#ffffff",
        "warning": "#e7b95e",
        "danger": "#ff5d73",
        "accent": "#8fb4ff",
        "panel_dark": "#170d13",
        "panel_field": "#25111a",
        "stick_bg": "#160d13",
        "warn_bg": "#352310",
        "accent_bg": "#15243a",
        "danger_bg": "#3b121d",
        "button_idle": "#2a1821",
        "button_pressed": "#263c66",
        "button_idle_outline": "#7a4654",
    },
    "midnight_blue": {
        "bg": "#07111f",
        "surface": "#0d1a2b",
        "surface_alt": "#142642",
        "line": "#29415f",
        "text": "#f2f7ff",
        "muted": "#97abc6",
        "ok": "#b8dcff",
        "ok_dark": "#2c7fe0",
        "active_glow": "#eef8ff",
        "active_text": "#ffffff",
        "warning": "#e8bf62",
        "danger": "#ff6078",
        "accent": "#78d7ff",
        "panel_dark": "#091524",
        "panel_field": "#0b1d34",
        "stick_bg": "#081421",
        "warn_bg": "#332611",
        "accent_bg": "#0b304a",
        "danger_bg": "#3a1320",
        "button_idle": "#142235",
        "button_pressed": "#17486f",
        "button_idle_outline": "#3b597a",
    },
}

# Button activation mode:
#   "toggle"    : press once -> True, press again -> False
#   "momentary" : True only while the button is being held
DEFAULT_BUTTON_ACTIVATION_MODE = "toggle"
BUTTON_ACTIVATION_MODES = ("toggle", "momentary")

JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80
JS_EVENT_SIZE = 8

# Virtual touchscreen buttons. Edit each button's "mode" field to change behavior.
VIRTUAL_BUTTON_MAP = {
    32: {"name": "Button1", "label": "BTN 1", "mode": DEFAULT_BUTTON_ACTIVATION_MODE, "x": 164, "y": 178, "w": 226, "h": 202, "radius": 8},  # 虚拟急停键 BTN 1
    33: {"name": "Button2", "label": "BTN 2", "mode": DEFAULT_BUTTON_ACTIVATION_MODE, "x": 408, "y": 178, "w": 226, "h": 202, "radius": 8},  # 虚拟使能键 BTN 2
    34: {"name": "Button3", "label": "BTN 3", "mode": DEFAULT_BUTTON_ACTIVATION_MODE, "x": 646, "y": 178, "w": 226, "h": 202, "radius": 8},  # 虚拟低速键 BTN 3
    35: {"name": "Button4", "label": "BTN 4", "mode": DEFAULT_BUTTON_ACTIVATION_MODE, "x": 890, "y": 178, "w": 226, "h": 202, "radius": 8},  # 虚拟高速键 BTN 4
    36: {"name": "Button5", "label": "BTN 5", "mode": DEFAULT_BUTTON_ACTIVATION_MODE, "x": 164, "y": 404, "w": 226, "h": 202, "radius": 8},  # 虚拟自动模式键 BTN 5
    37: {"name": "Button6", "label": "BTN 6", "mode": DEFAULT_BUTTON_ACTIVATION_MODE, "x": 408, "y": 404, "w": 226, "h": 202, "radius": 8},  # 虚拟复位键 BTN 6
    38: {"name": "Button7", "label": "BTN 7", "mode": DEFAULT_BUTTON_ACTIVATION_MODE, "x": 646, "y": 404, "w": 226, "h": 202, "radius": 8},  # 虚拟辅助键 1 BTN 7
    39: {"name": "Button8", "label": "BTN 8", "mode": DEFAULT_BUTTON_ACTIVATION_MODE, "x": 890, "y": 404, "w": 226, "h": 202, "radius": 8},  # 虚拟辅助键 2 BTN 8
}

VIRTUAL_BUTTON_IDS = tuple(VIRTUAL_BUTTON_MAP)

FOOTER_TOUCH_BUTTONS = {
    "clear_estop": {
        "label": "CLEAR ESTOP",
        "x": 164,
        "y": 712,
        "w": 230,
        "h": 54,
    },
    "exit_fullscreen": {
        "x": 525,
        "y": 712,
        "w": 230,
        "h": 54,
    },
    "exit_app": {
        "label": "EXIT APP",
        "x": 886,
        "y": 712,
        "w": 230,
        "h": 54,
    },
}


# Axis IDs sent by Linux joystick events.
AXIS_MAP = {
    0: {"name": "Left Stick X", "stick": "left", "component": "x"},
    1: {"name": "Left Stick Y", "stick": "left", "component": "y"},
    2: {"name": "Right Stick X", "stick": "right", "component": "x"},
    3: {"name": "Right Stick Y", "stick": "right", "component": "y"},
}

# Physical button display geometry.
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

# Physical button activation modes.
# Change individual entries to "momentary" when you want press-and-hold behavior.
# Entries here are merged into outgoing UDP button states by ControllerPanel.
PHYSICAL_BUTTON_MODE_MAP = {
    2: DEFAULT_BUTTON_ACTIVATION_MODE,  # 快捷菜单键 / ...
    3: DEFAULT_BUTTON_ACTIVATION_MODE,  # A 键
    4: DEFAULT_BUTTON_ACTIVATION_MODE,  # B 键
    5: DEFAULT_BUTTON_ACTIVATION_MODE,  # X 键
    6: DEFAULT_BUTTON_ACTIVATION_MODE,  # Y 键
    7: DEFAULT_BUTTON_ACTIVATION_MODE,  # 左肩键 LB
    8: DEFAULT_BUTTON_ACTIVATION_MODE,  # 右肩键 RB
    9: DEFAULT_BUTTON_ACTIVATION_MODE,  # 左扳机全按 LT
    10: DEFAULT_BUTTON_ACTIVATION_MODE,  # 右扳机全按 RT
    11: DEFAULT_BUTTON_ACTIVATION_MODE,  # View / Select 键
    12: DEFAULT_BUTTON_ACTIVATION_MODE,  # Menu / Start 键
    13: DEFAULT_BUTTON_ACTIVATION_MODE,  # Steam 键
    14: DEFAULT_BUTTON_ACTIVATION_MODE,  # 左摇杆按下 L3
    15: DEFAULT_BUTTON_ACTIVATION_MODE,  # 右摇杆按下 R3
    16: DEFAULT_BUTTON_ACTIVATION_MODE,  # 十字键上
    17: DEFAULT_BUTTON_ACTIVATION_MODE,  # 十字键下
    18: DEFAULT_BUTTON_ACTIVATION_MODE,  # 十字键左
    19: DEFAULT_BUTTON_ACTIVATION_MODE,  # 十字键右
    20: DEFAULT_BUTTON_ACTIVATION_MODE,  # 背键 L4
    21: DEFAULT_BUTTON_ACTIVATION_MODE,  # 背键 R4
    22: DEFAULT_BUTTON_ACTIVATION_MODE,  # 背键 L5
    23: DEFAULT_BUTTON_ACTIVATION_MODE,  # 背键 R5
}

OUTPUT_PHYSICAL_BUTTON_IDS = tuple(range(2, 24))
