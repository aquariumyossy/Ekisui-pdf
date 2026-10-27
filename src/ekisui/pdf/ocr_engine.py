from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from ekisui.errors import ModelMissing
from ekisui.paths import model_dir


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float
    quad: tuple[tuple[float, float], ...]
    upside_down: bool


class PpOcrV5:
    """PP-OCRv5 mobile detection + Japanese-capable recognition on ONNX Runtime.

    The recognition model is ``ch_PP-OCRv5_rec_mobile``. PaddleOCR trains that
    checkpoint on simplified Chinese, traditional Chinese, English, and Japanese.
    """

    def __init__(self, directory: Path | None = None) -> None:
        root = directory or model_dir()
        det = root / "ch_PP-OCRv5_det_mobile.onnx"
        rec = root / "ch_PP-OCRv5_rec_mobile.onnx"
        cls = root / "ch_PP-LCNet_x0_25_textline_ori.onnx"
        keys = root / "ppocrv5_dict.txt"
        if not det.exists() or not rec.exists() or not cls.exists() or not keys.exists():
            raise ModelMissing(str(root))
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.enable_cpu_mem_arena = True
        self.det = ort.InferenceSession(str(det), options, providers=["CPUExecutionProvider"])
        self.rec = ort.InferenceSession(str(rec), options, providers=["CPUExecutionProvider"])
        self.cls = ort.InferenceSession(str(cls), options, providers=["CPUExecutionProvider"])
        chars = keys.read_text(encoding="utf-8").splitlines()
        # PaddleOCR CTC: blank is index 0, and a trailing space is added after the dict.
        self.chars = chars + [" "]
        self._det_name = self.det.get_inputs()[0].name
        self._rec_name = self.rec.get_inputs()[0].name
        self._cls_name = self.cls.get_inputs()[0].name

    def read(self, image: np.ndarray) -> list[OcrLine]:
        boxes = self._detect(image)
        lines: list[OcrLine] = []
        for quad, _score in boxes:
            crop = _crop(image, quad)
            if crop.size == 0:
                continue
            upside = self._is_upside_down(crop)
            if upside:
                crop = cv2.rotate(crop, cv2.ROTATE_180)
            text, confidence = self._recognize(crop)
            if not text.strip():
                continue
            lines.append(OcrLine(text=text, confidence=confidence, quad=_as_quad(quad), upside_down=upside))
        lines.sort(key=lambda line: (min(point[1] for point in line.quad), min(point[0] for point in line.quad)))
        return lines

    def read_page(self, image: np.ndarray) -> tuple[np.ndarray, list[OcrLine], int]:
        lines = self.read(image)
        if lines and sum(line.upside_down for line in lines) * 2 >= len(lines):
            flipped = np.ascontiguousarray(np.rot90(image, 2))
            return flipped, self.read(flipped), 180
        if not lines:
            flipped = np.ascontiguousarray(np.rot90(image, 2))
            retry = self.read(flipped)
            if retry:
                return flipped, retry, 180
        return image, lines, 0

    def _detect(self, image: np.ndarray) -> list[tuple[np.ndarray, float]]:
        original_h, original_w = image.shape[:2]
        limit = 960
        scale = min(1.0, limit / max(original_h, original_w))
        resized_h = max(32, int(original_h * scale + 31) // 32 * 32)
        resized_w = max(32, int(original_w * scale + 31) // 32 * 32)
        resized = cv2.resize(image, (resized_w, resized_h))
        blob = _normalize(resized)
        pred = self.det.run(None, {self._det_name: blob})[0]
        prob = pred[0, 0]
        bitmap = (prob > 0.3).astype(np.uint8) * 255
        contours, _hierarchy = cv2.findContours(bitmap, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        scale_x = original_w / resized_w
        scale_y = original_h / resized_h
        boxes: list[tuple[np.ndarray, float]] = []
        for contour in contours:
            if cv2.contourArea(contour) < 8:
                continue
            rect = cv2.minAreaRect(contour)
            box = cv2.boxPoints(rect)
            score = _box_score(prob, contour)
            if score < 0.4:
                continue
            box = _expand_box(box, 1.6)
            box[:, 0] *= scale_x
            box[:, 1] *= scale_y
            width = np.linalg.norm(box[0] - box[1])
            height = np.linalg.norm(box[1] - box[2])
            if min(width, height) < 6 or max(width, height) < 8:
                continue
            boxes.append((box, score))
        return boxes

    def _recognize(self, crop: np.ndarray) -> tuple[str, float]:
        image_h = 48
        height, width = crop.shape[:2]
        if height < 2 or width < 2:
            return "", 0.0
        resized_w = max(8, min(2000, int(image_h * width / height)))
        resized = cv2.resize(crop, (resized_w, image_h))
        blob = _normalize(resized)
        preds = self.rec.run(None, {self._rec_name: blob})[0][0]
        return _ctc_decode(preds, self.chars)

    def _is_upside_down(self, crop: np.ndarray) -> bool:
        resized = cv2.resize(crop, (160, 80))
        blob = _normalize(resized)
        output = self.cls.run(None, {self._cls_name: blob})[0][0]
        winner = int(np.argmax(output))
        return winner == 1 and float(output[winner]) >= 0.6


def _normalize(image: np.ndarray) -> np.ndarray:
    array = image.astype(np.float32) / 255.0
    array = (array - 0.5) / 0.5
    array = np.transpose(array, (2, 0, 1))[None]
    return array


def _ctc_decode(preds: np.ndarray, chars: list[str]) -> tuple[str, float]:
    text: list[str] = []
    confidences: list[float] = []
    previous = -1
    for step in preds:
        index = int(step.argmax())
        if index != 0 and index != previous and index - 1 < len(chars):
            text.append(chars[index - 1])
            confidences.append(float(step[index]))
        previous = index
    if not confidences:
        return "", 0.0
    return "".join(text), sum(confidences) / len(confidences)


def _box_score(prob: np.ndarray, contour: np.ndarray) -> float:
    mask = np.zeros_like(prob, dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 1, thickness=-1)
    values = prob[mask == 1]
    if values.size == 0:
        return 0.0
    return float(values.mean())


def _expand_box(box: np.ndarray, ratio: float) -> np.ndarray:
    rect = cv2.minAreaRect(box.astype(np.float32))
    (center_x, center_y), (width, height), angle = rect
    area = max(width * height, 1.0)
    perimeter = max(2 * (width + height), 1.0)
    distance = area * ratio / perimeter
    expanded = ((center_x, center_y), (width + distance * 2, height + distance * 2), angle)
    return cv2.boxPoints(expanded)


def _crop(image: np.ndarray, box: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    xs = np.clip(box[:, 0], 0, width - 1)
    ys = np.clip(box[:, 1], 0, height - 1)
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    if x1 <= x0 or y1 <= y0:
        return image[0:0, 0:0]
    return image[y0:y1, x0:x1]


def _as_quad(box: np.ndarray) -> tuple[tuple[float, float], ...]:
    return tuple((float(point[0]), float(point[1])) for point in box)
