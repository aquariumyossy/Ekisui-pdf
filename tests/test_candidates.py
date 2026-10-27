from ekisui.domain.candidates import load_surnames, suggest
from ekisui.domain.index import build_document_index
from ekisui.domain.normalize import load_confusables
from ekisui.domain.session import Session
from ekisui.domain.types import Action, Category, Settings

from factory import document_from_lines

SAMPLE = [
    "原告 株式会社サンプル商事",
    "被告 山田太郎（住所 東京都千代田区架空町1-2-3）は、",
    "連絡先は電話03-1234-5678、メール",
    "taro.yamada@example.jpであると主張する。",
    "口座番号1234567（〒100-0001）である。",
    "管理番号SMP2026A",
    "被告山田太朗は別件である。",
]


def test_surname_list_is_a_real_top_list():
    names = load_surnames()
    assert len(names) >= 400
    for required in ("佐藤", "鈴木", "高橋", "田中", "山田", "渡辺", "渡邊"):
        assert required in names


def test_auto_categories_and_defaults():
    doc = document_from_lines([SAMPLE])
    session = Session(doc, Settings())
    session.suggest()
    by_cat = {}
    for group in session.groups:
        by_cat.setdefault(group.category, []).append(group)
    assert Category.COMPANY in by_cat
    assert Category.PERSON in by_cat
    assert Category.PHONE in by_cat
    assert Category.EMAIL in by_cat
    assert Category.ACCOUNT in by_cat
    assert Category.POSTAL in by_cat
    assert Category.ADDRESS in by_cat
    assert Category.ALNUM in by_cat
    address = by_cat[Category.ADDRESS][0]
    assert "架空町1-2-3" in address.canonical
    assert address.action == Action.REPLACE
    assert address.pseudonym == "住所A"
    assert all(hit.included for hit in address.hits)
    company = by_cat[Category.COMPANY][0]
    assert company.pseudonym == "会社A"
    assert company.action.name == "REPLACE"
    person = next(group for group in by_cat[Category.PERSON] if "太郎" in group.canonical or "太朗" in group.canonical)
    assert person.pseudonym == "個人甲"
    phone = by_cat[Category.PHONE][0]
    assert phone.action.name == "BLACKOUT"
    assert phone.pseudonym is None
    alnum = by_cat[Category.ALNUM][0]
    assert alnum.canonical == "SMP2026A"
    assert all(not hit.included for hit in alnum.hits)
    # OCR-like 郎/朗 variant is attached and selected. A different person stays separate.
    surfaces = {hit.hit.surface for group in by_cat[Category.PERSON] for hit in group.hits}
    assert any("太朗" in surface for surface in surfaces)
    taro = next(group for group in by_cat[Category.PERSON] if "太郎" in group.canonical)
    assert any(hit.included and "太朗" in hit.hit.surface for hit in taro.hits)


def test_same_term_keeps_one_pseudonym_across_pages():
    doc = document_from_lines(
        [
            ["株式会社サンプル商事"],
            ["再掲 株式会社 サンプル 商事"],
        ]
    )
    session = Session(doc, Settings())
    session.suggest()
    companies = [group for group in session.groups if group.category == Category.COMPANY]
    assert len(companies) == 1
    pages = {hit.hit.page_index for hit in companies[0].hits}
    assert pages == {0, 1}
    assert companies[0].pseudonym == "会社A"


def test_phrase_search_raises_fuzzy_candidates():
    doc = document_from_lines([["株式会社サンフル商事は否認する"]])
    session = Session(doc, Settings())
    group = session.add_phrase("株式会社サンプル商事")
    assert group is not None
    assert group.hits[0].included
    assert group.hits[0].hit.kind.name == "FUZZY"
    assert group.pseudonym == "会社A"


def test_suggest_does_not_merge_different_people():
    doc = document_from_lines([["佐藤一郎と佐藤二郎"]])
    table = load_confusables()
    groups = suggest(build_document_index(doc, table), Settings(), table, surnames=("佐藤",))
    canonicals = {group.canonical for group in groups}
    assert "佐藤一郎" in canonicals
    assert "佐藤二郎" in canonicals
