"""Snap a candidate box to character cells on one line."""

from __future__ import annotations

from ekisui.domain.index import _cells
from ekisui.domain.types import Rect, TextLine


def snap_boundary(cells: list[Rect], x: float) -> int:
    """Nearest boundary in ``0 .. len(cells)``."""
    if not cells:
        return 0
    best = 0
    best_distance = abs(x - cells[0].x0)
    for index, cell in enumerate(cells):
        distance = abs(x - cell.x0)
        if distance < best_distance:
            best = index
            best_distance = distance
    if abs(x - cells[-1].x1) < best_distance:
        return len(cells)
    return best


def move_edge(start: int, end: int, edge: str, boundary: int, count: int) -> tuple[int, int]:
    """Keep at least one character. ``end`` is exclusive."""
    if count <= 0 or end <= start:
        return start, end
    if edge == "left":
        start = min(max(boundary, 0), end - 1)
        return start, end
    end = max(min(boundary, count), start + 1)
    return start, end


def bind_span(line: TextLine, bbox: Rect) -> tuple[int, int]:
    """Character range whose non-space centers sit in ``bbox``.

    Interior spaces stay inside the range. Empty lines return ``(0, 0)``.
    """
    cells = _cells(line)
    covered = [
        index
        for index, char in enumerate(line.text)
        if not char.isspace() and bbox.contains(*cells[index].center())
    ]
    if not covered:
        covered = [
            index
            for index, char in enumerate(line.text)
            if not char.isspace() and cells[index].intersects(bbox)
        ]
    if not covered:
        return 0, 0
    return min(covered), max(covered) + 1


def bbox_of_range(cells: list[Rect], start: int, end: int) -> Rect:
    chosen = cells[start:end]
    rect = chosen[0]
    for cell in chosen[1:]:
        rect = rect.union(cell)
    return rect.pad(0.6, 0.4)
