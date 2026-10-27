from __future__ import annotations

import socket
from pathlib import Path

import pytest

from ekisui_pdf.core.errors import ModelNotFoundError
from ekisui_pdf.core.ocr import DET_FILENAME, REC_FILENAME, create_engine, recognize_image
from ekisui_pdf.network_guard import NetworkDisabled, install_network_guard, uninstall_network_guard
from ekisui_pdf.paths import models_dir


def test_network_guard_blocks_and_restores():
    install_network_guard()
    try:
        with pytest.raises(NetworkDisabled):
            socket.create_connection(("127.0.0.1", 9), timeout=0.2)
        import requests

        with pytest.raises(NetworkDisabled):
            requests.get("https://example.com", timeout=1)
    finally:
        uninstall_network_guard()
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.close()


def test_engine_rejects_missing_models(tmp_path: Path):
    with pytest.raises(ModelNotFoundError):
        create_engine(tmp_path)


def test_engine_is_constructed_from_local_files_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    det = tmp_path / DET_FILENAME
    rec = tmp_path / REC_FILENAME
    det.write_bytes(b"not a real model")
    rec.write_bytes(b"not a real model")
    captured: dict = {}

    class FakeEngine:
        def __init__(self, params=None, **kwargs):
            captured["params"] = params

        def __call__(self, image):
            raise AssertionError("このテストでは推論しない")

    monkeypatch.setattr("rapidocr.RapidOCR", FakeEngine)
    create_engine(tmp_path)
    params = captured["params"]
    assert params["Det.model_path"] == str(det)
    assert params["Rec.model_path"] == str(rec)
    assert params["Global.use_cls"] is False
    assert params["Det.ocr_version"].value == "PP-OCRv5"
    assert "://" not in params["Det.model_path"]
    assert "://" not in params["Rec.model_path"]


def test_recognize_rejects_paths():
    with pytest.raises(TypeError):
        recognize_image(None, "https://example.com/a.png", page_index=0, zoom=1)


def test_manifest_matches_bundled_names():
    import json

    manifest = json.loads((models_dir() / "manifest.json").read_text(encoding="utf-8"))
    names = [item["filename"] for item in manifest["models"]]
    assert names == [DET_FILENAME, REC_FILENAME]


@pytest.mark.skipif(
    not (models_dir() / DET_FILENAME).is_file(),
    reason="models が未取得。scripts/fetch_models.py のあとで実行する",
)
def test_bundled_models_ocr_a_scanned_page_without_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def fail_download(*args, **kwargs):
        raise AssertionError("実行中にモデルをダウンロードしようとしました")

    monkeypatch.setattr("rapidocr.utils.download_file.DownloadFile.run", fail_download)
    import pymupdf

    from tests.factories import scanned_pdf

    pdf_path = tmp_path / "ocr.pdf"
    scanned_pdf(pdf_path, [["株式会社サンプルは山田太郎を被告とする。"]])
    document = pymupdf.open(pdf_path)
    try:
        from ekisui_pdf.core.ocr import render_page_bgr

        image, zoom = render_page_bgr(document[0], dpi=200)
        engine = create_engine(models_dir())
        lines = recognize_image(engine, image, page_index=0, zoom=zoom)
    finally:
        document.close()
    text = "".join(line.text for line in lines)
    assert "山田太郎" in text
    assert "株式会社" in text
