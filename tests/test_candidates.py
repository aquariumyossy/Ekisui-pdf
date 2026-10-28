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


def test_unassigned_zero_numbers_are_phones():
    doc = document_from_lines([["電話00-1111-2222"], ["携帯000-2222-1111"], ["郵便番号〒000-0000"]])
    session = Session(doc, Settings())
    session.suggest()
    phones = {group.canonical for group in session.groups if group.category == Category.PHONE}
    assert phones == {"00-1111-2222", "000-2222-1111"}
    postals = [group for group in session.groups if group.category == Category.POSTAL]
    assert len(postals) == 1
    assert postals[0].canonical == "〒000-0000"
    assert len(postals[0].hits) == 1


def _companies(lines: list[str]) -> list[str]:
    doc = document_from_lines([lines], gap=29.0)
    session = Session(doc, Settings())
    session.suggest()
    return [group.canonical for group in session.groups if group.category == Category.COMPANY]


def test_a_finished_company_does_not_take_the_next_line():
    doc = document_from_lines(
        [["前文が続いて株式会社サンフル商事", "山田太朗", "前文が続いて株式会社サンプル商事"]],
        gap=29.0,
    )
    session = Session(doc, Settings())
    session.suggest()
    companies = [group.canonical for group in session.groups if group.category == Category.COMPANY]
    assert companies
    assert all("山田" not in name and "代表" not in name for name in companies), companies
    people = [group.canonical for group in session.groups if group.category == Category.PERSON]
    assert any("山田太朗" in name for name in people), people
    kept = _companies(["前文が続いて株式会社エクイスイ", "代表者は山田太郎であるとする。"])
    assert kept == ["株式会社エクイスイ"], kept
    kept = _companies(["前文が続いて株式会社エクイスイ", "担当は佐藤花子であるとする。"])
    assert kept == ["株式会社エクイスイ"], kept


def test_a_company_split_before_its_suffix_still_joins():
    assert "株式会社サンプル商事" in _companies(["甲は株式会社サンプル", "商事と契約した。"])
    assert "株式会社サンプル商事" in _companies(["前文が長く続いて行末の株式会社", "サンプル商事と契約した。"])
    assert "架空商事株式会社" in _companies(["甲は相当に長い商号である架空商事", "株式会社と本契約を締結する。"])
    assert "株式会社山田工業所" in _companies(["前文が長く続いて株式会社山田工業", "所と契約した。"])


def test_a_second_title_is_not_part_of_the_name():
    for line in ("原告訴訟代理人弁護士　架空花子", "原告訴訟代理人　弁護士　架空花子"):
        doc = document_from_lines([[line]])
        session = Session(doc, Settings())
        session.suggest()
        people = [group.canonical for group in session.groups if group.category == Category.PERSON]
        assert any("架空花子" in name for name in people), (line, people)
        assert all("弁護士" not in name and "訴訟" not in name for name in people), (line, people)


def test_suggest_does_not_merge_different_people():
    doc = document_from_lines([["佐藤一郎と佐藤二郎"]])
    table = load_confusables()
    groups = suggest(build_document_index(doc, table), Settings(), table, surnames=("佐藤",))
    canonicals = {group.canonical for group in groups}
    assert "佐藤一郎" in canonicals
    assert "佐藤二郎" in canonicals
