#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

source /opt/ros/humble/setup.bash

if [ -f install/setup.bash ]; then
  source install/setup.bash
fi

exec ros2 launch ares_usb_bridge usb_bridge.launch.py
