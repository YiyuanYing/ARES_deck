# Steam Deck ControllerFrame V2 Remote Control

本项目用于把 Steam Deck Ubuntu 当作机器人遥控器：

- 通过 Linux joystick 接口 `/dev/input/js0` 读取 Steam Deck 实体按键和左右摇杆。
- 在本地图形化面板中显示实体按键、触发状态、触屏虚拟按钮和摇杆位置。
- 以 UDP 发送固定长度 48 bytes 的 `ControllerFrame V2` 二进制控制帧。
- 机载小电脑或 Windows 笔记本接收后解析成 `axes/buttons/flags` 状态，后续可接入底盘控制、ROS2、串口或 H100 数传模块。

## 目录结构

代码按 `app / ui / core` 三层整理：

```text
app/
  controller_panel.py   # Steam Deck GUI 主入口
  udp_receiver.py       # UDP 接收端 CLI 入口
  udp_sender.py         # 独立 UDP 发送测试入口
  config/
    param.yaml          # app 入口使用的默认 IP、端口、频率和触屏参数

ui/
  config.py             # UI 尺寸、按钮布局、轴映射、默认 UI 参数
  inputs.py             # JoystickReader、TouchReader、HostReachabilityMonitor
  map_editor/           # 3x4 目标地图编辑弹窗、模式上限配置、地图数据转换
  action_command/       # 快捷菜单键动作指令弹窗、2x3 指令、BUILD 和 PLACE
  panel.py              # ControllerPanel、Tkinter 绘制和触屏交互

core/
  map_message.py        # 低频目标地图 UDP JSON 收发和校验
  protocol.py           # ControllerFrame V2 打包、解析、CRC、axes/buttons/flags 编码
  udp_sender.py         # 固定频率 UDP 发送
  udp_receiver.py       # UDP 接收、latest_state、failsafe、ESTOP 状态
```

根目录只保留文档、依赖说明和启动脚本。Python 代码都放在 `app/`、`ui/`、`core/` 中。

- `start_controller.sh`: Steam Deck 上的启动脚本，当前会运行 `python -m app.controller_panel --debug-touch`

## 环境准备

Steam Deck Ubuntu 端：

```bash
conda activate controller
python3 --version
```

Tkinter 通常属于系统包。如果 Ubuntu 缺少 Tkinter：

```bash
sudo apt install python3-tk
```

触屏 evdev 读取是可选能力。没有 `evdev` 时，程序会提示触屏 reader disabled，并保留 Tkinter mouse fallback。如果需要低延迟触屏读取：

```bash
pip install evdev
```

如果读不到 `/dev/input/js0`、触屏 event 设备，或提示 permission denied：

```bash
sudo usermod -aG input $USER
sudo reboot
```

Windows 或 Ubuntu 接收端：

```powershell
conda activate controller
python -m app.udp_receiver --bind-ip 0.0.0.0 --port 5005
```

Windows 如果收不到 UDP，请在 Windows Defender 防火墙中允许 Python 入站，或添加 UDP 5005 入站规则。

## 运行方式

Steam Deck 发送端：

```bash
conda activate controller
python3 -m app.controller_panel --local-ip 10.20.12.220 --target 10.20.99.23:5005:5006
```

多目标 UDP 单播发送：

```bash
python3 -m app.controller_panel \
  --local-ip 10.20.12.220 \
  --target 10.20.99.23:5005:5006 \
  --target 10.20.99.24:5005:5006
```

多目标时，Header 的 LINK 区域会显示所有配置的 host；高频 `ControllerFrame V2` 只发送给当前 connected 的 host。全部断开时显示红色断连警告，部分断开时显示 degraded 警告。目标地图 JSON 暂时仍只发到第一个目标的 `map_port`。

也可以使用启动脚本：

```bash
./start_controller.sh
```

不启动 GUI、循环模拟实体 `A` 键时：

```bash
conda activate controller
python -m app.simulate_controller
```

模拟器默认按现有 `udp_sender` 配置发送，每个 1 秒周期按下 0.5 秒、松开 0.5 秒。可以通过名称或协议 ID 更换按钮：

```bash
python -m app.simulate_controller --button B
python -m app.simulate_controller --button 4
```

接收端：

```powershell
conda activate controller
python -m app.udp_receiver --bind-ip 0.0.0.0 --port 5005
```

ROS2 接收端启动分成两个脚本。先启动 UDP 解码节点：

```bash
./start_receiver.sh
```

