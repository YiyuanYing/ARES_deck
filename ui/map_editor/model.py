#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

EDIT_WIDTH = 3
EDIT_HEIGHT = 4

EMPTY = 0
BLUE = 1
RED = 2
GRAY = 3

COLOR_NAMES = {
    EMPTY: "EMPTY",
    BLUE: "BLUE",
    RED: "RED",
    GRAY: "GRAY",
}

COLOR_KEYS = {
    BLUE: "blue",
    RED: "red",
    GRAY: "gray",
}

DEFAULT_MODES_PATH = Path(__file__).resolve().parent / "modes.json"


@dataclass(frozen=True)
class MapMode:
    name: str
    red_max: int
    blue_max: int
    gray_max: int

    def limit_for(self, cell_value: int) -> int:
        if cell_value == RED:
            return self.red_max
        if cell_value == BLUE:
            return self.blue_max
        if cell_value == GRAY:
            return self.gray_max
        return EDIT_WIDTH * EDIT_HEIGHT


def load_map_modes(path: Path = DEFAULT_MODES_PATH) -> Dict[str, MapMode]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    modes: Dict[str, MapMode] = {}
    for name, spec in raw.items():
        modes[name] = MapMode(
            name=name,
            red_max=int(spec.get("red_max", 0)),
            blue_max=int(spec.get("blue_max", 0)),
            gray_max=int(spec.get("gray_max", 0)),
        )
    if not modes:
        raise ValueError(f"no map modes configured in {path}")
    return modes


def empty_edit_grid() -> List[List[int]]:
    return [[EMPTY for _col in range(EDIT_WIDTH)] for _row in range(EDIT_HEIGHT)]


def count_cells(edit_grid: List[List[int]]) -> Dict[int, int]:
    counts = {EMPTY: 0, BLUE: 0, RED: 0, GRAY: 0}
    for row in edit_grid:
        for value in row:
            counts[int(value)] = counts.get(int(value), 0) + 1
    return counts


def validate_edit_grid(edit_grid: List[List[int]], mode: MapMode) -> None:
    if len(edit_grid) != EDIT_HEIGHT:
        raise ValueError("edit grid must have 4 rows")
    for row_index, row in enumerate(edit_grid):
        if len(row) != EDIT_WIDTH:
            raise ValueError(f"edit grid row {row_index} must have 3 columns")
        for value in row:
            if int(value) not in COLOR_NAMES:
                raise ValueError(f"invalid map cell value: {value!r}")

    counts = count_cells(edit_grid)
    for value in (RED, BLUE, GRAY):
        if counts.get(value, 0) > mode.limit_for(value):
            raise ValueError(f"{COLOR_NAMES[value]} limit exceeded")


def build_full_grid(edit_grid: List[List[int]]) -> List[List[int]]:
    """Convert screen top-to-bottom rows into planner x=0..5 rows.

    The UI shows exit at the top and entrance at the bottom. The planner expects
    x=0 as the entrance row and x=5 as the exit row, so the editable rows are
    reversed when creating the full 6x3 grid.
    """
    return (
        [[EMPTY, EMPTY, EMPTY]]
        + [list(row) for row in reversed(edit_grid)]
        + [[EMPTY, EMPTY, EMPTY]]
    )
