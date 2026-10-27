from __future__ import annotations

from ekisui_pdf.core.models import OcrLine, Rect
from ekisui_pdf.core.variants import core_key, find_variants, group_surfaces, search_phrase


def _line(text: str, line_id: str = "l", page: int = 0) -> OcrLine:
    return OcrLine(page, text, Rect(0, 0, 300, 20), line_id=line_id)


def test_search_ignores_width_and_spaces():
    line = _line("原告は株式会社　ＡＢＣである。")
    hits = search_phrase([line], "ABC")
    assert len(hits) == 1
    assert "ＡＢＣ" in hits[0].surface
    assert hits[0].char_end > hits[0].char_start


def test_company_marker_variants_are_listed_for_review():
    lines = [
        _line("契約の相手は株式会社サンプルです", "a"),
        _line("㈱サンプルとも合意した", "b"),
        _line("サンプル株式会社が通知した", "c"),
        _line("関係ない文章", "d"),
    ]
    hits = find_variants(lines, "サンプル")
    surfaces = [surface for surface, _ in group_surfaces(hits)]
    assert "株式会社サンプル" in surfaces
    assert any("サンプル" in surface and "株" in surface for surface in surfaces)
    assert "関係ない文章" not in surfaces
    assert core_key("㈱サンプル") == "サンプル"
    assert core_key("株式会社サンプル") == "サンプル"


def test_search_does_not_drop_company_marker_from_query():
    line = _line("本文にサンプルとだけある")
    assert search_phrase([line], "株式会社サンプル") == []
    assert find_variants([line], "株式会社サンプル")
