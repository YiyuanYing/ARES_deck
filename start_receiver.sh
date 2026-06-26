#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

source /opt/ros/humble/setup.bash

if [ -f install/setup.bash ]; then
  source install/setup.bash
fi

/usr/bin/python3 -m app.ros_udp_receiver
