#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


DEFAULT_PARAM_PATH = Path(__file__).resolve().parent / "config" / "param.yaml"


def load_app_params(path: Path | None = None) -> Dict[str, Dict[str, Any]]:
    param_path = path or DEFAULT_PARAM_PATH
    if not param_path.exists():
        return {}
    return _parse_simple_yaml(param_path.read_text(encoding="utf-8"))


def get_section(name: str, path: Path | None = None) -> Dict[str, Any]:
    params = load_app_params(path)
    section = params.get(name, {})
    if not isinstance(section, dict):
        return {}
    return section


def _parse_simple_yaml(text: str) -> Dict[str, Dict[str, Any]]:
    data: Dict[str, Dict[str, Any]] = {}
    current_section = ""

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        if not line.startswith((" ", "\t")) and line.endswith(":"):
            current_section = line[:-1].strip()
            data[current_section] = {}
            continue

        if not current_section or ":" not in line:
            continue

        key, value = line.strip().split(":", 1)
        data[current_section][key.strip()] = _parse_scalar(value.strip())

    return data


def _parse_scalar(value: str) -> Any:
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]

    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        return value
