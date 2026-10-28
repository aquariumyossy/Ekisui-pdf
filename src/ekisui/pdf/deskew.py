from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class DeskewResult:
    image: np.ndarray
    rotation: int
    skew: float
    label: str | None


def correct_page(image: np.ndarray, enabled: bool) -> DeskewResult:
    if not enabled:
        return DeskewResult(image, 0, 0.0, None)
    rotation = quarter_turns(image)
    turned = apply_quarter(image, rotation)
    skew = estimate_skew(turned)
    corrected = rotate_bound(turned, skew) if abs(skew) >= 0.05 else turned
    return DeskewResult(corrected, rotation, skew, format_correction(rotation, skew))


def format_correction(rotation: int, skew: float) -> str | None:
    parts: list[str] = []
    turn = rotation % 360
    if turn:
        parts.append(f"{turn}°回転")
    if abs(skew) >= 0.3:
        sign = "+" if skew > 0 else "−"
        parts.append(f"{sign}{abs(skew):.1f}°")
    if not parts:
        return None
    return " ".join(parts)


def quarter_turns(image: np.ndarray) -> int:
    """Return 0, 90, or 270. 90 and 270 are counterclockwise degrees."""
    binary = _binary(image)
    horizontal = _projection_score(binary, axis=1)
    vertical = _projection_score(binary, axis=0)
    if horizontal >= vertical * 1.15:
        return 0
    if vertical < horizontal * 1.15:
        return 0
    ccw = np.rot90(binary, 1)
    cw = np.rot90(binary, 3)
    if _projection_score(ccw, axis=1) >= _projection_score(cw, axis=1):
        return 90
    return 270


