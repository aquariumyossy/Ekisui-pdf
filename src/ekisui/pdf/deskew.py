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
