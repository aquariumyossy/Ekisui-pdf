from ekisui.domain.index import build_document_index
from ekisui.domain.match import search_pages
from ekisui.domain.normalize import load_confusables, strict_text
from ekisui.domain.types import MatchKind, Settings

from factory import document_from_lines


def _hits(pages, term, threshold=0.60):
    table = load_confusables()
    doc = document_from_lines(pages)
    return search_pages(build_document_index(doc, table), term, Settings(fuzzy_threshold=threshold), table)


def test_spaces_and_fullwidth_are_exact():
    hits = _hits([["株式会社 サンプル 商事", "電話０３-１２３４-５６７８"]], "株式会社サンプル商事")
    assert len(hits) == 1
    assert hits[0].kind == MatchKind.EXACT
    assert "サンプル" in hits[0].surface
    assert strict_text("０３") == "03"


def test_confusable_is_fuzzy_with_percent():
    hits = _hits([["原告株式会社サンフル商事の振込先"]], "株式会社サンプル商事")
    assert len(hits) == 1
    assert hits[0].kind == MatchKind.FUZZY
    assert hits[0].ocr_like
    assert round(hits[0].score * 100) == 90
    assert "「プ」→「フ」" in hits[0].explanation


def test_yamada_variant_is_75_percent():
    hits = _hits([["被告山田太朗は否認する"]], "山田太郎")
    assert len(hits) == 1
    assert hits[0].kind == MatchKind.FUZZY
    assert round(hits[0].score * 100) == 75
    assert "「郎」→「朗」" in hits[0].explanation


def test_short_term_rejects_unrelated_substitution():
    hits = _hits([["山川"]], "山田")
    assert hits == []


def test_short_term_allows_one_confusable():
    hits = _hits([["カ田"]], "力田")
    assert len(hits) == 1
    assert hits[0].kind == MatchKind.FUZZY


def test_threshold_blocks_weak_long_match():
    # 郎/朗 is a confusable, so it still matches after normalization.
    # A real one-character edit that is not in the table follows the slider.
    assert _hits([["山田太朗"]], "山田太郎", threshold=0.90)
    assert _hits([["山田太一"]], "山田太郎", threshold=0.90) == []
    weak = _hits([["山田太一"]], "山田太郎", threshold=0.60)
    assert len(weak) == 1
    assert weak[0].ocr_like is False
    assert round(weak[0].score * 100) == 75


def test_wrapped_lines_join_and_paragraphs_do_not():
    # Each half is below the 60% band on its own. Together they are the term.
    close = document_from_lines([["株式会社サ", "ンプル商事"]], gap=18.0)
    far = document_from_lines([["株式会社サ", "ンプル商事"]], gap=40.0)
    table = load_confusables()
    settings = Settings()
    close_hits = search_pages(build_document_index(close, table), "株式会社サンプル商事", settings, table)
    far_hits = search_pages(build_document_index(far, table), "株式会社サンプル商事", settings, table)
    assert len(close_hits) == 1
    assert close_hits[0].kind == MatchKind.EXACT
    assert far_hits == []


def test_ocr_spaced_name_is_exact():
    hits = _hits([["山 田 太 郎"]], "山田太郎")
    assert len(hits) == 1
    assert hits[0].kind == MatchKind.EXACT
    assert hits[0].surface.replace(" ", "") == "山田太郎"
