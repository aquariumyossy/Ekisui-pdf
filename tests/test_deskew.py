import numpy as np
from PIL import Image, ImageDraw

from ekisui.pdf.deskew import correct_page, estimate_skew, quarter_turns, rotate_bound


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
