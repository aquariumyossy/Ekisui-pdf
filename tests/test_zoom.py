"""Ctrl+wheel and pinch keep the page point under the cursor."""

from ekisui.gui.zoom import anchored_scroll, clamp_zoom, page_at_scroll, scroll_to_keep_point, stack_offsets


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


def test_stack_centers_a_narrow_page_and_scroll_crosses_the_gap():
    placed = stack_offsets([(200, 400), (100, 300)], gap=16)
    assert placed[0] == (0, 0)
    assert placed[1] == (50, 416)
    spans = [(y, height) for (_x, y), (_w, height) in zip(placed, [(200, 400), (100, 300)])]
    assert page_at_scroll(spans, 0, 180, gap=16) == 0
    assert page_at_scroll(spans, 360, 180, gap=16) == 1
    short = [(0, 400), (416, 80)]
    assert page_at_scroll(short, 296, 200, gap=16) == 1


def test_scroll_keeps_a_point_on_a_lower_page():
    page_x, page_y = 40.0, 25.0
    scroll_x, scroll_y = scroll_to_keep_point(page_x, page_y, 2.0, 30.0, 50.0, 10.0, 500.0)
    assert scroll_x == 10.0 + 40.0 * 2.0 - 30.0
    assert scroll_y == 500.0 + 25.0 * 2.0 - 50.0


def test_anchor_respects_the_zoom_limit():
    zoom, scroll_x, _scroll_y = anchored_scroll(1.0, 9.0, 10, 10, 0, 0, 0, 0)
    assert zoom == 3.0
    assert scroll_x == 10 * 3.0 - 10