def apply_quarter(image: np.ndarray, rotation: int) -> np.ndarray:
    turns = (rotation // 90) % 4
    if turns == 0:
        return image
    return np.ascontiguousarray(np.rot90(image, turns))


def estimate_skew(image: np.ndarray) -> float:
    """Degrees to rotate the image counterclockwise so text lines are horizontal."""
    binary = _binary(image, max_width=900)
    if binary.mean() < 1:
        return 0.0
    baseline = _score_at(binary, 0.0)
    best_angle = 0.0
    best_score = baseline
    angle = -8.0
    while angle <= 8.0:
        score = _score_at(binary, angle)
        if score > best_score:
            best_angle = angle
            best_score = score
        angle += 0.5
    refined = best_angle
    angle = best_angle - 0.6
    while angle <= best_angle + 0.6:
        score = _score_at(binary, angle)
        if score > best_score:
            refined = angle
            best_score = score
        angle += 0.1
    if best_score <= baseline * 1.01:
        return 0.0
    if abs(refined) < 0.3:
        return 0.0
    return round(refined, 2)


def rotate_bound(image: np.ndarray, angle: float) -> np.ndarray:
    if abs(angle) < 0.05:
        return image
    height, width = image.shape[:2]
    center = (width / 2, height / 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    bound_w = int(height * sin + width * cos)
    bound_h = int(height * cos + width * sin)
    matrix[0, 2] += bound_w / 2 - center[0]
    matrix[1, 2] += bound_h / 2 - center[1]
    return cv2.warpAffine(
        image,
        matrix,
        (bound_w, bound_h),
        flags=cv2.INTER_LINEAR,
        borderValue=(255, 255, 255),
    )


def map_page_rect(old, new, rect):
    """Move a rectangle from one reading of a page onto the next.

    Both readings are turns of the original PDF page: quarter turn, then skew,
    then 180° when the line model flips the image. A second OCR run undoes the
    previous turns before applying the new ones, so the box is not rotated twice.
    """
    from ekisui.domain.types import Rect

    source = _undo_page_rect(old, rect)
    mapped = _apply_page_rect(new, source, _source_size(old, new))
    return mapped.clip(Rect(0.0, 0.0, max(new.width, 1.0), max(new.height, 1.0)))


def _source_size(old, new) -> tuple[float, float]:
    if getattr(new, "source_width", 0) and getattr(new, "source_height", 0):
        return float(new.source_width), float(new.source_height)
    if getattr(old, "source_width", 0) and getattr(old, "source_height", 0):
        return float(old.source_width), float(old.source_height)
    if not _has_turn(old):
        return float(old.width), float(old.height)
    return float(new.width), float(new.height)


def _has_turn(page) -> bool:
    extra = (page.rotation - page.quarter) % 360
    return page.quarter % 360 != 0 or extra != 0 or abs(page.skew) >= 0.05


def _corners(rect, scale: float) -> list[tuple[float, float]]:
    return [
        (rect.x0 * scale, rect.y0 * scale),
        (rect.x1 * scale, rect.y0 * scale),
        (rect.x0 * scale, rect.y1 * scale),
        (rect.x1 * scale, rect.y1 * scale),
    ]


def _rect_from_pixels(points: list[tuple[float, float]], scale: float):
    from ekisui.domain.types import Rect

    xs = [point[0] / scale for point in points]
    ys = [point[1] / scale for point in points]
    return Rect(min(xs), min(ys), max(xs), max(ys))


def _apply_page_rect(page, rect, source_size: tuple[float, float]):
    scale = page.dpi / 72.0
    if scale <= 0 or not _has_turn(page):
        return rect
    width = float(round(source_size[0] * scale))
    height = float(round(source_size[1] * scale))
    corners = _corners(rect, scale)
    corners, width, height = _turn(corners, width, height, page.quarter)
    corners, width, height = _skew_points(corners, width, height, page.skew)
    extra = (page.rotation - page.quarter) % 360
    if extra == 180:
        corners, width, height = _turn(corners, width, height, 180)
    return _rect_from_pixels(corners, scale)


def _undo_page_rect(page, rect):
    if not _has_turn(page):
        return rect
    source_w = float(page.source_width or page.width)
    source_h = float(page.source_height or page.height)
    scale = page.dpi / 72.0
    if scale <= 0:
        return rect
    width = float(round(source_w * scale))
    height = float(round(source_h * scale))
    corners = _corners(rect, scale)
    turned, width, height = _turn(list(corners), width, height, page.quarter)
    skewed, bound_w, bound_h = _skew_points(turned, width, height, page.skew)
    extra = (page.rotation - page.quarter) % 360
    if extra == 180:
        # The 180° turn uses the post-skew canvas. Undo it before the skew.
        corners, _, _ = _turn(corners, bound_w, bound_h, 180)
    if abs(page.skew) >= 0.05:
        corners = _unskew_points(corners, width, height, page.skew)
    corners = _unturn(corners, float(round(source_w * scale)), float(round(source_h * scale)), page.quarter)
    del skewed
    return _rect_from_pixels(corners, scale)


def _turn(points: list[tuple[float, float]], width: float, height: float, quarter: int):
    turns = (quarter // 90) % 4
    if turns == 0:
        return points, width, height
    if turns == 1:
        return [(y, width - x) for x, y in points], height, width
    if turns == 2:
        return [(width - x, height - y) for x, y in points], width, height
    return [(height - y, x) for x, y in points], height, width


def _unturn(points: list[tuple[float, float]], width: float, height: float, quarter: int):
    """Inverse of ``_turn``. ``width`` and ``height`` are the size before the turn."""
    turns = (quarter // 90) % 4
    if turns == 0:
        return points
    if turns == 1:
        return [(width - y, x) for x, y in points]
    if turns == 2:
        return [(width - x, height - y) for x, y in points]
    return [(y, height - x) for x, y in points]


def _unskew_points(points: list[tuple[float, float]], width: float, height: float, angle: float):
    matrix, _bound_w, _bound_h = _skew_matrix(width, height, angle)
    inverse = cv2.invertAffineTransform(matrix)
    moved = []
    for x, y in points:
        moved.append(
            (
                inverse[0, 0] * x + inverse[0, 1] * y + inverse[0, 2],
                inverse[1, 0] * x + inverse[1, 1] * y + inverse[1, 2],
            )
        )
    return moved


def _skew_matrix(width: float, height: float, angle: float):
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cosine = abs(matrix[0, 0])
    sine = abs(matrix[0, 1])
    bound_w = float(int(height * sine + width * cosine))
    bound_h = float(int(height * cosine + width * sine))
    matrix[0, 2] += bound_w / 2.0 - center[0]
    matrix[1, 2] += bound_h / 2.0 - center[1]
    return matrix, bound_w, bound_h


def _skew_points(points: list[tuple[float, float]], width: float, height: float, angle: float):
    if abs(angle) < 0.05 or width < 1 or height < 1:
        return points, width, height
    matrix, bound_w, bound_h = _skew_matrix(width, height, angle)
    moved = []
    for x, y in points:
        moved.append(
            (
                matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2],
                matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2],
            )
        )
    return moved, bound_w, bound_h


def _binary(image: np.ndarray, max_width: int = 1200) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    height, width = gray.shape
    if width > max_width:
        scale = max_width / width
        gray = cv2.resize(gray, (max_width, max(1, int(height * scale))))
    _threshold, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary


def _projection_score(binary: np.ndarray, axis: int) -> float:
    return float(binary.sum(axis=axis).astype(np.float64).var())


def _score_at(binary: np.ndarray, angle: float) -> float:
    if abs(angle) < 1e-6:
        return _projection_score(binary, axis=1)
    height, width = binary.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    rotated = cv2.warpAffine(binary, matrix, (width, height), flags=cv2.INTER_NEAREST, borderValue=0)
    return _projection_score(rotated, axis=1)
