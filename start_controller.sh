#!/usr/bin/env bash
set -e

conda init

conda activate controller

python -m app.controller_panel --debug-touch
