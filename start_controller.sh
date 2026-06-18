#!/usr/bin/env bash
set -e

cd "$HOME/ARES_deck"

source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate controller

python steamdeck_controller_panel.py --debug-touch