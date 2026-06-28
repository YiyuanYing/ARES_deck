#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.map_message import MAP_MESSAGE_PORT
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
DEFAULT_MAP_MESSAGE_PORT = MAP_MESSAGE_PORT
UDP_SEND_HZ = SEND_HZ
MAP_EDITOR_TRIGGER_BUTTON_ID = 13  # Steam 键：按下会打开目标地图编辑器。
ACTION_COMMAND_TRIGGER_BUTTON_ID = 2  # 快捷菜单键 / ...：按下会打开动作指令窗口。

UI_COLOR_THEME = "midnight_blue"  # 可选: "burgundy" 酒红色, "midnight_blue" 墨蓝色
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
        "host_connected": "#32ff75",
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
        "host_connected": "#32ff75",
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

# 按键触发模式：
#   "toggle"    : 点一次变 True，再点一次变 False
#   "momentary" : 按住时为 True，松开后为 False
DEFAULT_BUTTON_ACTIVATION_MODE = "momentary"
BUTTON_ACTIVATION_MODES = ("toggle", "momentary")

JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80
JS_EVENT_SIZE = 8

# SBUS_2 矩阵左侧的动作行标题。
SBUS2_ROW_LABELS = (
    {"label": "EXTEND", "x": 180, "y": 254},
    {"label": "DOWN", "x": 180, "y": 378},
    {"label": "RELAY", "x": 180, "y": 502},
)

# 屏幕虚拟按键；修改各条目的 mode 可以单独调整触发方式。
VIRTUAL_BUTTON_MAP = {
    32: {"name": "SBUS2 M3508 Left Extend", "label": "EXT L", "group": "SBUS_2", "mode": "toggle", "x": 248, "y": 202, "w": 160, "h": 104, "radius": 8},
    33: {"name": "SBUS2 M3508 Center Extend", "label": "EXT C", "group": "SBUS_2", "mode": "toggle", "x": 422, "y": 202, "w": 160, "h": 104, "radius": 8},
    34: {"name": "SBUS2 M3508 Right Extend", "label": "EXT R", "group": "SBUS_2", "mode": "toggle", "x": 596, "y": 202, "w": 160, "h": 104, "radius": 8},
    35: {"name": "SBUS2 M2006 Left Down", "label": "DOWN L", "group": "SBUS_2", "mode": "toggle", "x": 248, "y": 326, "w": 160, "h": 104, "radius": 8},
    36: {"name": "SBUS2 M2006 Right Down", "label": "DOWN R", "group": "SBUS_2", "mode": "toggle", "x": 596, "y": 326, "w": 160, "h": 104, "radius": 8},
    37: {"name": "SBUS2 Relay Left", "label": "RELAY L", "group": "SBUS_2", "mode": "toggle", "x": 248, "y": 450, "w": 160, "h": 104, "radius": 8},
    38: {"name": "SBUS2 Relay Center", "label": "RELAY C", "group": "SBUS_2", "mode": "toggle", "x": 422, "y": 450, "w": 160, "h": 104, "radius": 8},
    39: {"name": "SBUS2 Relay Right", "label": "RELAY R", "group": "SBUS_2", "mode": "toggle", "x": 596, "y": 450, "w": 160, "h": 104, "radius": 8},
    40: {"name": "R1 Catch Prepare", "label": "PREPARE", "group": "CATCH", "style": "compact", "mode": "toggle", "x": 786, "y": 350, "w": 312, "h": 58, "radius": 8},
    41: {"name": "R1 Catch Raise", "label": "RAISE", "group": "CATCH", "style": "compact", "mode": "toggle", "x": 786, "y": 424, "w": 312, "h": 58, "radius": 8},
    42: {"name": "R1 Catch Attack", "label": "ATTACK", "group": "CATCH", "style": "compact", "mode": "toggle", "x": 786, "y": 498, "w": 312, "h": 58, "radius": 8},
    46: {"name": "R1 Catch Release", "label": "RELEASE", "group": "CATCH", "style": "compact", "mode": "toggle", "x": 786, "y": 202, "w": 312, "h": 58, "radius": 8},
    47: {"name": "R1 Catch Seize", "label": "SEIZE", "group": "CATCH", "style": "compact", "mode": "toggle", "x": 786, "y": 276, "w": 312, "h": 58, "radius": 8},
}

VIRTUAL_BUTTON_IDS = tuple(VIRTUAL_BUTTON_MAP)