该脚本会加载 ROS2 环境和本仓库 `install/setup.bash`，然后运行 `python3 -m app.ros_udp_receiver`：接收 Steam Deck UDP、解码 `ControllerFrame V2`，发布 `/t0x0303_deck` 和 `/aruco_comm/tx_id`。

确认 `/t0x0303_deck` 数据正常后，再另开终端启动 USB 透传节点：

```bash
./start_usb.sh
```

该脚本会运行 `ros2 launch ares_usb comm_bringup.launch.py`：启动 `ares_usb` USB 透传节点，动态订阅 `t0x....` 的 `Float32MultiArray` topic，并按 topic 里的十六进制 DataID 发送到下位机。

`ares_usb` 是接收端的 ROS2 USB 透传包。它会扫描所有 `t0x....` 形式的 `std_msgs/msg/Float32MultiArray` topic，例如 `/t0x0303_deck` 会被解析为 DataID `0x0303`，并按高字节 `0x03` 路由到对应 USB 设备。下位机上报的 DataID 会反向发布成 `/r0x....` topic。

首次部署或修改 `ares_usb` 后，先编译并加载本仓库工作区：

```bash
cd ~/ARES_deck
source /opt/ros/humble/setup.bash
colcon build --packages-select ares_usb
source install/setup.bash
ros2 pkg prefix ares_usb
```

最后一行能输出类似 `~/ARES_deck/install/ares_usb` 就说明包已经可被 `ros2 launch` 找到。

如果只想单独调试 UDP 解码节点，也可以直接运行：

```bash
python3 -m app.ros_udp_receiver
```

默认会按配置频率打印分组 debug log，包含 controller 发布频率、UDP 接收频率、online/timeout/estop、seq、axes 和当前按下的按钮。临时关闭：

```bash
python3 -m app.ros_udp_receiver --no-debug-log
```

临时切回单行格式：

```bash
python3 -m app.ros_udp_receiver --debug-log-format line
```

如果终端不支持颜色，临时关闭彩色 debug log：

```bash
python3 -m app.ros_udp_receiver --no-debug-log-color
```

ROS2 接收端会发布：

- `/controller` (`std_msgs/msg/Float32MultiArray`): 紧凑遥控器状态。
  - `data` 固定 7 个 float，业务 payload 为 `7 * 4 = 28` 字节。
  - `data[0..2]` 是 3 个 16-bit button bitmask，覆盖协议 button id `0..47`。
  - `data[3..6] = [lx, ly, rx, ry]`，放两对摇杆值。
  - 已在 `button_to_tx_id` 中分配为离散命令的按钮不会进入 `/controller` bitmask，只通过 `/aruco_comm/tx_id` 发送。
  - `controller_topics` 可以配置多个类似 `/t0x0303_deck` 的 topic；每个 topic 都发布同一份 7 槽紧凑数据。
  - 摇杆轴在 ROS topic 输出侧按当前坐标约定取反；控制面板 UI 显示保持手柄原方向，订阅端不要再次取反。

多 topic 配置示例：

```yaml
ros_udp_receiver:
  controller_topics:
    - "/t0x0303_deck"
    # - "/t0x0102_deck"
```

`/controller.data` 紧凑布局：

| Index | Meaning |
|---:|---|
| 0 | button bits `0..15` |
| 1 | button bits `16..31` |
| 2 | button bits `32..47` |
| 3 | `lx` |
| 4 | `ly` |
| 5 | `rx` |
| 6 | `ry` |

按键解码示例：

```python
mask0 = int(msg.data[0])
mask1 = int(msg.data[1])
mask2 = int(msg.data[2])

button_3_pressed = bool(mask0 & (1 << 3))    # A
button_20_pressed = bool(mask1 & (1 << 4))   # L4
button_47_pressed = bool(mask2 & (1 << 15))  # R1_CATCH_SEIZE

lx = float(msg.data[3])
ly = float(msg.data[4])
rx = float(msg.data[5])
ry = float(msg.data[6])
```

- `/aruco_comm/tx_id` (`std_msgs/msg/Int32`): 按键到 ArUco tx id 的离散命令映射，默认绑定 Target Action 的 `SELECT/PLACE/BUILD`。
  - 触发后会先发布 3 帧 `0`，再发布 1 帧目标整数；多个触发会排队发送。

UI / 安全保留键不会被 `button_to_tx_id` 用作业务映射：

- `QUICK_ACCESS=2`
- `MENU=12`
- `STEAM=13`

app 默认参数写在 `app/config/param.yaml`：

