"""Zoom factor and scroll anchor. Widget code stays out of this module."""

from __future__ import annotations


def clamp_zoom(zoom: float, low: float = 0.3, high: float = 3.0) -> float:
    return max(low, min(high, zoom))


def stack_offsets(sizes: list[tuple[int, int]], gap: int = 16) -> list[tuple[int, int]]:
    """Top-left of each page in a vertical stack. Pages are centered on the widest one."""
    if not sizes:
        return []
    width = max(item[0] for item in sizes)
    top = 0
    placed: list[tuple[int, int]] = []
    for page_width, page_height in sizes:
        placed.append(((width - page_width) // 2, top))
        top += page_height + gap
    return placed


def page_at_scroll(spans: list[tuple[int, int]], scroll: int, viewport: int, gap: int = 16) -> int:
    """Index of the page under a point a third of the way down the viewport.

    ``spans`` are ``(top, height)`` in the stacked page column. The gap between
    pages belongs to the page that follows it, so the indicator moves as the
    next page comes into view.
    """
    if not spans:
        return 0
    probe = scroll + max(1, int(viewport * 0.35))
    for index, (top, height) in enumerate(spans):
        limit = top + height
        if index < len(spans) - 1:
            limit += gap
        if probe < limit:
            return index
    return len(spans) - 1


def scroll_to_keep_point(
    page_x: float,
    page_y: float,
    zoom: float,
    cursor_x: float,
    cursor_y: float,
    frame_x: float,
    frame_y: float,
) -> tuple[float, float]:
    """Scroll offsets that keep a page point under the viewport cursor.

    ``frame_x`` and ``frame_y`` are the page origin in the stacked column
    after the zoom has been applied.
    """
    return frame_x + page_x * zoom - cursor_x, frame_y + page_y * zoom - cursor_y


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
