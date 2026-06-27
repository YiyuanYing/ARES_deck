#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

source /opt/ros/humble/setup.bash

if [ -f install/setup.bash ]; then
  source install/setup.bash
fi

/usr/bin/python3 -m app.ros_udp_receiver &
receiver_pid=$!

ros2 launch ares_usb comm_bringup.launch.py &
usb_pid=$!

cleanup() {
  kill "$receiver_pid" "$usb_pid" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

wait -n "$receiver_pid" "$usb_pid"
