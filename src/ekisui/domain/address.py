"""Prefecture-based address spans and a key that equates 丁目/番 with hyphens."""

from __future__ import annotations

import re

from ekisui.domain.normalize import strict_text
from ekisui.paths import resource_path

_MARKERS = ("振興局", "市", "区", "町", "村", "郡", "島")
_PUNCT = set("、。，．）)」』」")
_HYPHEN = set("-－ー−‐‑")
_STOP = ("において", "の住所")
_AFTER_SPACE = (
    "被告",
    "原告",
    "申請人",
    "相手方",
    "申立人",
    "弁護士",
    "電話",
    "メール",
    "生年月日",
    "本籍",
    "において",
    "の住所",
)
_BUILDING = ("号室", "マンション", "アパート", "ビル", "ハイツ", "コーポ", "荘", "棟", "階")


def load_address_bodies() -> tuple[str, ...]:
    """Public-body words used to choose blackout, not to drop the candidate."""
    return _load_word_list("address_exclude.txt")


def load_address_excludes() -> tuple[str, ...]:
    """Older name. The list classifies; it does not exclude."""
    return load_address_bodies()


def _load_word_list(name: str) -> tuple[str, ...]:
    text = resource_path(name).read_text(encoding="utf-8")
    words = []
    seen = set()
    for line in text.splitlines():
        word = line.strip()
        if not word or word.startswith("#") or word in seen:
            continue
        seen.add(word)
        words.append(word)
    words.sort(key=len, reverse=True)
    return tuple(words)


def address_key(text: str) -> str:
    """Same place written with 丁目/番/号 or with hyphens shares one key."""
    folded = strict_text(text)
    folded = re.sub(r"[－ー−‐‑]", "-", folded)
    folded = re.sub(r"(\d+)丁目(\d+)(?:番地|番)(\d+)号", r"\1-\2-\3", folded)
    folded = re.sub(r"(\d+)丁目(\d+)(?:番地|番)", r"\1-\2", folded)
    folded = re.sub(r"(\d+)(?:番地|番)(\d+)号", r"\1-\2", folded)
    folded = re.sub(r"(\d+)丁目", r"\1-", folded)
    folded = re.sub(r"(\d+)番地", r"\1-", folded)
    folded = re.sub(r"(\d+)番", r"\1-", folded)
    folded = re.sub(r"(\d+)号室", r"\1", folded)
    folded = re.sub(r"(\d+)号", r"\1-", folded)
    folded = re.sub(r"-{2,}", "-", folded).strip("-")
    return folded


def find_addresses(
    text: str,
    prefectures: tuple[str, ...],
    bodies: tuple[str, ...],
) -> list[tuple[int, int, str]]:
    """Every prefecture starts a candidate. The kind is place, body, or other.

    place: municipality in the next few characters, or 立 immediately before one
    (立川市). The span runs through the rest of the address.
    body: a public-body word such as 知事 or 警. The span is the prefecture plus
    that word. 立 also takes a contiguous facility name (東京都立病院).
    other: the prefecture alone, for example 東京都と. Still a candidate.
    """
    found: list[tuple[int, int, str]] = []
    index = 0
    while index < len(text):
        name = _prefecture_at(text, index, prefectures)
        if name is None:
            index += 1
            continue
        after = index + len(name)
        kind, end = _classify_and_end(text, after, bodies, prefectures)
        while end > after and text[end - 1].isspace():
            end -= 1
        if end <= index:
            index = after
            continue
        found.append((index, end, kind))
        index = max(end, after)
    return found


def _prefecture_at(text: str, index: int, prefectures: tuple[str, ...]) -> str | None:
    for name in prefectures:
        if text.startswith(name, index):
            return name
    return None


def _classify_and_end(
    text: str,
    after: int,
    bodies: tuple[str, ...],
    prefectures: tuple[str, ...],
) -> tuple[str, int]:
    cursor = after
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    for word in bodies:
        if not text.startswith(word, cursor):
            continue
        # 立川市 is a municipality. 立病院 is a metropolitan facility.
        if word == "立" and _has_marker(text[cursor : cursor + 8]):
            return "place", _extend(text, after, prefectures)
        end = cursor + len(word)
        if word == "立":
            end = _extend(text, end, prefectures)
        return "body", end
    # Only the characters that can still be a municipality. 東京都と stops here,
    # even when another address follows in the same sentence.
    if _has_marker(_address_prefix(text, cursor, 12)):
        return "place", _extend(text, after, prefectures)
    return "other", after


def _address_prefix(text: str, start: int, limit: int) -> str:
    chunk: list[str] = []
    index = start
    while index < len(text) and len(chunk) < limit:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if not _address_char(char):
            break
        chunk.append(char)
        index += 1
    return "".join(chunk)


def _has_marker(text: str) -> bool:
    return any(marker in text for marker in _MARKERS)


def _extend(text: str, start: int, prefectures: tuple[str, ...]) -> int:
    index = start
    limit = len(text)
    while index < limit:
        if index > start and _prefecture_at(text, index, prefectures):
            break
        if any(text.startswith(word, index) for word in _STOP):
            break
        char = text[index]
        if char in _PUNCT or char == "で":
            break
        if char.isspace():
            nxt = index
            while nxt < limit and text[nxt].isspace():
                nxt += 1
            if not _continues(text, nxt):
                break
            index = nxt
            continue
        if _address_char(char):
            index += 1
            continue
        break
    return index


def _continues(text: str, index: int) -> bool:
    if index >= len(text):
        return False
    if any(text.startswith(word, index) for word in _AFTER_SPACE):
        return False
    char = text[index]
    if char in _PUNCT or char == "で" or _hiragana(char):
        return False
    end = index
    while end < len(text) and not text[end].isspace() and text[end] not in _PUNCT:
        end += 1
    chunk = text[index:end]
    if not chunk or len(chunk) > 24:
        return False
    if any(mark in chunk for mark in _BUILDING):
        return True
    if any(ch.isdigit() or ch in _HYPHEN for ch in chunk):
        return True
    if any(marker in chunk for marker in _MARKERS):
        return True
    return all(_address_char(ch) for ch in chunk)


def _address_char(char: str) -> bool:
    if char.isdigit() or char in _HYPHEN:
        return True
    if _hiragana(char):
        return False
    code = ord(char)
    if 0x4E00 <= code <= 0x9FFF or 0x30A0 <= code <= 0x30FF:
        return True
    if 0xFF10 <= code <= 0xFF19 or 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A:
        return True
    return char.isascii() and char.isalnum()


def _hiragana(char: str) -> bool:
    return "ぁ" <= char <= "ん"
