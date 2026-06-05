# Steam Deck ControllerFrame V2 Remote Control

本项目用于把 Steam Deck Ubuntu 当作机器人遥控器：

- 通过 Linux joystick 接口 `/dev/input/js0` 读取 Steam Deck 实体按键和左右摇杆。
- 在本地图形化面板中显示按键、toggle 状态和摇杆位置。
- 以 UDP 发送固定长度 48 bytes 的 `ControllerFrame V2` 二进制控制帧。
- 机载小电脑或 Windows 笔记本接收后解析成 `axes/buttons/flags` 状态，后续可直接接入底盘控制、ROS2、串口或 H100 数传模块。

## 文件说明

- `steamdeck_controller_panel.py`: Steam Deck GUI 面板，读取 `/dev/input/js0`，接入 100 Hz UDP 发送。
- `controller_protocol.py`: 协议层，只负责 ControllerFrame V2 打包、解析、CRC 校验、axes/buttons/flags 编码。
- `controller_udp_sender.py`: UDP 发送层，使用 `time.perf_counter()` 固定 100 Hz 发送二进制帧。
- `controller_udp_receiver.py`: UDP 接收端，收包线程解析数据，主循环 100 Hz 维护 `latest_state` 和 failsafe。
- `udp_receiver.py`: 兼容入口，等价于运行 `controller_udp_receiver.py`。

## 环境准备

Steam Deck Ubuntu 端：

```bash
conda activate controller
python3 --version
```

当前代码只使用 Python 标准库。Tkinter 通常属于系统包，如果 Ubuntu 缺少 Tkinter：

```bash
sudo apt install python3-tk
```

如果读不到 `/dev/input/js0` 或提示 permission denied：

```bash
sudo usermod -aG input $USER
sudo reboot
```

Windows 或 Ubuntu 接收端：

```powershell
conda activate controller
python controller_udp_receiver.py --bind-ip 0.0.0.0 --port 5005
```

Windows 如果收不到 UDP，请在 Windows Defender 防火墙中允许 Python 入站，或添加 UDP 5005 入站规则。

## 运行方式

Steam Deck 发送端：

```bash
conda activate controller
python3 steamdeck_controller_panel.py --local-ip 10.20.12.220 --target-ip 10.20.99.23 --port 5005
```

接收端：

```powershell
conda activate controller
python controller_udp_receiver.py --bind-ip 0.0.0.0 --port 5005
```

也可以继续使用旧入口：

```powershell
python udp_receiver.py --bind-ip 0.0.0.0 --port 5005
```

默认目标地址在 `controller_udp_sender.py` 顶部：

```python
LOCAL_IP = "10.20.12.220"
TARGET_IP = "10.20.99.23"
TARGET_PORT = 5005
SEND_HZ = 100.0
```

也可以通过命令行参数覆盖。

## ControllerFrame V2 协议

`ControllerFrame V2` 是固定长度 48 bytes 的 Little Endian 二进制帧。

struct 格式：

```python
FRAME_FMT_WITHOUT_CRC = "<HBBHHHHIQQ4h4s"
FRAME_FMT = "<HBBHHHHIQQ4h4sI"
```

CRC32 计算范围：前 44 bytes，即不包含最后 4 bytes `crc32` 字段。

