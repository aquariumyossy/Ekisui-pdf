"""The bundled fictitious contract is an image-only scan, and the pipeline redacts it."""

import subprocess
import sys
from pathlib import Path

import pymupdf

from ekisui.domain.session import Session
from ekisui.domain.types import Category, SaveOptions, Settings
from ekisui.pdf.document import open_document, recognize
from ekisui.pdf.export import export_pdf, unique_destination
from ekisui.pdf.ocr_engine import PpOcrV5
from ekisui.pdf.verify import verify_pdf

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
SCAN = SAMPLES / "架空契約_スキャン.pdf"
TEXT = SAMPLES / "架空契約_テキスト.pdf"

EXPECTED = (
    "山田太郎",
    "佐藤花子",
    "株式会社架空商事",
    "株式会社架空工業",
    "株式会社架空銀行",
    "03-5555-0000",
    "090-5555-0001",
    "taro.yamada@example.jp",
    "hanako.kaku@example.com",
    "5555555",
    "000-0000",
)


def test_sample_script_matches_the_committed_pdfs(tmp_path: Path) -> None:
    subprocess.check_call([sys.executable, str(ROOT / "tools" / "make_sample.py"), str(tmp_path)])
    for name in (SCAN.name, TEXT.name):
        assert (tmp_path / name).read_bytes() == (SAMPLES / name).read_bytes()


def test_scan_is_image_only_and_small() -> None:
    total = SCAN.stat().st_size + TEXT.stat().st_size
    assert total < 2_000_000
    doc = pymupdf.open(SCAN)
    try:
        assert doc.page_count == 2
        assert all(not page.get_text().strip() for page in doc)
        assert all(page.get_images() for page in doc)
    finally:
        doc.close()
    opened = open_document(SCAN)
    assert all(page.kind.name == "SCANNED" for page in opened.pages)
    assert all(not page.lines for page in opened.pages)
    text = pymupdf.open(TEXT)
    try:
        body = text[0].get_text()
    finally:
        text.close()
    assert "サンプル・架空のデータです" in body
    assert "1丁目2番3号" in body
    assert "架空町1-2-3" in body


def test_scan_pipeline_redacts_the_fake_entities(tmp_path: Path) -> None:
    opened = open_document(SCAN)
    recognized = recognize(opened, Settings(), PpOcrV5(), tmp_path / "ocr")
    session = Session(recognized, Settings())
    session.suggest()
    found = {group.canonical for group in session.groups}
    missing = [item for item in EXPECTED if item not in found]
    assert not missing, missing
    tokyo = next(group for group in session.groups if "千代田区架空町" in group.canonical)
    osaka = next(group for group in session.groups if "架空市架空町" in group.canonical)
    assert {hit.hit.surface for hit in tokyo.hits} == {
        "東京都千代田区架空町1丁目2番3号",
        "東京都千代田区架空町1-2-3",
    }
    assert tokyo.pseudonym == "住所A"
    assert {hit.hit.surface for hit in osaka.hits} == {
        "大阪府架空市架空町1丁目4番5号",
        "大阪府架空市架空町1-4-5",
    }
    session.commit_redactions(tmp_path / "burn", False)
    dest = tmp_path / "架空契約_スキャン_Masked.pdf"
    export_pdf(
        session.document,
        session.groups,
        dest,
        SaveOptions(align_box_width=False, strip_metadata=True, export_log=False, export_replacement_table=False),
        session.settings,
        archived=session.committed,
        prior_boxes=session.burned_boxes,
    )
    report = verify_pdf(str(dest), session.committed, session.settings, session.table, True)
    assert report.passed, [(item.term, item.explanation) for item in report.leftovers]
    saved = pymupdf.open(dest)
    try:
        flat = "".join(page.get_text() for page in saved)
    finally:
        saved.close()
    for secret in ("山田太郎", "佐藤花子", "03-5555-0000", "5555555", "example.jp"):
        assert secret not in flat
    assert "サンプル・架空のデータです" in flat.replace(" ", "")


def test_save_beside_a_read_only_sample_in_a_user_folder(tmp_path: Path) -> None:
    install = tmp_path / "AppData" / "Local" / "ekisui-pdf" / "samples"
    install.mkdir(parents=True)
    sample = install / TEXT.name
    sample.write_bytes(TEXT.read_bytes())
    sample.chmod(0o444)
    dest = unique_destination(sample.with_name(sample.stem + "_Masked.pdf"))
    dest.write_bytes(b"%PDF-1.4 sample\n")
    assert dest.parent == install
    assert sample.read_bytes() == TEXT.read_bytes()
    assert dest.exists()


def test_installer_copies_samples_and_does_not_wipe_the_folder() -> None:
    raw = (ROOT / "installer" / "ekisui-pdf.iss").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    script = raw.decode("utf-8-sig")
    assert r'Source: "..\samples\架空契約_スキャン.pdf"; DestDir: "{app}\samples"' in script
    assert r'Source: "..\samples\架空契約_テキスト.pdf"; DestDir: "{app}\samples"' in script
    assert "UninstallDelete" not in script
    assert "AppId={{E4B7A1C2-6D58-4F0E-9A31-7C2E8B6D4F10}" in script
