"""Ctrl+wheel and pinch keep the page point under the cursor."""

from ekisui.gui.zoom import anchored_scroll, clamp_zoom


def test_clamp():
    assert clamp_zoom(0.1) == 0.3
    assert clamp_zoom(4.0) == 3.0
    assert clamp_zoom(1.25) == 1.25


def test_anchor_stays_under_the_cursor():
    zoom, scroll_x, scroll_y = anchored_scroll(
        old_zoom=1.0,
        new_zoom=2.0,
        cursor_x=100,
        cursor_y=80,
        origin_x=18,
        origin_y=18,
        scroll_x=40,
        scroll_y=10,
    )
    assert zoom == 2.0
    page_x = (100 + 40 - 18) / 1.0
    page_y = (80 + 10 - 18) / 1.0
    assert scroll_x == 18 + page_x * 2.0 - 100
    assert scroll_y == 18 + page_y * 2.0 - 80
    again_x = (100 + scroll_x - 18) / zoom
    again_y = (80 + scroll_y - 18) / zoom
    assert again_x == page_x
    assert again_y == page_y


def test_anchor_respects_the_zoom_limit():
    zoom, scroll_x, _scroll_y = anchored_scroll(1.0, 9.0, 10, 10, 0, 0, 0, 0)
    assert zoom == 3.0
    assert scroll_x == 10 * 3.0 - 10