```yaml
controller_panel:
  local_ip: "10.20.12.220"
  port: 5005
  map_port: 5006
  targets:
    - ip: "10.20.99.23"
      port: 5005
      map_port: 5006
    - ip: "10.20.99.24"
      port: 5005
      map_port: 5006
  send_hz: 100.0

udp_receiver:
  bind_ip: "0.0.0.0"
  port: 5005
  map_port: 5006
  map_receiver_enabled: true

udp_sender:
  local_ip: "10.20.12.220"
  targets:
    - ip: "10.20.99.23"
      port: 5005
      map_port: 5006
```

命令行参数仍然可用，并且会覆盖 `app/config/param.yaml` 中的默认值。

## 之后如何修改 UI

只改界面显示时，优先看 `ui/`，不要动 `core/` 的协议和 UDP：

- 改按钮位置、大小、标签、布局：修改 `ui/config.py` 里的 `VIRTUAL_BUTTON_MAP`、`FOOTER_TOUCH_BUTTONS`、`DISPLAY_BUTTON_MAP`。
- 改颜色、字体、标题、状态栏显示：修改 `ui/panel.py` 里的 `draw_header()`、`draw_virtual_buttons()`、`draw_footer()`、`draw_button()`。
- 改点击后的 UI 行为：修改 `ui/panel.py` 里的 `handle_canvas_touch_xy()`、`toggle_virtual_button()`、`trigger_clear_estop()`。
- 改手柄或触屏读取：修改 `ui/inputs.py` 里的 `JoystickReader`、`TouchReader`。
- 改“UI 状态如何发出去”：修改 `ControllerPanel.get_controller_snapshot()`。如果只是显示变化，不要改这里。
- 改目标地图编辑器：修改 `ui/map_editor/modes.json` 的模式上限，或把 `ui/config.py` 的 `MAP_EDITOR_TRIGGER_BUTTON_ID` 改成需要触发弹窗的按钮 ID。

建议修改后至少运行：

```bash
python -m app.controller_panel --help
python -m core.protocol
```

## ControllerFrame V2 协议

`ControllerFrame V2` 是固定长度 48 bytes 的 Little Endian 二进制帧。

struct 格式：

```python
FRAME_FMT_WITHOUT_CRC = "<HBBHHHHIQQ4h4s"
FRAME_FMT = "<HBBHHHHIQQ4h4sI"
```

CRC32 计算范围：前 44 bytes，即不包含最后 4 bytes `crc32` 字段。

## 低频 UDP JSON

目标地图使用独立低频 UDP JSON 通道，不占用 `ControllerFrame V2`。默认端口是控制端口 `+1`，例如控制帧 `5005`，低频 JSON 消息 `5006`。

### 目标地图

UI 弹窗只编辑中间 `4x3` 区域，发送时自动补成 `6x3`：

- `x=0` 入口行：`[0, 0, 0]`
- `x=1..4`：来自弹窗，从入口向出口排列
- `x=5` 出口行：`[0, 0, 0]`

颜色编码沿用 `mf_action_planner`：

- `0`: 空
- `1`: 蓝色 / KFS1
- `2`: 红色 / KFS2
- `3`: 灰色 / 假 KFS

payload 示例：

```json
{
  "type": "target_map",
  "mode": "崇武探幽",
  "width": 3,
  "height": 6,
  "grid": [[0,0,0],[2,1,0],[3,0,0],[1,0,0],[2,0,0],[0,0,0]],
  "timestamp": 1718400000.0
}
```

R1 receiver 收到后会校验尺寸和颜色编码，缓存 `latest_target_map`，并打印 `[map]` 结构化日志。

### Target Action

快捷菜单键动作窗口不单独发送 JSON topic 或低频 action JSON。它会先映射成 `ControllerFrame V2` 的 `ACTION_*` button bit，再由 ROS2 接收端按 `button_to_tx_id` 转成 `/aruco_comm/tx_id` 离散命令；这些已映射按钮不会进入 `/controller` bitmask。

| ID | Protocol Name | Action |
|---:|---|---|
| 24 | ACTION_SELECT_3_LEFT | `3 LEFT` |
| 25 | ACTION_SELECT_3_MID | `3 MID` |
| 26 | ACTION_SELECT_3_RIGHT | `3 RIGHT` |
| 27 | ACTION_SELECT_2_LEFT | `2 LEFT` |
| 28 | ACTION_SELECT_2_MID | `2 MID` |
| 29 | ACTION_SELECT_2_RIGHT | `2 RIGHT` |
| 30 | ACTION_BUILD | `BUILD` |
| 31 | ACTION_PLACE | `PLACE` |

