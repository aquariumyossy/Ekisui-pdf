"""Remove external Word targets before Microsoft Word can open them.

Word fetches linked images, INCLUDETEXT, and attached templates while it
opens a file. The .docx package is rewritten first, so those addresses are
gone before Word starts. A binary .doc cannot be rewritten safely; when it
already contains such a target, conversion stops instead of launching Word.
"""

from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote
from ekisui.errors import WordConvertError

_EXTERNAL = "この Word 文書は、外部の画像や文書、ひな形を参照しています。通信せずには開けないため、開くのをやめました。"
_IRM = "この Word 文書は権利管理（IRM）で保護されています。確認のために外部へ接続する可能性があるため、開くのをやめました。"
_IRM_MARKERS = (
    b"DRMEncryptedTransform",
    b"Microsoft.Metadata.DRMTransform",
    b"DRMContent",
)

def external_reference_message() -> str:
    return _EXTERNAL


def irm_message() -> str:
    return _IRM


def is_remote(target: str) -> bool:
    """True when a path or URL is not on this machine."""
    text = unquote((target or "").strip().strip('"').strip("'"))
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith(("http://", "https://", "ftp://", "ftps://", "sftp://")):
        return True
    if text.startswith("\\\\") or text.startswith("//"):
        return True
    if lowered.startswith("file:"):
        after = text[5:]
        if after.startswith("\\\\"):
            return True
        slashes = len(after) - len(after.lstrip("/"))
        rest = after.lstrip("/")
        if re.match(r"^[A-Za-z]:[\\/]", rest) or rest.lower().startswith(("localhost", "127.0.0.1")):
            return False
        # file:////server/share and file://server/share are UNC. file:///C:/ is local.
        if slashes >= 4 or slashes == 2:
            return bool(rest)
        return False
    return False


def contains_remote(text: str) -> bool:
    """True when a field instruction or path mentions a remote target."""
    if not text:
        return False
    decoded = unquote(text)
    if is_remote(decoded.strip().strip('"').strip("'")):
        return True
    lowered = decoded.lower()
    if any(token in lowered for token in ("http://", "https://", "ftp://", "ftps://", "sftp://")):
        return True
    if re.search(r"(?<![A-Za-z0-9:])\\\\", decoded):
        return True
    if re.search(r"(?<!:)//[A-Za-z0-9_.$-]+/", decoded):
        return True
    if "file:////" in lowered or re.search(r"file://[^/]", lowered):
        return True
    return False


def looks_like_irm(path: Path) -> bool:
    needles = list(_IRM_MARKERS)
    for marker in _IRM_MARKERS:
        needles.append(marker.decode("ascii").encode("utf-16-le"))
    overlap = max(len(item) for item in needles) - 1
    with path.open("rb") as handle:
        previous = b""
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return False
            data = previous + chunk
            if any(needle in data for needle in needles):
                return True
            previous = data[-overlap:] if overlap else b""


def doc_has_remote_fields(path: Path) -> bool:
    """Binary .doc: stop before Word if a field or template path leaves the PC."""
    with path.open("rb") as handle:
        data = handle.read()
    texts = [data.decode("latin-1", errors="ignore")]
    if len(data) >= 2:
        texts.append(data.decode("utf-16-le", errors="ignore"))
        texts.append(data[1:].decode("utf-16-le", errors="ignore"))
    return any(_text_has_remote_word_target(text) for text in texts)


