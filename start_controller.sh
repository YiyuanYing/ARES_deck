#!/usr/bin/env bash
set -e

source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate controller

export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-/run/user/1000/gdm/Xauthority}"

python -m app.controller_panel --debug-touch