点击 Target Action 弹窗按钮时，对应 `ACTION_*` button bit 会短暂置为 True。ROS2 接收端检测上升沿后，按默认映射发布 `/aruco_comm/tx_id`：`SELECT` 为 `1~6`，`PLACE=7`，`BUILD=8`；发布顺序是先 3 帧 `0`，再 1 帧目标整数。

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
- Button `0~23`: Steam Deck 实体按键
- Button `24~31`: R2 动作弹窗虚拟按键
- Button `32~47`: 主页机构动作虚拟按键
- Button `48~95`: 虚拟按键扩展预留
- Button `96~127`: 系统保留、调试、扩展

Steam Deck `/dev/input/js0` 当前实体按键映射如下。实体按键编号区为 `0~23`；当前 GUI 会显示并发送 `2~23`，`0~1` 的左右触控板按钮暂时没有加入 `OUTPUT_PHYSICAL_BUTTON_IDS`。

| ID | Protocol Name | UI Label |
|---:|---|---|
| 0 | LEFT_TRACKPAD | - |
| 1 | RIGHT_TRACKPAD | - |
| 2 | QUICK_ACCESS | `...` |
| 3 | A | `A` |
| 4 | B | `B` |
| 5 | X | `X` |
| 6 | Y | `Y` |
| 7 | LB | `LB` |
| 8 | RB | `RB` |
| 9 | LT_FULL | `LT` |
| 10 | RT_FULL | `RT` |
| 11 | VIEW | `VIEW` |
| 12 | MENU | `MENU` |
| 13 | STEAM | `STEAM` |
| 14 | L3 | - |
| 15 | R3 | - |
| 16 | DPAD_UP | `↑` |
| 17 | DPAD_DOWN | `↓` |
| 18 | DPAD_LEFT | `←` |
| 19 | DPAD_RIGHT | `→` |
| 20 | L4 | `L4` |
| 21 | R4 | `R4` |
| 22 | L5 | `L5` |
| 23 | R5 | `R5` |

其中 R1 升降机构使用：

| ID | 实体按键 | 动作 |
|---:|---|---|
| 3 | A | lift：降一挡 |
| 6 | Y | lift：升一挡 |

摇杆轴映射：

| Axis ID | Name |
|---:|---|
| 0 | Left Stick X |
| 1 | Left Stick Y |
| 2 | Right Stick X |
| 3 | Right Stick Y |

R2 动作弹窗使用虚拟按键 `24~31`，由实体 `...` / Quick Access（ID `2`）打开：

| ID | Protocol Name | GUI Label |
|---:|---|---|
| 24 | ACTION_SELECT_3_LEFT | `3 LEFT` |
| 25 | ACTION_SELECT_3_MID | `3 MID` |
| 26 | ACTION_SELECT_3_RIGHT | `3 RIGHT` |
| 27 | ACTION_SELECT_2_LEFT | `2 LEFT` |
| 28 | ACTION_SELECT_2_MID | `2 MID` |
| 29 | ACTION_SELECT_2_RIGHT | `2 RIGHT` |
| 30 | ACTION_BUILD | `BUILD` |
| 31 | ACTION_PLACE | `PLACE` |

主页显示 13 个机构动作虚拟按键，均使用 `momentary` 模式：

| ID | Protocol Name | GUI Label | 动作 |
|---:|---|---|---|
| 32 | SBUS2_M3508_LEFT_EXTEND | `LEFT EXT` | sbus_2：M3508 left extend |
| 33 | SBUS2_M3508_CENTER_EXTEND | `CENTER EXT` | sbus_2：M3508 center extend |
| 34 | SBUS2_M3508_RIGHT_EXTEND | `RIGHT EXT` | sbus_2：M3508 right extend |
| 35 | SBUS2_M2006_LEFT_DOWN | `LEFT DOWN` | sbus_2：M2006 left down |
| 36 | SBUS2_M2006_RIGHT_DOWN | `RIGHT DOWN` | sbus_2：M2006 right down |
| 37 | SBUS2_RELAY_LEFT | `RELAY LEFT` | sbus_2：relay left |
| 38 | SBUS2_RELAY_CENTER | `RELAY CENTER` | sbus_2：relay center |
| 39 | SBUS2_RELAY_RIGHT | `RELAY RIGHT` | sbus_2：relay right |
| 40 | R1_CATCH_PREPARE | `PREPARE` | R1_catch：prepare |
| 41 | R1_CATCH_RAISE | `RAISE` | R1_catch：raise |
| 42 | R1_CATCH_ATTACK | `ATTACK` | R1_catch：attack |
| 43~45 | - | - | 保留未分配 |
| 46 | R1_CATCH_RELEASE | `RELEASE` | R1_catch：release |
| 47 | R1_CATCH_SEIZE | `SEIZE` | R1_catch：seize |

