import numpy as np
from PIL import Image, ImageDraw

from ekisui.domain.types import Page, PageKind, Rect
from ekisui.pdf.deskew import correct_page, estimate_skew, map_page_rect, quarter_turns, rotate_bound


def _bars(width=900, height=500) -> np.ndarray:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for y in range(40, height - 40, 36):
        draw.rectangle((30, y, width - 30, y + 8), fill="black")
    return np.array(image)


def test_deskew_corrects_a_known_angle():
    tilted = rotate_bound(_bars(), 3.0)
    angle = estimate_skew(tilted)
    assert abs(abs(angle) - 3.0) < 0.45
    corrected = rotate_bound(tilted, angle)
    assert abs(estimate_skew(corrected)) < 0.35


def test_quarter_turn_restores_horizontal_text():
    original = _bars()
    turned = np.ascontiguousarray(np.rot90(original, 1))
    rotation = quarter_turns(turned)
    assert rotation in {90, 270}
    result = correct_page(turned, enabled=True)
    assert result.rotation in {90, 270}
    assert result.label is not None
    assert "回転" in result.label
    assert result.image.shape[1] > result.image.shape[0]


def test_straight_page_has_no_correction_label():
    result = correct_page(_bars(), enabled=True)
    assert result.label is None
    assert result.rotation == 0
    assert abs(result.skew) < 0.3


def test_deskew_can_be_disabled():
    tilted = rotate_bound(_bars(), 3.0)
    result = correct_page(tilted, enabled=False)
    assert result.label is None
    assert result.image.shape == tilted.shape


def _red_bbox(image: np.ndarray) -> Rect:
    red = (image[:, :, 0] > 150) & (image[:, :, 1] < 80) & (image[:, :, 2] < 80)
    ys, xs = np.where(red)
    assert len(xs) > 0
    return Rect(float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1))


def _iou(left: Rect, right: Rect) -> float:
    overlap = left.intersection(right)
    if overlap is None:
        return 0.0
    return overlap.area() / (left.area() + right.area() - overlap.area())


def test_mapped_rect_follows_quarter_turn_and_skew():
    image = np.full((200, 400, 3), 255, np.uint8)
    image[40:80, 50:120] = (200, 0, 0)
    turned = np.ascontiguousarray(np.rot90(image, 1))
    skewed = rotate_bound(turned, 4.0)
    old = Page(index=0, width=400, height=200, kind=PageKind.SCANNED, lines=(), dpi=72)
    new = Page(
        index=0,
        width=float(skewed.shape[1]),
        height=float(skewed.shape[0]),
        kind=PageKind.SCANNED,
        lines=(),
        dpi=72,
        rotation=90,
        quarter=90,
        skew=4.0,
    )
    mapped = map_page_rect(old, new, Rect(50, 40, 120, 80))
    assert _iou(mapped, _red_bbox(skewed)) > 0.8
    # A second reading must undo the first turn instead of rotating the box again.
    mid = Page(
        index=0,
        width=float(skewed.shape[1]),
        height=float(skewed.shape[0]),
        kind=PageKind.SCANNED,
        lines=(),
        dpi=72,
        rotation=90,
        quarter=90,
        skew=4.0,
        source_width=400,
        source_height=200,
    )
    plain = Page(
        index=0,
        width=400,
        height=200,
        kind=PageKind.SCANNED,
        lines=(),
        dpi=72,
        source_width=400,
        source_height=200,
    )
    restored = map_page_rect(mid, plain, mapped)
    original = Rect(50, 40, 120, 80)
    # The stored box is the upright bound of the rotated quad, so the inverse
    # is slightly larger. Its center stays on the original rectangle.
    assert restored.x0 <= original.x0 + 1
    assert restored.y0 <= original.y0 + 1
    assert restored.x1 >= original.x1 - 1
    assert restored.y1 >= original.y1 - 1
    assert abs((restored.x0 + restored.x1) / 2 - (original.x0 + original.x1) / 2) < 1.5
    assert abs((restored.y0 + restored.y1) / 2 - (original.y0 + original.y1) / 2) < 1.5
