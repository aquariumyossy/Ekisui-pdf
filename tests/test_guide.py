"""The end-user guide keeps every safety caution, and the installer ships it."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render_guide(markdown: str) -> str:
    path = ROOT / "tools" / "guide_html.py"
    spec = importlib.util.spec_from_file_location("guide_html", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render_guide(markdown)

# Plain-language cautions. Each one is a place a person can leave something visible.
CAUTIONS = (
    "消し忘れることが、いちばん危険です",
    "消した語句は見つかりませんでした",
    "縦書き",
    "山田たろう",
    "行をまたいで",
    "半角カタカナ",
    "小さい文字",
    "英字を含む3文字以上",
    "フとプ",
    "都道府県",
    "長い名前の枠は縮みません",
    "手で枠を縮めた",
    "画像の中の文字",
    "ファクス",
    "見えない文字",
    "文字を読む前には保存できません",
    "権利管理（IRM）",
    "Word 自身の更新確認",
    "割り当て済みドライブ（Z: など）",
    "開かずに止まります",
    "取りには行きません",
    "HTML や RTF",
    "リンクは開きません",
    "マクロは実行しません",
    "元のファイルは上書きしません",
    "元の Word ファイルは変更しません",
)

# The developer section must keep the technical wording, not a shorter paraphrase.
TECHNICAL = (
    "INCLUDEPICTURE、INCLUDETEXT、DDE、添付ひな形、差し込み印刷",
    "クリック用のハイパーリンクは開きません",
    "HTML や RTF は変換しません",
    "権利管理（IRM）は、ファイルから分かるときは Word を起動せずに止めます",
    "ネットワーク上の Normal.dotm",
    "画像の中の文字をもう一度 OCR して探す処理ではありません",
    "ページ面積の約6割以上を、4千画素以上の画像",
    "複合機の見えない文字層は残しません",
    "OCR の前に保存しようとすると、読み取ってから保存するよう止めます",
    "8文字以上の語句の前半と後半",
    "半角カタカナの濁点（ﾀﾞ など）",
    "長辺を960ピクセル",
    "山田たろう",
    "別の段や表の隣のマス、空行のあとにはつなぎません",
    "英字を1字以上含む3文字以上",
    "フとプ",
    "建物名まで枠に入ることがあります",
    "長い名前の枠は短くなりません",
)

IMAGES = ("01-open.png", "02-ocr.png", "03-mask.png", "04-confirm.png", "05-save.png")


def test_guide_keeps_cautions_and_matches_html() -> None:
    guide = (ROOT / "docs" / "使い方.md").read_text(encoding="utf-8")
    html = (ROOT / "docs" / "使い方.html").read_text(encoding="utf-8")
    assert html == render_guide(guide)
    assert "<code>samples</code>" in html
    assert "<code>架空契約_スキャン.pdf</code>" in html
    assert "<code>名前_Masked.pdf</code>" in html
    assert "`" not in html
    for phrase in CAUTIONS:
        assert phrase in guide
        assert phrase in html
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "[使い方ガイド](docs/使い方.md)" in readme
    assert "## 開発者向け" in readme
    for phrase in TECHNICAL:
        assert phrase in readme


def test_installer_ships_the_guide_as_utf8() -> None:
    raw = (ROOT / "installer" / "ekisui-pdf.iss").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    script = raw.decode("utf-8-sig")
    assert "AppId={{E4B7A1C2-6D58-4F0E-9A31-7C2E8B6D4F10}" in script
    assert '#define MyAppVersion "1.0.0"' in script
    assert r'Source: "..\docs\使い方.md"' in script
    assert r'Source: "..\docs\使い方.html"' in script
    for name in IMAGES:
        assert rf'Source: "..\docs\images\{name}"' in script
    assert "autoprograms" in script
    assert "使い方" not in script.split("[Icons]", 1)[1].split("[Run]", 1)[0]


def test_guide_screenshots_are_legible() -> None:
    for name in IMAGES:
        path = ROOT / "docs" / "images" / name
        data = path.read_bytes()
        assert data[1:4] == b"PNG"
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        assert (width, height) == (1280, 800)
        assert path.stat().st_size > 50_000