| Offset | Size | Type | Name | Description |
|---:|---:|---|---|---|
| 0 | 2 | uint16 | magic | 固定 `0xA55A` |
| 2 | 1 | uint8 | version | 当前为 `2` |
| 3 | 1 | uint8 | msg_type | 控制帧为 `1` |
| 4 | 2 | uint16 | length | 固定 `48` |
| 6 | 2 | uint16 | flags | 状态标志位 |
| 8 | 2 | uint16 | seq | 帧序号，`0~65535` 循环 |
| 10 | 2 | uint16 | failsafe_timeout_ms | 心跳超时时间，默认 `150 ms` |
| 12 | 4 | uint32 | timestamp_ms | Steam Deck `time.monotonic()` 毫秒时间戳，截断到 uint32 |
| 16 | 8 | uint64 | buttons_low | Button `0~63` |
| 24 | 8 | uint64 | buttons_high | Button `64~127` |
| 32 | 2 | int16 | axis_lx | 左摇杆 X，`-1000~1000` |
| 34 | 2 | int16 | axis_ly | 左摇杆 Y，`-1000~1000` |
| 36 | 2 | int16 | axis_rx | 右摇杆 X，`-1000~1000` |
| 38 | 2 | int16 | axis_ry | 右摇杆 Y，`-1000~1000` |
| 40 | 4 | bytes | reserved | 当前填 0 |
| 44 | 4 | uint32 | crc32 | 对前 44 bytes 计算 CRC32 |

接收端有效帧检查：

1. 长度必须为 48 bytes。
2. `magic == 0xA55A`。
3. `version == 2`。
4. `msg_type == 1`。
5. `length == 48`。
6. `crc32` 校验正确。

## Axes 编码

GUI 内部继续使用 `-1.0~1.0` float。

发送端：

```python
axis_int = round(axis_float * 1000)
axis_int = clamp(axis_int, -1000, 1000)
```

接收端：

```python
axis_float = axis_int / 1000.0
```

示例：

- `lx = 0.123 -> 123 -> 0.123`
- `ly = -0.350 -> -350 -> -0.350`

## Buttons 编码

buttons 使用 128-bit bitmask：

- `buttons_low`: Button `0~63`
- `buttons_high`: Button `64~127`
- Button `0~31`: Steam Deck 实体按键
- Button `32~95`: 屏幕虚拟按键
- Button `96~127`: 系统保留、调试、扩展

Steam Deck `/dev/input/js0` 当前实体按键映射：

| ID | Name |
|---:|---|
| 0 | LEFT_TRACKPAD |
| 1 | RIGHT_TRACKPAD |
| 2 | QUICK_ACCESS |
| 3 | A |
| 4 | B |
| 5 | X |
| 6 | Y |
| 7 | LB |
| 8 | RB |
| 9 | LT_FULL |
| 10 | RT_FULL |
| 11 | VIEW |
| 12 | MENU |
| 13 | STEAM |
| 14 | L3 |
| 15 | R3 |
| 16 | DPAD_UP |
| 17 | DPAD_DOWN |
| 18 | DPAD_LEFT |
| 19 | DPAD_RIGHT |
| 20 | L4 |
| 21 | R4 |
| 22 | L5 |
| 23 | R5 |

预留虚拟按键：

| ID | Name |
|---:|---|
| 32 | VIRTUAL_ESTOP |
| 33 | VIRTUAL_ENABLE |
| 34 | VIRTUAL_LOW_SPEED |
| 35 | VIRTUAL_HIGH_SPEED |
| 36 | VIRTUAL_AUTO_MODE |
| 37 | VIRTUAL_RESET |

发送端默认发送 physical pressed 状态。GUI 中绿色 toggle 状态目前只用于显示，后续可以映射到 `32~95` 的虚拟按键。

## Flags

`flags` 是 uint16：

| Bit | Name | Description |
|---:|---|---|
| 0 | ENABLE | 遥控器使能 |
| 1 | ESTOP | 急停 |
| 2 | FULL_STATE | 当前帧包含完整状态 |
| 3 | HEARTBEAT | 当前帧作为心跳 |
| 4 | MANUAL_MODE | 手动模式 |
| 5 | AUTO_MODE | 自动模式 |
| 6~15 | reserved | 预留 |

每一帧默认设置：

- `FULL_STATE = 1`
- `HEARTBEAT = 1`
- `MANUAL_MODE = 1`

如果 `enable=True` 或 `VIRTUAL_ENABLE` 被按下，则设置 `ENABLE`。

如果 `STEAM`、`VIRTUAL_ESTOP` 或发送端传入 `estop=True`，则设置 `ESTOP`。

## 心跳保护和 Failsafe

