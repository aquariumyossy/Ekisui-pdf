"""Prefecture spans: places are replaced, offices and bare names are blacked out."""

from ekisui.domain.address import address_key, find_addresses, load_address_bodies
from ekisui.domain.candidates import load_prefectures
from ekisui.domain.index import _cells
from ekisui.domain.session import Session
from ekisui.domain.types import (
    Action,
    Category,
    Document,
    Page,
    PageKind,
    Rect,
    Settings,
    TextLine,
    TextSource,
)

from factory import document_from_lines

HONSEKI = "本籍　東京都品川区東五反田２丁目１５番"


def test_body_words_stay_in_the_data_file():
    words = load_address_bodies()
    for required in ("知事", "警", "警察", "庁", "議会", "教育委員会", "公安委員会", "立"):
        assert required in words


def test_same_address_key_for_choume_and_hyphen():
    assert address_key("東京都品川区東五反田２丁目１５番") == address_key("東京都品川区東五反田2-15")
    assert address_key("東京都千代田区二番町3番地") != address_key("東京都品川区")


def test_finder_kinds():
    prefectures = load_prefectures()
    bodies = load_address_bodies()
    place = find_addresses(HONSEKI, prefectures, bodies)
    assert place == [(HONSEKI.index("東"), len(HONSEKI), "place")]
    governor = find_addresses("東京都知事は中央区に住む", prefectures, bodies)
    assert governor == [(0, len("東京都知事"), "body")]
    police = find_addresses("大阪府警へ照会", prefectures, bodies)
    assert police == [(0, len("大阪府警"), "body")]
    hospital = find_addresses("東京都立病院に入院", prefectures, bodies)
    assert hospital[0][2] == "body"
    assert hospital[0][1] == len("東京都立病院")
    tachikawa = find_addresses("東京都立川市砂川", prefectures, bodies)
    assert tachikawa[0][2] == "place"
    assert tachikawa[0][1] >= len("東京都立川市")
    bare = find_addresses("東京都と協定した", prefectures, bodies)
    assert bare == [(0, len("東京都"), "other")]


def test_sample_and_places_are_prechecked_replacements():
    lines = [
        HONSEKI,
        "送付先 東京都千代田区二番町3番地",
        "現住所 東京都大田区東六郷1丁目2番3号",
        "所在 東京都品川区",
        "建物 東京都品川区東五反田２丁目１５番サンプルマンション101号室",
        "北海道上川郡東川町",
        "京都府京都市左京区吉田",
        "東京都立川市栄町",
    ]
    groups = _address_groups(lines)
    honseki = next(group for group in groups if group.canonical == "東京都品川区東五反田２丁目１５番")
    assert "１５番" in honseki.canonical
    assert "籍" not in honseki.canonical
    assert honseki.action == Action.REPLACE
    assert honseki.pseudonym == "住所A"
    assert honseki.hits[0].included
    nibanchou = _one(groups, "二番町")
    assert "3番地" in nibanchou.canonical
    assert nibanchou.action == Action.REPLACE
    rokugou = _one(groups, "東六郷")
    assert "1丁目" in rokugou.canonical
    assert rokugou.action == Action.REPLACE
    shinagawa = next(group for group in groups if group.canonical == "東京都品川区")
    assert shinagawa.canonical == "東京都品川区"
    assert shinagawa.action == Action.REPLACE
    building = _one(groups, "マンション")
    assert "101号室" in building.canonical
    assert building.action == Action.REPLACE
    hokkaido = _one(groups, "上川郡")
    assert hokkaido.action == Action.REPLACE
    kyoto = _one(groups, "左京区")
    assert kyoto.action == Action.REPLACE
    tachikawa = _one(groups, "立川市")
    assert tachikawa.action == Action.REPLACE
    letters = [group.pseudonym for group in groups if group.action == Action.REPLACE]
    assert letters[0] == "住所A"
    assert len(letters) == len(set(letters))


def test_two_notations_share_one_pseudonym_and_another_address_is_next():
    session = _session(
        [
            "甲は東京都品川区東五反田２丁目１５番に住む。",
            "乙は東京都大田区東六郷1丁目2番に住む。",
            "甲の登記は東京都品川区東五反田2-15。",
        ]
    )
    groups = [group for group in session.groups if group.category == Category.ADDRESS]
    gotanda = [group for group in groups if "五反田" in group.canonical]
    assert len(gotanda) == 1
    assert gotanda[0].pseudonym == "住所A"
    assert gotanda[0].action == Action.REPLACE
    surfaces = {hit.hit.surface for hit in gotanda[0].hits}
    assert any("１５番" in surface for surface in surfaces)
    assert any("2-15" in surface for surface in surfaces)
    assert all(hit.included for hit in gotanda[0].hits)
    ota = _one(groups, "東六郷")
    assert ota.pseudonym == "住所B"
    assert ota.action == Action.REPLACE