def neutralize_docx(source: Path, dest: Path) -> None:
    """Write a copy with remote fetch targets removed. The original stays put."""
    try:
        with zipfile.ZipFile(source) as archive:
            files = {info.filename: archive.read(info.filename) for info in archive.infolist() if not info.is_dir()}
    except zipfile.BadZipFile as exc:
        raise WordConvertError(_EXTERNAL) from exc
    if not any(_part_fetches(name, data) for name, data in files.items()):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
        return
    rewritten: dict[str, bytes] = {}
    dropped_by_part: dict[str, set[str]] = {}
    for name, data in files.items():
        if name.lower().endswith(".rels"):
            try:
                xml, ids = _rewrite_relationships(data)
            except WordConvertError:
                raise
            except Exception as exc:
                raise WordConvertError(_EXTERNAL) from exc
            part = _part_for_relationships(name)
            if part and ids:
                dropped_by_part.setdefault(part, set()).update(ids)
            rewritten[name] = xml
        else:
            rewritten[name] = data
    for name, data in list(rewritten.items()):
        if _is_markup(name) and not name.lower().endswith(".rels"):
            try:
                rewritten[name] = _rewrite_document_part(data, dropped_by_part.get(name, set()))
            except WordConvertError:
                raise
            except Exception as exc:
                raise WordConvertError(_EXTERNAL) from exc
    for name, data in rewritten.items():
        lower = name.lower()
        if lower.endswith((".xml", ".rels", ".htm", ".html")) and _markup_fetches(
            data.decode("utf-8", errors="replace"), lower.endswith(".rels")
        ):
            raise WordConvertError(_EXTERNAL)
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".partial")
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in rewritten.items():
                archive.writestr(name, data)
        partial.replace(dest)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _text_has_remote_word_target(text: str) -> bool:
    for match in re.finditer(
        r"\x13\s*(INCLUDEPICTURE|INCLUDETEXT|DDEAUTO|DATABASE|IMPORT|DDE|LINK)\b.{0,600}",
        text,
        re.IGNORECASE,
    ):
        if contains_remote(match.group(0)):
            return True
    upper = text.upper()
    for name in ("INCLUDEPICTURE", "INCLUDETEXT", "DDEAUTO"):
        start = 0
        while True:
            index = upper.find(name, start)
            if index < 0:
                break
            if contains_remote(text[index : index + 800]):
                return True
            start = index + len(name)
    if re.search(
        r"(?:\\\\|//|file:////)[^\x00\r\n\"<>|]{0,300}?\.(?:dot|dotx|dotm)\b",
        text,
        re.IGNORECASE,
    ):
        return True
    if re.search(r"https?://[^\s\"'<>]{0,240}?\.(?:dot|dotx|dotm)\b", text, re.IGNORECASE):
        return True
    return False


def _part_fetches(name: str, data: bytes) -> bool:
    if not _is_markup(name):
        return False
    return _markup_fetches(data.decode("utf-8", errors="replace"), name.lower().endswith(".rels"))


def _part_for_relationships(name: str) -> str | None:
    """`word/_rels/settings.xml.rels` belongs to `word/settings.xml` only."""
    lower = name.lower()
    marker = "/_rels/"
    index = lower.rfind(marker)
    if index < 0 or not lower.endswith(".rels"):
        return None
    folder = name[:index]
    base = name[index + len(marker) :]
    if not base.lower().endswith(".rels"):
        return None
    part = base[:-5]
    return f"{folder}/{part}" if folder else part


def _is_markup(name: str) -> bool:
    lower = name.lower()
    return lower.endswith((".xml", ".rels", ".htm", ".html"))


def _rewrite_relationships(data: bytes) -> tuple[bytes, set[str]]:
    text = data.decode("utf-8")
    edited, dropped = _edit_relationships(text)
    return edited.encode("utf-8"), dropped


def _rewrite_document_part(data: bytes, dropped: set[str]) -> bytes:
    text = data.decode("utf-8")
    edited = _edit_markup(text, dropped)
    if _markup_fetches(edited, rels=False):
        raise WordConvertError(_EXTERNAL)
    return data if edited == text else edited.encode("utf-8")


_FETCH_FIELD = re.compile(r"\b(INCLUDEPICTURE|INCLUDETEXT|DDEAUTO|DATABASE|IMPORT|DDE|LINK)\b", re.IGNORECASE)
_REL_TAG = re.compile(
    r"<(?:[\w.]+:)?Relationship\b[^>]*/>|<(?:[\w.]+:)?Relationship\b[^>]*>.*?</(?:[\w.]+:)?Relationship\s*>",
    re.IGNORECASE | re.DOTALL,
)
_URL_ATTR = re.compile(
    r"""(\s(?:[\w.]+:)?(?:src|href)\s*=\s*)(["'])(.*?)\2""",
    re.IGNORECASE | re.DOTALL,
)
_INSTR_TEXT = re.compile(r"(<(?:[\w.]+:)?instrText\b[^>]*>)(.*?)(</(?:[\w.]+:)?instrText\s*>)", re.IGNORECASE | re.DOTALL)