按键激活方式在 `ui/config.py` 中配置：

- `toggle`: 按一次锁存为 True，再按一次解除。
- `momentary`: 按住为 True，松开为 False。

默认触发方式是 `momentary`。屏幕虚拟按钮在 `VIRTUAL_BUTTON_MAP` 的每个按钮条目里设置 `"mode"`。Steam Deck 实体按钮在 `PHYSICAL_BUTTON_MODE_MAP` 里按 ID 设置，其中 `MENU / Start` 保持 `toggle` 用于本地 ESTOP。普通实体按键和主页虚拟按键会合并到 `buttons` bitmask；已映射到 `/aruco_comm/tx_id` 的 R2 Target Action 按钮不会进入 `/controller` bitmask。

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

如果发送端传入 `enable=True`，则设置 `ENABLE`。当前 GUI 中 MENU 关闭时 `enable=True`，MENU 打开进入 ESTOP 时 `enable=False`。

如果发送端传入 `estop=True`，则设置 `ESTOP`。当前 GUI 使用 `MENU` 作为唯一手动 ESTOP/ENABLE/CLEAR 开关：按下 MENU 进入 ESTOP，再按一次 MENU 恢复 enable；底部 `CLEAR ESTOP` 也会清除 MENU 急停状态。

当前 13 个主页虚拟按钮不会直接修改 flags；它们只作为普通 button bit 发送。

## 心跳保护和 Failsafe

发送端固定 100 Hz 发送，也就是每 10 ms 一帧。

接收端行为：

- 收到一帧通过长度、magic、version、msg_type、length 字段和 CRC32 检查的数据，就认为是有效心跳。
- 超过 50 ms 没有收到有效帧：认为链路异常，并显示 warning。
- 超过 `failsafe_timeout_ms` 没有收到有效帧：进入 remote timeout，`axes/buttons` 输出清零。
- `failsafe_timeout_ms` 默认来自数据帧，默认值 150 ms。
- 接收端会限制 timeout：`timeout_ms = clamp(failsafe_timeout_ms, 50, 300)`。
- 收到 `ESTOP` flag 会立即进入急停并清零输出。
- 当前 GUI 使用 `MENU` 作为唯一手动 ESTOP 开关。Steam Deck 底部 `CLEAR ESTOP` 会清除本地 MENU/ESTOP 状态。

## 日志解释

示例：

```text
[21:44:05] online  from=10.20.12.220:53908  seq=30807  rx=100/s lost=0(0.00%) ooo=0 jitter=2.3ms age=34ms axes=L(+0.00,+0.00) R(+0.00,+0.00) buttons=-
```

字段含义：

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
- `frame={...}`: 最近一帧 ControllerFrame V2 的完整字段内容。

超时示例：

```text
[21:44:05] TIMEOUT age=168ms -> ESTOP axes=L(+0.00,+0.00) R(+0.00,+0.00)
```

## 协议自测

```bash
conda activate controller
python -m core.protocol
```

自测会 build 一帧、parse 回来，并检查 axes、buttons、flags 和 CRC。

## 后续扩展

把 UDP 换成 H100 数传：

- 保留 `core/protocol.py` 不变。
- 新建 H100 transport 模块，调用 `build_controller_frame()` 得到 48 bytes。
- 接收端读取 H100 串口/链路数据后，按 48 bytes 帧边界调用 `parse_controller_frame()`。

接入 ROS2 / 串口 / 机器人底盘控制：

- 在机载小电脑程序中创建 `ControllerUdpReceiver`。
- 以 100 Hz 控制周期调用 `receiver.update_state()` 或读取 `receiver.get_latest_state()`。
- 把 `latest_state["axes"]`、`latest_state["buttons"]`、`latest_state["flags"]` 映射到底盘速度、机构动作和安全状态。
- 急停和 timeout 应优先级最高，进入 ESTOP 后不要自动恢复输出。

sudo ip addr flush dev enx00e09a50a5cc
sudo ip addr add 192.168.0.20/24 dev enx00e09a50a5cc
sudo ip link set enx00e09a50a5cc up