发送端固定 100 Hz 发送，也就是每 10 ms 一帧。

接收端行为：

- 收到一帧通过长度、magic、version、msg_type、length 字段和 CRC32 检查的数据，就认为是有效心跳。
- 超过 50 ms 没有收到有效帧：认为链路异常，`axes` 输出清零，并显示 warning。
- 超过 `failsafe_timeout_ms` 没有收到有效帧：进入 remote timeout / ESTOP，`axes` 输出清零。
- `failsafe_timeout_ms` 默认来自数据帧，默认值 150 ms。
- 接收端会限制 timeout：`timeout_ms = clamp(failsafe_timeout_ms, 50, 300)`。
- 收到 `ESTOP` flag 会立即进入急停。
- 当前版本进入急停后不会自动解除，代码中保留了 `TODO`，后续可用 `VIRTUAL_RESET` 或 ENABLE 逻辑明确解除。

接收端维护的 `latest_state` 结构类似：

```python
{
    "online": True,
    "remote_timeout": False,
    "seq": 1234,
    "age_ms": 12.3,
    "jitter_ms": 2.1,
    "lost": 0,
    "ooo": 0,
    "flags": {
        "enable": True,
        "estop": False,
        "full_state": True,
        "heartbeat": True,
        "manual_mode": True,
        "auto_mode": False,
    },
    "axes": {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0},
    "buttons": {"A": False, "B": False, "X": False, "Y": False, "LB": False, "RB": False, "STEAM": False},
}
```

## 日志解释

示例：

```text
[21:44:05] online  from=10.20.12.220:53908  seq=30807  rx=100/s lost=0(0.00%) ooo=0 jitter=2.3ms age=34ms axes=L(+0.00,+0.00) R(+0.00,+0.00) buttons=-
```

字段含义：

- `[21:44:05]`: 本机显示时间。
- `online`: 链路状态，也可能显示 `WARN`、`ESTOP`、`TIMEOUT`、`waiting`。
- `from`: 最近一帧来源 IP 和 UDP 源端口。
- `seq`: 最近有效帧序号。
- `rx=100/s`: 最近 1 秒收到的有效帧数量。
- `lost`: 根据 seq 推算的丢包数量和百分比。
- `ooo`: out of order，乱序包数量。
- `jitter`: 接收帧间隔抖动。
- `age`: 距离最近有效帧的时间。
- `axes`: 左右摇杆状态。
- `buttons`: 当前按下的可读按钮名，`-` 表示没有按键按下。

超时示例：

```text
[21:44:05] TIMEOUT age=168ms -> ESTOP axes=L(+0.00,+0.00) R(+0.00,+0.00)
```

## 协议自测

```bash
conda activate controller
python controller_protocol.py
```

自测会 build 一帧、parse 回来，并检查 axes、buttons、flags 和 CRC。

## 后续扩展

加入屏幕虚拟按键：

- 在 GUI 中添加触屏按钮。
- 把触屏按钮状态写入 `VIRTUAL_ESTOP`、`VIRTUAL_ENABLE`、`VIRTUAL_LOW_SPEED` 等 ID。
- 在 `get_controller_snapshot()` 中把这些状态合并到 `buttons` dict。

把 UDP 换成 H100 数传：

- 保留 `controller_protocol.py` 不变。
- 新建 H100 transport 模块，调用 `build_controller_frame()` 得到 48 bytes。
- 接收端读取 H100 串口/链路数据后，按 48 bytes 帧边界调用 `parse_controller_frame()`。

接入 ROS2 / 串口 / 机器人底盘控制：

- 在机载小电脑程序中创建 `ControllerUdpReceiver`。
- 以 100 Hz 控制周期调用 `receiver.update_state()` 或读取 `receiver.get_latest_state()`。
- 把 `latest_state["axes"]`、`latest_state["buttons"]`、`latest_state["flags"]` 映射到底盘速度、机构动作和安全状态。
- 急停和 timeout 应优先级最高，进入 ESTOP 后不要自动恢复输出。