def _markup_fetches(xml: str, rels: bool) -> bool:
    if rels:
        for match in _REL_TAG.finditer(xml):
            if _relationship_fetches(match.group(0)):
                return True
        return False
    if re.search(r"<(?:[\w.]+:)?mailMerge\b", xml, re.IGNORECASE):
        return True
    if re.search(r"<(?:[\w.]+:)?updateFields\b[^>]*\bval\s*=\s*[\"'](?:true|1)[\"']", xml, re.IGNORECASE):
        return True
    for instruction in _field_instructions(xml):
        if _FETCH_FIELD.search(instruction) or contains_remote(instruction):
            return True
    for url in _markup_urls(xml):
        if is_remote(url) or contains_remote(url):
            return True
    return False


def _relationship_fetches(tag: str) -> bool:
    kind = (_attr_value(tag, "Type") or "").lower()
    if kind.endswith("/hyperlink"):
        return False
    target = html.unescape(_attr_value(tag, "Target") or "")
    mode = (_attr_value(tag, "TargetMode") or "").lower()
    return mode == "external" or is_remote(target) or contains_remote(target)


def _edit_relationships(xml: str) -> tuple[str, set[str]]:
    dropped: set[str] = set()

    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        if not _relationship_fetches(tag):
            return tag
        ident = _attr_value(tag, "Id")
        if ident:
            dropped.add(html.unescape(ident))
        return ""

    return _REL_TAG.sub(repl, xml), dropped


def _edit_markup(xml: str, dropped: set[str]) -> str:
    xml = _remove_balanced(xml, "mailMerge")
    xml = re.sub(r"<(?:[\w.]+:)?updateFields\b[^>]*/>", "", xml, flags=re.IGNORECASE)
    xml = re.sub(r"<(?:[\w.]+:)?attachedTemplate\b[^>]*>\s*</(?:[\w.]+:)?attachedTemplate>", "", xml, flags=re.IGNORECASE)
    xml = re.sub(r"<(?:[\w.]+:)?attachedTemplate\b[^>]*/>", "", xml, flags=re.IGNORECASE)
    xml = _strip_relationship_ids(xml, dropped)
    xml = _scrub_remote_attrs(xml)
    xml = _scrub_field_instructions(xml)
    return _lock_field_begins(xml)


def _field_instructions(xml: str) -> list[str]:
    found = []
    for match in re.finditer(r"<(?:[\w.]+:)?fldSimple\b([^>]*)/?>", xml, re.IGNORECASE):
        instr = _attr_value(match.group(1), "instr")
        if instr is not None:
            found.append(html.unescape(instr))
    for pieces in _complex_instructions(xml):
        found.append("".join(pieces))
    return found


def _complex_instructions(xml: str) -> list[list[str]]:
    fields: list[list[str]] = []
    stack: list[list[str]] = []
    for match in re.finditer(r"<(?P<slash>/)?(?P<pre>[\w.]+:)?(?P<name>fldChar|instrText)\b(?P<attrs>[^>]*?)(?P<self>/)?>", xml, re.IGNORECASE):
        name = match.group("name").lower()
        if name == "fldchar" and not match.group("slash"):
            kind = (_attr_value(match.group("attrs"), "fldCharType") or "").lower()
            if kind == "begin":
                stack.append([])
            elif kind in {"separate", "end"} and stack:
                if kind == "end":
                    fields.append(stack.pop())
                else:
                    fields.append(list(stack[-1]))
                    stack[-1] = []
        elif name == "instrtext" and stack and not match.group("slash") and not match.group("self"):
            close = re.search(r"</(?:[\w.]+:)?instrText\s*>", xml[match.end() :], re.IGNORECASE)
            if close:
                stack[-1].append(html.unescape(xml[match.end() : match.end() + close.start()]))
    return fields


