"""Zoom factor and scroll anchor. Widget code stays out of this module."""

from __future__ import annotations


def clamp_zoom(zoom: float, low: float = 0.3, high: float = 3.0) -> float:
    return max(low, min(high, zoom))


def anchored_scroll(
    old_zoom: float,
    new_zoom: float,
    cursor_x: float,
    cursor_y: float,
    origin_x: float,
    origin_y: float,
    scroll_x: float,
    scroll_y: float,
    low: float = 0.3,
    high: float = 3.0,
) -> tuple[float, float, float]:
    """Keep the page point under the cursor fixed. Returns zoom and scroll."""
    zoom = clamp_zoom(new_zoom, low, high)
    if old_zoom <= 0:
        return zoom, scroll_x, scroll_y
    page_x = (cursor_x + scroll_x - origin_x) / old_zoom
    page_y = (cursor_y + scroll_y - origin_y) / old_zoom
    return zoom, origin_x + page_x * zoom - cursor_x, origin_y + page_y * zoom - cursor_y
