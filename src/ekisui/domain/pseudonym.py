from __future__ import annotations

_STEMS = "甲乙丙丁戊己庚辛壬癸"


def _letters(index: int) -> str:
    number = index
    chars: list[str] = []
    while True:
        chars.append(chr(ord("A") + number % 26))
        number = number // 26 - 1
        if number < 0:
            break
    return "".join(reversed(chars))


def company_name(index: int) -> str:
    return f"会社{_letters(index)}"


def person_name(index: int) -> str:
    if index < len(_STEMS):
        return f"個人{_STEMS[index]}"
    return f"個人{index + 1}"


def phrase_name(index: int) -> str:
    return f"呼称{_letters(index)}"
