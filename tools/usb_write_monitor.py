#!/usr/bin/env python3
"""通过 Linux usbmon 统计指定 USB 设备的 Bulk OUT 写入情况。"""

from __future__ import annotations

import argparse
import os
import re
import statistics
import time
from pathlib import Path


USBMON_RE = re.compile(
    r"^\S+\s+(?P<timestamp>\d+)\s+(?P<event>[SCE])\s+"
    r"(?P<transfer>[A-Za-z]{2}):(?P<bus>\d+):(?P<device>\d+):(?P<endpoint>\d+)"
    r"\s+(?P<status>-?\d+)\s+(?P<length>\d+)"
)


def parse_hex_id(value: str) -> int:
    return int(value, 16)


def find_device(vid: int, pid: int) -> tuple[int, int, Path]:
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
            return bus, device, entry
    raise RuntimeError(f"找不到 USB 设备 {vid:04x}:{pid:04x}")


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * fraction), len(ordered) - 1)
    return ordered[index]


def print_report(
    started_at: float,
    now: float,
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
        f"rate={count / elapsed:7.2f}Hz packets={count:5d} errors={errors:3d} "
        f"interval[{gap_text}] lengths[{length_text}]",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="统计 USB Bulk OUT 实际完成频率")
    parser.add_argument("--vid", type=parse_hex_id, default=0x1209, help="十六进制 VID，默认 1209")
    parser.add_argument("--pid", type=parse_hex_id, default=0x0001, help="十六进制 PID，默认 0001")
    parser.add_argument("--interval", type=float, default=1.0, help="统计输出周期，单位秒")
    parser.add_argument("--endpoint", type=int, help="只统计指定 OUT endpoint 编号")
    parser.add_argument("--raw", action="store_true", help="同时打印匹配到的 usbmon 原始记录")
    args = parser.parse_args()

    bus, device, sysfs_path = find_device(args.vid, args.pid)
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
        f"sysfs={sysfs_path} source={usbmon_path}",
        flush=True,
    )
    print("统计 USB Bulk OUT 完成事件；Ctrl+C 停止。", flush=True)

    window_start = time.monotonic()
    next_report = window_start + args.interval
    previous_timestamp: int | None = None
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
                            item["event"] == "C"
                            and transfer == "Bo"
                            and int(item["bus"]) == bus
                            and int(item["device"]) == device
                            and (args.endpoint is None or endpoint == args.endpoint)
                        ):
                            if args.raw:
                                print(line.rstrip(), flush=True)
                            timestamp = int(item["timestamp"])
                            status = int(item["status"])
                            length = int(item["length"])
                            count += 1
                            errors += status != 0
                            lengths[length] = lengths.get(length, 0) + 1
                            if previous_timestamp is not None:
                                intervals_ms.append((timestamp - previous_timestamp) / 1000.0)
                            previous_timestamp = timestamp

                if now >= next_report:
                    print_report(window_start, now, count, errors, lengths, intervals_ms)
                    window_start = now
                    next_report = now + args.interval
                    count = 0
                    errors = 0
                    lengths.clear()
                    intervals_ms.clear()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