def _scrub_field_instructions(xml: str) -> str:
    def repl_simple(match: re.Match[str]) -> str:
        attrs = match.group(2)
        instr = _attr_value(attrs, "instr")
        if instr is None:
            return match.group(0)
        plain = html.unescape(instr)
        if not (_FETCH_FIELD.search(plain) or contains_remote(plain)):
            return match.group(0)
        return match.group(1) + _replace_attr(attrs, "instr", " QUOTE &quot;&quot; ") + match.group(3)

    xml = re.sub(r"(<(?:[\w.]+:)?fldSimple\b)([^>]*?)(/?>)", repl_simple, xml, flags=re.IGNORECASE)
    groups = _complex_instructions(xml)
    if not groups:
        return xml
    matches = list(_INSTR_TEXT.finditer(xml))
    cursor = 0
    replacements: list[tuple[int, int, str]] = []
    for pieces in groups:
        count = len(pieces)
        chunk = matches[cursor : cursor + count]
        cursor += count
        if len(chunk) != count:
            break
        if not (_FETCH_FIELD.search("".join(pieces)) or contains_remote("".join(pieces))):
            continue
        for index, match in enumerate(chunk):
            text = " QUOTE \"\" " if index == 0 else ""
            replacements.append((match.start(2), match.end(2), text))
    for start, end, text in reversed(replacements):
        xml = xml[:start] + text + xml[end:]
    return xml


def _lock_field_begins(xml: str) -> str:
    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        if not re.search(r"fldCharType\s*=\s*[\"']begin[\"']", tag, re.IGNORECASE):
            return tag
        if re.search(r"fldLock\s*=", tag, re.IGNORECASE):
            return tag
        prefix = ""
        named = re.match(r"<([\w.]+:)?fldChar\b", tag, re.IGNORECASE)
        if named and named.group(1):
            prefix = named.group(1)
        if tag.endswith("/>"):
            return tag[:-2] + f' {prefix}fldLock="true"/>'
        return tag[:-1] + f' {prefix}fldLock="true">'

    return re.sub(r"<(?:[\w.]+:)?fldChar\b[^>]*>", repl, xml, flags=re.IGNORECASE)


def _scrub_remote_attrs(xml: str) -> str:
    def repl(match: re.Match[str]) -> str:
        url = html.unescape(match.group(3))
        if is_remote(url) or contains_remote(url):
            return match.group(1) + match.group(2) + match.group(2)
        return match.group(0)

    return _URL_ATTR.sub(repl, xml)


def _strip_relationship_ids(xml: str, dropped: set[str]) -> str:
    for ident in dropped:
        xml = re.sub(
            rf"""\s(?:[\w.]+:)?(?:id|embed|link)\s*=\s*(["']){re.escape(ident)}\1""",
            "",
            xml,
            flags=re.IGNORECASE,
        )
    return xml


def _remove_balanced(xml: str, local: str) -> str:
    pattern = re.compile(rf"<(?P<pre>[\w.]+:)?{local}\b(?P<attrs>[^>]*?)(?P<self>/)?>", re.IGNORECASE)
    while True:
        match = pattern.search(xml)
        if not match:
            return xml
        if match.group("self"):
            xml = xml[: match.start()] + xml[match.end() :]
            continue
        prefix = match.group("pre") or ""
        close_re = re.compile(rf"</{re.escape(prefix)}{local}\s*>", re.IGNORECASE)
        depth = 1
        pos = match.end()
        end_at: int | None = None
        while depth:
            nxt = pattern.search(xml, pos)
            closed = close_re.search(xml, pos)
            if closed is None:
                raise WordConvertError(_EXTERNAL)
            if nxt and not nxt.group("self") and nxt.start() < closed.start():
                depth += 1
                pos = nxt.end()
                continue
            depth -= 1
            pos = closed.end()
            end_at = closed.end()
        xml = xml[: match.start()] + xml[end_at:]


def _markup_urls(xml: str) -> list[str]:
    return [html.unescape(match.group(3)) for match in _URL_ATTR.finditer(xml)]


def _attr_value(blob: str, name: str) -> str | None:
    match = re.search(rf"(?:[\w.]+:)?{name}\s*=\s*([\"'])(.*?)\1", blob, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return match.group(2)


def _replace_attr(blob: str, name: str, value: str) -> str:
    return re.sub(
        rf"((?:[\w.]+:)?{name}\s*=\s*)([\"']).*?\2",
        lambda match: match.group(1) + match.group(2) + value + match.group(2),
        blob,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )


