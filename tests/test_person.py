"""A title plus a seal gap or a split line still yields the person's name."""

from ekisui.domain.session import Session
from ekisui.domain.types import Category, Settings

from factory import document_from_lines


def test_clerk_line_finds_ono_mina():
    text = "裁判所書記官　小野　美奈…"
    session = _session([text])
    group = _person(session, "小野")
    assert "美奈" in group.canonical
    assert "書記官" not in group.canonical
    assert group.hits[0].included
    surface = group.hits[0].hit.surface
    assert surface.index("小") < surface.index("奈")
    assert "書" not in surface


def test_seal_gap_between_surname_and_given_name():
    session = _session(["裁判所書記官　小野　○　美奈"])
    group = _person(session, "小野")
    assert "美奈" in group.canonical
    assert "書記官" not in group.canonical
    assert group.hits[0].included


def test_split_name_joins_the_next_short_line():
    session = _session(["裁判所書記官　小野", "美奈…"])
    group = _person(session, "小野")
    assert "美奈" in group.canonical
    assert "書" not in group.hits[0].hit.surface
    assert group.hits[0].included


def test_seal_gap_keeps_the_name_when_a_particle_follows():
    session = _session(["裁判所書記官　小野　○　美奈は出席した"])
    group = _person(session, "小野")
    assert "美奈" in group.canonical
    assert "書記官" not in group.canonical


def test_split_name_keeps_a_phone_on_the_first_line():
    session = _session(["裁判所書記官　小野　03-1234-5678", "美奈"])
    group = _person(session, "小野")
    assert "美奈" in group.canonical
    phones = [item for item in session.groups if item.category == Category.PHONE]
    assert phones and "03-1234-5678" in phones[0].canonical
    session.adjust_hit(group.hits[0].id, "right", 0)
    assert "美奈" in group.hits[0].hit.surface


def test_hiragana_given_name_is_not_a_person():
    session = _session(["申立人　山田たろう", "吉田 秀平"])
    people = [group.canonical for group in session.groups if group.category == Category.PERSON]
    assert not any("山田" in name or "たろう" in name for name in people)
    assert any("秀平" in name for name in people)


def _session(lines: list[str]) -> Session:
    session = Session(document_from_lines([lines]), Settings())
    session.suggest()
    return session


def _person(session: Session, needle: str):
    matches = [
        group
        for group in session.groups
        if group.category == Category.PERSON and needle in group.canonical
    ]
    assert len(matches) == 1, [group.canonical for group in session.groups]
    return matches[0]
