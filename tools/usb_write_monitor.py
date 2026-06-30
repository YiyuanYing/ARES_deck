#!/usr/bin/env python3
"""通过 Linux usbmon 统计指定 USB 设备的 Bulk OUT 写入情况。"""

from __future__ import annotations

import argparse
import os
import re
import statistics
import struct
import time
from dataclasses import dataclass
from pathlib import Path


USBMON_RE = re.compile(
    r"^\S+\s+(?P<timestamp>\d+)\s+(?P<event>[SCE])\s+"
    r"(?P<transfer>[A-Za-z]{2}):(?P<bus>\d+):(?P<device>\d+):(?P<endpoint>\d+)"
    r"\s+(?P<status>-?\d+)\s+(?P<length>\d+)(?P<remainder>.*)$"
)


def parse_hex_id(value: str) -> int:
    return int(value, 16)


@dataclass(frozen=True)
class UsbDevice:
    vid: int
    pid: int
    bus: int
    device: int
    serial: str
    sysfs_path: Path


def find_devices(vid: int, pid: int) -> list[UsbDevice]:
    devices = []
    for entry in Path("/sys/bus/usb/devices").iterdir():
        vid_path = entry / "idVendor"
        pid_path = entry / "idProduct"
        if not vid_path.exists() or not pid_path.exists():
            continue
        try:
            entry_vid = int(vid_path.read_text().strip(), 16)
            entry_pid = int(pid_path.read_text().strip(), 16)
        except (OSError, ValueError):
            continue
        if entry_vid == vid and entry_pid == pid:
            bus = int((entry / "busnum").read_text().strip())
            device = int((entry / "devnum").read_text().strip())
            serial_path = entry / "serial"
            serial = serial_path.read_text().strip() if serial_path.exists() else "-"
            devices.append(UsbDevice(vid, pid, bus, device, serial, entry))
    return sorted(devices, key=lambda item: (item.bus, item.device))


def print_devices(devices: list[UsbDevice]) -> None:
    if not devices:
        print("没有找到匹配的 USB 设备")
        return
    print("VID:PID    BUS DEVICE SERIAL")
    for item in devices:
        print(
            f"{item.vid:04x}:{item.pid:04x}  "
            f"{item.bus:03d} {item.device:03d}    {item.serial}"
        )


def select_device(
    devices: list[UsbDevice],
    serial: str | None,
    bus: int | None,
    device: int | None,
) -> UsbDevice:
    if (bus is None) != (device is None):
        raise RuntimeError("--bus 和 --device 必须一起使用")

    matches = devices
    if serial is not None:
        matches = [item for item in matches if item.serial == serial]
    if bus is not None:
        matches = [
            item for item in matches
            if item.bus == bus and item.device == device
        ]

    if not matches:
        raise RuntimeError("找不到符合指定条件的 USB 设备")
    if len(matches) > 1:
        print_devices(matches)
        raise RuntimeError(
            "同一 VID/PID 匹配到多块设备，请使用 --serial 或 --bus/--device 指定"
        )
    return matches[0]


def parse_payload(remainder: str) -> bytes | None:
    if "=" not in remainder:
        return None
    hex_text = "".join(re.findall(r"[0-9A-Fa-f]+", remainder.split("=", 1)[1]))
    if not hex_text or len(hex_text) % 2:
        return None
    try:
        return bytes.fromhex(hex_text)
    except ValueError:
        return None


def decode_payload(payload: bytes, requested_length: int) -> str:
    suffix = ""
    if len(payload) < requested_length:
        suffix = f" captured={len(payload)}/{requested_length}B"
    if len(payload) < 2:
        return f"RAW={payload.hex(' ')}{suffix}"

    head = struct.unpack_from(">H", payload)[0]
    if head == 0x5A5A and len(payload) >= 4:
        data_id = struct.unpack_from(">H", payload, 2)[0]
        data = payload[4:]
        if data_id == 0x0303 and len(data) >= 28:
            values = struct.unpack_from("<7f", data)
            masks = tuple(int(round(value)) for value in values[:3])
            axes = values[3:]
            return (
                f"SYNC id=0x{data_id:04X} "
                f"mask=[{masks[0]:04X},{masks[1]:04X},{masks[2]:04X}] "
                f"axes=[lx={axes[0]:+.3f},ly={axes[1]:+.3f},"
                f"rx={axes[2]:+.3f},ry={axes[3]:+.3f}]{suffix}"
            )
        return (
            f"SYNC id=0x{data_id:04X} data={data.hex(' ')}{suffix}"
        )

    if head == 0xCADE and len(payload) >= 6:
        request_id = payload[2]
        error_code = struct.unpack_from(">H", payload, 4)[0]
        return (
            f"HEARTBEAT request_id=0x{request_id:02X} "
            f"error_code=0x{error_code:04X}{suffix}"
        )

    return f"HEAD=0x{head:04X} raw={payload.hex(' ')}{suffix}"


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * fraction), len(ordered) - 1)
    return ordered[index]


