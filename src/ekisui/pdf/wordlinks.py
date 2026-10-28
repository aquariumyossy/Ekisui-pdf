"""Remove external Word targets before Microsoft Word can open them.

Word fetches linked images, INCLUDETEXT, and attached templates while it
opens a file. The .docx package is rewritten first, so those addresses are
gone before Word starts. A binary .doc cannot be rewritten safely; when it
already contains such a target, conversion stops instead of launching Word.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

from ekisui.errors import WordConvertError

W_URI = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_URI = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_URI = "http://schemas.openxmlformats.org/package/2006/relationships"

_EXTERNAL = "この Word 文書は、外部の画像や文書、ひな形を参照しています。通信せずには開けないため、開くのをやめました。"
_IRM = "この Word 文書は権利管理（IRM）で保護されています。確認のために外部へ接続する可能性があるため、開くのをやめました。"
_IRM_MARKERS = (
    b"DRMEncryptedTransform",
    b"Microsoft.Metadata.DRMTransform",
    b"DRMContent",
)
_FIELD_WITH_TARGET = ("INCLUDEPICTURE", "INCLUDETEXT", "DDEAUTO", "DATABASE")
_TEMPLATE_SUFFIX = re.compile(r"\.(?:dot|dotx|dotm)\b", re.IGNORECASE)


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
    if lowered.startswith("file://"):
        rest = text[7:]
        if rest.startswith("/"):
            rest = rest.lstrip("/")
            if re.match(r"^[A-Za-z]:[\\/]", rest):
                return False
            if rest.lower().startswith(("localhost", "127.0.0.1")):
                return False
            return False
        host = rest.split("/", 1)[0].lower()
        return bool(host) and host not in {"localhost", "127.0.0.1"}
    return False


def contains_remote(text: str) -> bool:
    """True when a field instruction or path mentions a remote target."""
    if not text:
        return False
    lowered = unquote(text).lower()
    if any(token in lowered for token in ("http://", "https://", "ftp://", "ftps://", "sftp://")):
        return True
    if "\\\\" in text or "\\\\" in unquote(text):
        return True
    if re.search(r"file://[^/]", lowered):
        return True
    return False


def looks_like_irm(path: Path) -> bool:
    with path.open("rb") as handle:
        sample = handle.read(4_000_000)
    return any(marker in sample for marker in _IRM_MARKERS)


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
        if name.endswith(".rels"):
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
        if _is_word_xml(name, data):
            try:
                rewritten[name] = _rewrite_document_part(data, dropped_by_part.get(name, set()))
            except WordConvertError:
                raise
            except Exception as exc:
                raise WordConvertError(_EXTERNAL) from exc
    for name, data in rewritten.items():
        if name.endswith((".xml", ".rels")) and _xml_still_fetches(data):
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
    upper = text.upper()
    for name in _FIELD_WITH_TARGET:
        start = 0
        while True:
            index = upper.find(name, start)
            if index < 0:
                break
            if contains_remote(text[index : index + 800]):
                return True
            start = index + len(name)
    for match in re.finditer(r"(?:^|[\s\x13])LINK\s.{0,400}", text, re.IGNORECASE):
        if contains_remote(match.group(0)):
            return True
    for match in re.finditer(r"(?:^|[\s\x13])DDE\s.{0,400}", text, re.IGNORECASE):
        if contains_remote(match.group(0)):
            return True
    for match in re.finditer(r"\\\\[^\s\"'<>]{1,240}", text):
        if _TEMPLATE_SUFFIX.search(match.group(0)):
            return True
    for match in re.finditer(r"https?://[^\s\"'<>]{1,240}", text, re.IGNORECASE):
        if _TEMPLATE_SUFFIX.search(match.group(0)):
            return True
    return False


def _part_fetches(name: str, data: bytes) -> bool:
    if not (name.endswith(".rels") or _is_word_xml(name, data)):
        return False
    try:
        root = _parse_xml(data)
    except ElementTree.ParseError:
        return True
    return bool(_remaining_fetch_targets(root))


def _part_for_relationships(name: str) -> str | None:
    """`word/_rels/settings.xml.rels` belongs to `word/settings.xml` only."""
    marker = "/_rels/"
    if marker not in name or not name.endswith(".rels"):
        return None
    folder, base = name.split(marker, 1)
    part = base[: -len(".rels")]
    return f"{folder}/{part}" if folder else part


def _is_word_xml(name: str, data: bytes) -> bool:
    if not name.endswith(".xml") or name.endswith(".rels"):
        return False
    return name.startswith("word/")


def _rewrite_relationships(data: bytes) -> tuple[bytes, set[str]]:
    root = _parse_xml(data)
    dropped: set[str] = set()
    removed = []
    for element in list(root):
        if _local(element.tag) != "Relationship":
            continue
        target = element.get("Target") or ""
        kind = (element.get("Type") or "").lower()
        if kind.endswith("/hyperlink"):
            continue
        if is_remote(target) or contains_remote(target):
            ident = element.get("Id") or ""
            if ident:
                dropped.add(ident)
            removed.append(element)
    for element in removed:
        root.remove(element)
    return _xml_bytes(root), dropped


def _rewrite_document_part(data: bytes, dropped: set[str]) -> bytes:
    root = _parse_xml(data)
    _strip_dropped_references(root, dropped)
    _scrub_fields(root)
    _scrub_loose_instructions(root)
    if _remaining_fetch_targets(root):
        raise WordConvertError(_EXTERNAL)
    return _xml_bytes(root)


def _strip_dropped_references(root: ElementTree.Element, dropped: set[str]) -> None:
    if not dropped:
        return
    parents = _parent_map(root)
    doomed: list[ElementTree.Element] = []
    for element in list(root.iter()):
        if _local(element.tag) == "mailMerge" and _subtree_uses(element, dropped):
            doomed.append(element)
            continue
        refs = _relationship_ids(element)
        if not any(value in dropped for _key, value in refs):
            continue
        kept = [(key, value) for key, value in refs if value not in dropped]
        if kept and _local(element.tag) == "blip":
            for key, value in refs:
                if value in dropped:
                    del element.attrib[key]
            continue
        doomed.append(element)
    for element in doomed:
        parent = parents.get(element)
        if parent is not None and element in list(parent):
            parent.remove(element)


def _scrub_fields(root: ElementTree.Element) -> None:
    stack: list[dict] = []
    for element in root.iter():
        name = _local(element.tag)
        if name == "fldChar":
            kind = (_attr(element, "fldCharType") or "").lower()
            if kind == "begin":
                _set_attr(element, "fldLock", "true", W_URI)
                stack.append({"nodes": [], "scrubbed": False})
            elif kind == "separate" and stack:
                _scrub_instruction(stack[-1])
            elif kind == "end" and stack:
                field = stack.pop()
                _scrub_instruction(field)
        elif name == "instrText" and stack:
            stack[-1]["nodes"].append(element)
        elif name == "fldSimple" and contains_remote(_attr(element, "instr") or ""):
            _set_attr(element, "instr", ' QUOTE "" ', W_URI)


def _scrub_instruction(field: dict) -> None:
    if field["scrubbed"]:
        return
    text = "".join(node.text or "" for node in field["nodes"])
    if not contains_remote(text):
        return
    if field["nodes"]:
        field["nodes"][0].text = ' QUOTE "" '
        for node in field["nodes"][1:]:
            node.text = ""
    field["scrubbed"] = True


def _scrub_loose_instructions(root: ElementTree.Element) -> None:
    for element in root.iter():
        name = _local(element.tag)
        if name == "instrText" and contains_remote(element.text or ""):
            element.text = ' QUOTE "" '
        elif name == "fldSimple" and contains_remote(_attr(element, "instr") or ""):
            _set_attr(element, "instr", ' QUOTE "" ', W_URI)


def _xml_still_fetches(data: bytes) -> bool:
    try:
        root = _parse_xml(data)
    except ElementTree.ParseError:
        return True
    return bool(_remaining_fetch_targets(root))


def _remaining_fetch_targets(root: ElementTree.Element) -> list[str]:
    found: list[str] = []
    for element in root.iter():
        name = _local(element.tag)
        if name == "instrText" and contains_remote(element.text or ""):
            found.append(element.text or "")
        elif name == "fldSimple" and contains_remote(_attr(element, "instr") or ""):
            found.append(_attr(element, "instr") or "")
        elif name == "Relationship":
            target = element.get("Target") or ""
            kind = (element.get("Type") or "").lower()
            if not kind.endswith("/hyperlink") and (is_remote(target) or contains_remote(target)):
                found.append(target)
    return found


def _parse_xml(data: bytes) -> ElementTree.Element:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    text = data.decode("utf-8", errors="replace")
    for prefix, uri in re.findall(r'xmlns:([A-Za-z0-9]+)="([^"]+)"', text):
        ElementTree.register_namespace(prefix, uri)
    if 'xmlns="' in text:
        match = re.search(r'\sxmlns="([^"]+)"', text)
        if match:
            ElementTree.register_namespace("", match.group(1))
    for prefix, uri in (("w", W_URI), ("r", R_URI), ("pr", REL_URI)):
        ElementTree.register_namespace(prefix, uri)
    return ElementTree.fromstring(data)


def _xml_bytes(root: ElementTree.Element) -> bytes:
    return ElementTree.tostring(root, encoding="UTF-8", xml_declaration=True)


def _relationship_ids(element: ElementTree.Element) -> list[tuple[str, str]]:
    found = []
    for key, value in element.attrib.items():
        if key.startswith("{") and key[1:].split("}", 1)[0] == R_URI:
            found.append((key, value))
    return found


def _subtree_uses(element: ElementTree.Element, dropped: set[str]) -> bool:
    for node in element.iter():
        if any(value in dropped for _key, value in _relationship_ids(node)):
            return True
    return False


def _parent_map(root: ElementTree.Element) -> dict[ElementTree.Element, ElementTree.Element | None]:
    parents: dict[ElementTree.Element, ElementTree.Element | None] = {root: None}
    for element in root.iter():
        for child in list(element):
            parents[child] = element
    return parents


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(element: ElementTree.Element, local: str) -> str | None:
    for key, value in element.attrib.items():
        if key == local or key.endswith("}" + local):
            return value
    return None


def _set_attr(element: ElementTree.Element, local: str, value: str, uri: str) -> None:
    for key in list(element.attrib):
        if key == local or key.endswith("}" + local):
            element.set(key, value)
            return
    element.set(f"{{{uri}}}{local}", value)