def test_offices_and_bare_prefectures_are_prechecked_blackouts():
    session = _session(
        [
            "東京都知事の印",
            "大阪府警へ照会する。",
            "東京都立病院に入院した。",
            "東京都と協定した。",
            "居住地は東京都品川区東五反田２丁目１５番。",
        ]
    )
    groups = [group for group in session.groups if group.category == Category.ADDRESS]
    governor = _one(groups, "知事")
    assert governor.canonical == "東京都知事"
    assert governor.action == Action.BLACKOUT
    assert governor.pseudonym is None
    assert governor.hits[0].included
    police = _one(groups, "大阪府警")
    assert police.canonical == "大阪府警"
    assert police.action == Action.BLACKOUT
    assert police.pseudonym is None
    assert police.hits[0].included
    hospital = _one(groups, "立病院")
    assert hospital.canonical == "東京都立病院"
    assert "入院" not in hospital.canonical
    assert hospital.action == Action.BLACKOUT
    assert hospital.pseudonym is None
    assert hospital.hits[0].included
    bare = next(group for group in groups if group.canonical == "東京都")
    assert bare.action == Action.BLACKOUT
    assert bare.pseudonym is None
    assert bare.hits[0].included
    assert "と" not in bare.canonical
    place = _one(groups, "五反田")
    assert "１５番" in place.canonical
    assert place.action == Action.REPLACE
    assert place.pseudonym == "住所A"
    session.renumber()
    assert bare.pseudonym is None
    assert governor.pseudonym is None
    assert place.pseudonym == "住所A"


def test_honseki_box_covers_higashi_through_ban():
    for boxes in (True, False):
        text = HONSEKI
        session = Session(_document(text, boxes), Settings())
        session.suggest()
        group = next(item for item in session.groups if item.category == Category.ADDRESS)
        assert "１５番" in group.canonical
        assert "籍" not in group.canonical
        hit = group.hits[0].hit
        cells = _cells(session.document.pages[0].lines[0])
        east = text.index("東")
        ban = text.rindex("番")
        seki = text.index("籍")
        space = text.index("\u3000")
        assert hit.bbox.contains(*cells[east].center())
        assert hit.bbox.contains(*cells[ban].center())
        assert not hit.bbox.contains(*cells[seki].center())
        assert not hit.bbox.contains(*cells[space].center())
        assert hit.bbox.x0 > cells[seki].x1


def test_fullwidth_neighbours_stay_outside_the_box():
    cases = [
        ("前　０３－１２３４－５６７８", Category.PHONE, "０３"),
        ("前　〒１００－０００１", Category.POSTAL, "１００"),
        ("記号　ＡＢＣ１２３です", Category.ALNUM, "ＡＢＣ"),
        ("紹介　山田　太郎です", Category.PERSON, "山田"),
    ]
    for text, category, needle in cases:
        session = Session(_document(text, with_chars=False), Settings())
        session.suggest()
        group = next(item for item in session.groups if item.category == category and needle in item.canonical)
        hit = group.hits[0].hit
        line = session.document.pages[0].lines[0]
        cells = _cells(line)
        start = line.text.find(hit.surface)
        assert start > 0
        before = start - 1
        while before > 0 and line.text[before].isspace():
            before -= 1
        assert not hit.bbox.contains(*cells[before].center())
        assert hit.bbox.x0 > cells[before].x1 - 1
        first = start
        while line.text[first].isspace():
            first += 1
        last = start + len(hit.surface) - 1
        while line.text[last].isspace():
            last -= 1
        assert hit.bbox.contains(*cells[first].center())
        assert hit.bbox.contains(*cells[last].center())


def _session(lines: list[str]) -> Session:
    session = Session(document_from_lines([lines]), Settings())
    session.suggest()
    return session


def _address_groups(lines: list[str]):
    return [group for group in _session(lines).groups if group.category == Category.ADDRESS]


def _one(groups, needle: str):
    matches = [group for group in groups if needle in group.canonical]
    assert len(matches) == 1, [(group.canonical, group.action.name) for group in groups]
    return matches[0]


def _document(text: str, with_chars: bool) -> Document:
    width = 12.0
    chars = tuple(Rect(index * width, 80, (index + 1) * width, 96) for index in range(len(text)))
    line = TextLine(
        id="p0l0",
        page_index=0,
        text=text,
        bbox=Rect(0, 80, width * len(text), 96),
        confidence=1.0,
        source=TextSource.NATIVE,
        chars=chars if with_chars else (),
    )
    page = Page(
        index=0,
        width=800,
        height=400,
        kind=PageKind.NATIVE,
        lines=(line,),
        source_index=0,
    )
    return Document(source_path="memory.pdf", pages=(page,))
