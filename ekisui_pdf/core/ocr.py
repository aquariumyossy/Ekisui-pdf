from __future__ import annotations

from pathlib import Path

from ekisui_pdf.core.errors import ModelNotFoundError
from ekisui_pdf.core.models import OcrLine, Rect
from ekisui_pdf.paths import models_dir

DET_FILENAME = "ch_PP-OCRv5_det_mobile.onnx"
REC_FILENAME = "ch_PP-OCRv5_rec_mobile.onnx"


def model_paths(directory: Path | None = None) -> tuple[Path, Path]:
    root = Path(directory) if directory is not None else models_dir()
    return root / DET_FILENAME, root / REC_FILENAME


def create_engine(directory: Path | None = None):
    """同梱ファイルだけを渡して RapidOCR を作る。model_path が無いと自動ダウンロードする。"""
    det_path, rec_path = model_paths(directory)
    missing = [path.name for path in (det_path, rec_path) if not path.is_file()]
    if missing:
        raise ModelNotFoundError(
            "OCRモデルが見つかりません: "
            + ", ".join(missing)
            + "。配布版ではインストーラに同梱されています。"
        )
    if not _is_local_file(det_path) or not _is_local_file(rec_path):
        raise ModelNotFoundError("OCRモデルはローカルファイルだけを使います。")

    from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR

    return RapidOCR(
        params={
            "Global.use_cls": False,
            "Global.log_level": "error",
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Det.lang_type": LangDet.CH,
            "Det.model_type": ModelType.MOBILE,
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.model_path": str(det_path),
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Rec.lang_type": LangRec.CH,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_path": str(rec_path),
        }
    )


def recognize_image(engine, image, *, page_index: int, zoom: float) -> list[OcrLine]:
    if not hasattr(image, "shape"):
        raise TypeError("OCRには画像配列だけを渡します。パスやURLは受け付けません。")
    result = engine(image)
    texts = tuple(result.txts or ())
    scores = tuple(result.scores or ())
    boxes = result.boxes
    if boxes is None or not texts:
        return []
    lines: list[OcrLine] = []
    for index, (text, score, box) in enumerate(zip(texts, scores, boxes)):
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        if zoom <= 0:
            raise ValueError("zoom は正の数です。")
        lines.append(
            OcrLine(
                page_index=page_index,
                text=str(text),
                rect=Rect(min(xs) / zoom, min(ys) / zoom, max(xs) / zoom, max(ys) / zoom),
                confidence=float(score),
                line_id=f"p{page_index}-l{index}",
            )
        )
    return lines


def render_page_bgr(page, dpi: int = 200):
    import numpy as np
    import pymupdf

    zoom = dpi / 72.0
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, colorspace=pymupdf.csRGB)
    array = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
    rgb = array[:, :, :3].copy()
    return rgb[:, :, ::-1].copy(), zoom


def _is_local_file(path: Path) -> bool:
    text = str(path)
    return path.is_file() and "://" not in text