FOOTER_TOUCH_BUTTONS = {
    "clear_estop": {
        "label": "CLEAR ESTOP",
        "x": 176,
        "y": 722,
        "w": 204,
        "h": 48,
    },
    "exit_fullscreen": {
        "x": 538,
        "y": 722,
        "w": 204,
        "h": 48,
    },
    "exit_app": {
        "label": "EXIT APP",
        "x": 900,
        "y": 722,
        "w": 204,
        "h": 48,
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
        "x": 1200,
        "y": 625,
        "w": 44,
        "h": 48,
        "radius": 12,
    },
    3: {"name": "A", "label": "A", "hint": "LIFT DOWN", "hint_y": 532, "shape": "circle", "x": 1194, "y": 500, "r": 20},
    4: {"name": "B", "label": "B", "shape": "circle", "x": 1229, "y": 465, "r": 20},
    5: {"name": "X", "label": "X", "shape": "circle", "x": 1159, "y": 465, "r": 20},
    6: {"name": "Y", "label": "Y", "hint": "LIFT UP", "hint_y": 398, "shape": "circle", "x": 1194, "y": 430, "r": 20},
    7: {
        "name": "LB",
        "label": "LB",
        "shape": "rounded_rect",
        "x": 36,
        "y": 206,
        "w": 100,
        "h": 40,
        "radius": 12,
    },
    8: {
        "name": "RB",
        "label": "RB",
        "shape": "rounded_rect",
        "x": 1144,
        "y": 206,
        "w": 100,
        "h": 40,
        "radius": 12,
    },
    9: {
        "name": "LT Full Press",
        "label": "LT",
        "shape": "rounded_rect",
        "x": 36,
        "y": 158,
        "w": 100,
        "h": 40,
        "radius": 12,
    },
    10: {
        "name": "RT Full Press",
        "label": "RT",
        "shape": "rounded_rect",
        "x": 1144,
        "y": 158,
        "w": 100,
        "h": 40,
        "radius": 12,
    },
    11: {
        "name": "View / Select",
        "label": "VIEW",
        "shape": "rounded_rect",
        "x": 88,
        "y": 625,
        "w": 44,
        "h": 48,
        "radius": 12,
    },
    12: {
        "name": "Menu / Start",
        "label": "MENU",
        "shape": "rounded_rect",
        "x": 1148,
        "y": 625,
        "w": 44,
        "h": 48,
        "radius": 12,
    },
    13: {
        "name": "Steam",
        "label": "STEAM",
        "shape": "rounded_rect",
        "x": 36,
        "y": 625,
        "w": 44,
        "h": 48,
        "radius": 12,
    },
    16: {"name": "D-pad Up", "label": "↑", "shape": "circle", "x": 86, "y": 430, "r": 20},
    17: {"name": "D-pad Down", "label": "↓", "shape": "circle", "x": 86, "y": 500, "r": 20},
    18: {"name": "D-pad Left", "label": "←", "shape": "circle", "x": 51, "y": 465, "r": 20},
    19: {"name": "D-pad Right", "label": "→", "shape": "circle", "x": 121, "y": 465, "r": 20},
    20: {
        "name": "L4",
        "label": "L4",
        "shape": "rounded_rect",
        "x": 44,
        "y": 284,
        "w": 44,
        "h": 96,
        "radius": 14,
    },
    21: {
        "name": "R4",
        "label": "R4",
        "shape": "rounded_rect",
        "x": 1140,
        "y": 284,
        "w": 44,
        "h": 96,
        "radius": 14,
    },
    22: {
        "name": "L5",
        "label": "L5",
        "shape": "rounded_rect",
        "x": 96,
        "y": 284,
        "w": 44,
        "h": 96,
        "radius": 14,
    },
    23: {
        "name": "R5",
        "label": "R5",
        "shape": "rounded_rect",
        "x": 1192,
        "y": 284,
        "w": 44,
        "h": 96,
        "radius": 14,
    },
}

# 实体按键触发模式。
# 默认是 momentary；如果某个键需要锁存，就在这里单独改成 "toggle"。
# 这里的配置会被 ControllerPanel 合并到发出的 UDP 按键状态里。
PHYSICAL_BUTTON_MODE_MAP = {
    2: "momentary",  # 快捷菜单键 / ...：按住有效；动作指令窗口打开时再次按下会临时退出
    3: DEFAULT_BUTTON_ACTIVATION_MODE,  # A 键
    4: DEFAULT_BUTTON_ACTIVATION_MODE,  # B 键
    5: DEFAULT_BUTTON_ACTIVATION_MODE,  # X 键
    6: DEFAULT_BUTTON_ACTIVATION_MODE,  # Y 键
    7: DEFAULT_BUTTON_ACTIVATION_MODE,  # 左肩键 LB
    8: DEFAULT_BUTTON_ACTIVATION_MODE,  # 右肩键 RB
    9: DEFAULT_BUTTON_ACTIVATION_MODE,  # 左扳机全按 LT
    10: DEFAULT_BUTTON_ACTIVATION_MODE,  # 右扳机全按 RT
    11: DEFAULT_BUTTON_ACTIVATION_MODE,  # View / Select 键
    12: "toggle",  # Menu / Start 键：本地 ESTOP 需要保持锁存
    13: "momentary",  # Steam 键：按住有效；地图编辑器打开时再次按下会临时退出
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