def print_report(
    started_at: float,
    now: float,
    submitted: int,
    count: int,
    errors: int,
    lengths: dict[int, int],
    intervals_ms: list[float],
) -> None:
    elapsed = max(now - started_at, 1e-9)
    length_text = ",".join(f"{length}B:{amount}" for length, amount in sorted(lengths.items())) or "-"
    if intervals_ms:
        avg = statistics.fmean(intervals_ms)
        p95 = percentile(intervals_ms, 0.95)
        maximum = max(intervals_ms)
        gap_text = f"avg={avg:.3f}ms p95={p95:.3f}ms max={maximum:.3f}ms"
    else:
        gap_text = "avg=- p95=- max=-"
    print(
        f"submit={submitted / elapsed:7.2f}Hz complete={count / elapsed:7.2f}Hz "
        f"packets={count:5d} errors={errors:3d} "
        f"interval[{gap_text}] lengths[{length_text}]",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="统计 USB Bulk OUT 实际完成频率")
    parser.add_argument("--vid", type=parse_hex_id, default=0x1209, help="十六进制 VID，默认 1209")
    parser.add_argument("--pid", type=parse_hex_id, default=0x0001, help="十六进制 PID，默认 0001")
    parser.add_argument("--serial", help="按 USB 序列号指定设备，重新插拔后仍有效")
    parser.add_argument("--bus", type=int, help="USB Bus 编号，需和 --device 一起使用")
    parser.add_argument("--device", type=int, help="USB Device 编号，需和 --bus 一起使用")
    parser.add_argument("--list-devices", action="store_true", help="列出匹配 VID/PID 的设备后退出")
    parser.add_argument("--interval", type=float, default=1.0, help="统计输出周期，单位秒")
    parser.add_argument("--endpoint", type=int, help="只统计指定 OUT endpoint 编号")
    parser.add_argument("--raw", action="store_true", help="同时打印匹配到的 usbmon 原始记录")
    parser.add_argument("--decode", action="store_true", help="解码 Bulk OUT 提交事件中的 ARES 协议帧")
    args = parser.parse_args()

    devices = find_devices(args.vid, args.pid)
    if args.list_devices:
        print_devices(devices)
        return
    try:
        selected = select_device(devices, args.serial, args.bus, args.device)
    except RuntimeError as error:
        raise SystemExit(str(error)) from error

    bus = selected.bus
    device = selected.device
    usbmon_path = Path(f"/sys/kernel/debug/usb/usbmon/{bus}u")
    if not usbmon_path.exists():
        raise SystemExit(
            f"{usbmon_path} 不存在，请先执行：sudo modprobe usbmon\n"
            "如果 /sys/kernel/debug 未挂载，再执行：sudo mount -t debugfs none /sys/kernel/debug"
        )
    if not os.access(usbmon_path, os.R_OK):
        raise SystemExit(f"没有权限读取 {usbmon_path}，请使用 sudo 运行本程序")

    print(
        f"monitoring {args.vid:04x}:{args.pid:04x} bus={bus:03d} device={device:03d} "
        f"serial={selected.serial} sysfs={selected.sysfs_path} source={usbmon_path}",
        flush=True,
    )
    print("统计 USB Bulk OUT 完成事件；Ctrl+C 停止。", flush=True)

    window_start = time.monotonic()
    next_report = window_start + args.interval
    previous_timestamp: int | None = None
    submitted = 0
    count = 0
    errors = 0
    lengths: dict[int, int] = {}
    intervals_ms: list[float] = []

    try:
        with usbmon_path.open("r", encoding="ascii", errors="replace", buffering=1) as stream:
            while True:
                line = stream.readline()
                now = time.monotonic()
                if line:
                    match = USBMON_RE.match(line)
                    if match:
                        item = match.groupdict()
                        transfer = item["transfer"]
                        endpoint = int(item["endpoint"])
                        if (
                            transfer == "Bo"
                            and int(item["bus"]) == bus
                            and int(item["device"]) == device
                            and (args.endpoint is None or endpoint == args.endpoint)
                        ):
                            if args.raw:
                                print(line.rstrip(), flush=True)
                            timestamp = int(item["timestamp"])
                            status = int(item["status"])
                            length = int(item["length"])
                            if item["event"] == "S":
                                submitted += 1
                                if args.decode:
                                    payload = parse_payload(item["remainder"])
                                    if payload is None:
                                        print(
                                            f"SUBMIT {length}B payload unavailable",
                                            flush=True,
                                        )
                                    else:
                                        print(
                                            f"SUBMIT {length}B "
                                            f"{decode_payload(payload, length)}",
                                            flush=True,
                                        )
                            elif item["event"] == "C":
                                count += 1
                                errors += status != 0
                                lengths[length] = lengths.get(length, 0) + 1
                                if previous_timestamp is not None:
                                    intervals_ms.append(
                                        (timestamp - previous_timestamp) / 1000.0
                                    )
                                previous_timestamp = timestamp

                if now >= next_report:
                    print_report(
                        window_start,
                        now,
                        submitted,
                        count,
                        errors,
                        lengths,
                        intervals_ms,
                    )
                    window_start = now
                    next_report = now + args.interval
                    submitted = 0
                    count = 0
                    errors = 0
                    lengths.clear()
                    intervals_ms.clear()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
