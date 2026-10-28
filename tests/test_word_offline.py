"""Word conversion must not ask Microsoft Word to fetch external targets."""

import io
import zipfile
from pathlib import Path

import pytest

from ekisui.errors import WordConvertError
from ekisui.pdf.wordconvert import _export_with_application, convert_word_to_pdf
from ekisui.pdf.wordlinks import (
    doc_has_remote_fields,
    external_reference_message,
    is_remote,
    neutralize_docx,
)


def test_single_quoted_vml_and_explicit_relationship_are_removed(tmp_path) -> None:
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <w:p><w:r><w:t>残す</w:t></w:r></w:p>
    <w:p><w:r><v:imagedata r:id="rId7" src='http://example.invalid/single.png'/></w:r></w:p>
  </w:body>
</w:document>
"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="http://example.invalid/photo.png" TargetMode="External"></Relationship>
</Relationships>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    package = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    source = tmp_path / "quoted.docx"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", rels)
    source.write_bytes(buffer.getvalue())
    dest = tmp_path / "clean.docx"
    neutralize_docx(source, dest)
    blob = "\n".join(_parts(dest.read_bytes()).values())
    assert "残す" in blob
    assert "example.invalid" not in blob
    assert "single.png" not in blob
    assert "photo.png" not in blob


def _package(directory: Path, parts: dict[str, bytes]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "sample.docx"
    payload = {
        "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        "_rels/.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>',
    }
    payload.update(parts)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in payload.items():
            archive.writestr(name, data)
    source.write_bytes(buffer.getvalue())
    return source


def test_rtf_altchunk_utf16_rels_and_open_field_do_not_reach_word(tmp_path) -> None:
    rtf = _package(tmp_path, {
        "word/chunk.rtf": b'{\\rtf1 INCLUDEPICTURE "http://example.invalid/a.png"}',
    })
    with pytest.raises(WordConvertError) as caught:
        neutralize_docx(rtf, tmp_path / "rtf-out.docx")
    assert "外部" in str(caught.value)

    rels = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        'Target="http://example.invalid/photo.png" TargetMode="External"/>'
        "</Relationships>"
    ).encode("utf-16")
    utf16 = _package(tmp_path / "utf", {"word/_rels/document.xml.rels": rels})
    dest = tmp_path / "utf-clean.docx"
    neutralize_docx(utf16, dest)
    assert b"example.invalid" not in dest.read_bytes()

    document = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r>
    <w:fldChar w:fldCharType="begin"/>
    <w:instrText> INCLUDEPICTURE "http://example.invalid/open.png" </w:instrText>
    <w:t>残す</w:t>
  </w:r></w:p></w:body>
</w:document>
""".encode()
    opened = _package(tmp_path / "open", {"word/document.xml": document})
    out = tmp_path / "open-clean.docx"
    neutralize_docx(opened, out)
    text = "\n".join(_parts(out.read_bytes()).values())
    assert "open.png" not in text
    assert "残す" in text


def test_schema_lookalike_and_utf8_comment_do_not_slip_through(tmp_path) -> None:
    svg = _package(tmp_path / "svg", {
        "word/media/image1.svg": b'<svg xmlns="http://www.w3.org/2000/svg"><image href="http://www.w3.org.attacker.example/track.png"/></svg>',
    })
    with pytest.raises(WordConvertError) as caught:
        neutralize_docx(svg, tmp_path / "svg-out.docx")
    assert "外部" in str(caught.value)

    mht = _package(tmp_path / "mht", {
        "word/afchunk.mht": b'<img src="file://fileserver/share/secret.png">',
    })
    with pytest.raises(WordConvertError) as caught:
        neutralize_docx(mht, tmp_path / "mht-out.docx")
    assert "外部" in str(caught.value)

    types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/chunk.xml" ContentType="application/rtf"/>
</Types>
"""
    rtf_named_xml = _package(tmp_path / "ctype", {
        "[Content_Types].xml": types.encode(),
        "word/chunk.xml": b'{\\rtf1 INCLUDEPICTURE "http://example.invalid/a.png"}',
    })
    with pytest.raises(WordConvertError) as caught:
        neutralize_docx(rtf_named_xml, tmp_path / "ctype-out.docx")
    assert "外部" in str(caught.value)

    document = """<?xml version="1.0" encoding="UTF-8"?>
<!-- encoding="UTF-16" -->
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r>
    <w:fldChar w:fldCharType="begin"/>
    <w:instrText> INCLUDEPICTURE "http://example.invalid/open.png" </w:instrText>
    <w:t>KEEP</w:t>
  </w:r></w:p></w:body>
</w:document>
""".encode()
    commented = _package(tmp_path / "comment", {"word/document.xml": document})
    dest = tmp_path / "comment-clean.docx"
    neutralize_docx(commented, dest)
    text = "\n".join(_parts(dest.read_bytes()).values())
    assert "open.png" not in text
    assert "KEEP" in text


def test_remote_forms() -> None:
    assert is_remote("file:////fileserver/share/secret.dotx")
    assert is_remote("file://fileserver/share/secret.dotx")
    assert is_remote("//fileserver/share/secret.dotx")
    assert not is_remote("file:///C:/Users/a.png")
    assert not is_remote("C:\\\\Users\\\\a.png")

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "external-links.docx"
FORBIDDEN = {
    "Update",
    "UpdateLinks",
    "UpdateSource",
    "FollowHyperlink",
    "Reload",
    "WebPagePreview",
    "Save",
    "SaveAs",
}


def build_external_docx() -> bytes:
    """A .docx with an http picture, a split INCLUDEPICTURE, an IF/INCLUDETEXT, and a UNC template."""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
</Types>
"""
    package_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <w:p><w:r><w:t>控える文章です</w:t></w:r></w:p>
    <w:p>
      <w:fldSimple w:instr=" INCLUDEPICTURE &quot;http://example.invalid/photo.png&quot; \\d ">
        <w:r><w:t>写真</w:t></w:r>
      </w:fldSimple>
    </w:p>
    <w:p>
      <w:r>
        <w:fldChar w:fldCharType="begin"/>
        <w:instrText xml:space="preserve"> INCLUDEPICTURE "http://example.</w:instrText>
        <w:instrText xml:space="preserve">invalid/split.png" </w:instrText>
        <w:fldChar w:fldCharType="end"/>
      </w:r>
    </w:p>
    <w:p>
      <w:fldSimple w:instr=" IF 1 = 1 INCLUDETEXT &quot;\\\\fileserver\\share\\clause.docx&quot; &quot;&quot; ">
        <w:r><w:t>条項</w:t></w:r>
      </w:fldSimple>
    </w:p>
    <w:p>
      <w:hyperlink r:id="rId2"><w:r><w:t>案内</w:t></w:r></w:hyperlink>
    </w:p>
  </w:body>
</w:document>
"""
    document_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="http://example.invalid/info" TargetMode="External"/>
</Relationships>
"""
    settings = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:attachedTemplate r:id="rId1"/>
</w:settings>
"""
    settings_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" Target="\\\\fileserver\\share\\secret.dotx" TargetMode="External"/>
</Relationships>
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_rels)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", document_rels)
        archive.writestr("word/settings.xml", settings)
        archive.writestr("word/_rels/settings.xml.rels", settings_rels)
    return buffer.getvalue()


def _parts(blob: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


class _Log:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def add(self, name: str) -> None:
        self.calls.append(name)


class _Code:
    def __init__(self, text: str) -> None:
        self.Text = text


class _Field:
    def __init__(self, code: str, log: _Log) -> None:
        self.Code = _Code(code)
        self.Locked = False
        self.unlinked = False
        self.log = log

    def Unlink(self) -> None:
        self.log.add("Unlink")
        self.unlinked = True

    def Update(self) -> None:
        self.log.add("Update")


class _Fields:
    def __init__(self, items: list[_Field], log: _Log) -> None:
        self._items = items
        self.log = log

    def __iter__(self):
        return iter(self._items)

    def Update(self) -> None:
        self.log.add("Update")


class _Link:
    def __init__(self, source: str, log: _Log, fail: bool = False) -> None:
        self.SourceFullName = source
        self.AutoUpdate = True
        self.log = log
        self.fail = fail

    def BreakLink(self) -> None:
        self.log.add("BreakLink")
        if self.fail:
            raise OSError("link")
        self.SourceFullName = ""

    def Update(self) -> None:
        self.log.add("Update")


class _Shape:
    def __init__(self, source: str, log: _Log, fail: bool = False) -> None:
        self.Type = 4
        self.LinkFormat = _Link(source, log, fail)


class _Template:
    def __init__(self, path: str) -> None:
        self.FullName = path


class _Story:
    def __init__(self, log: _Log) -> None:
        self.Fields = _Fields([], log)
        self.InlineShapes = [_Shape(r"\\fileserver\share\ole.bin", log)]
        self.Shapes = []
        self.ShapeRange = []
        self.NextStoryRange = None


class _View:
    def __init__(self) -> None:
        self.RevisionsView = None
        self.ShowRevisionsAndComments = None
        self.ShowComments = None
        self.ShowInsertionsAndDeletions = None


class _Doc:
    def __init__(self, log: _Log, fail_break: bool = False) -> None:
        self.log = log
        self.ActiveWindow = type("Window", (), {"View": _View()})()
        self.picture = _Field(' INCLUDEPICTURE "http://example.invalid/photo.png" ', log)
        self.date = _Field(" DATE ", log)
        self.Fields = _Fields([self.picture, self.date], log)
        self.InlineShapes = []
        self.Shapes = []
        self.StoryRanges = [_Story(log)]
        if fail_break:
            self.InlineShapes = [_Shape("http://example.invalid/photo.png", log, fail=True)]
            self.StoryRanges = []
            self.AttachedTemplate = _Template(r"C:\Users\Public\Normal.dotm")
        else:
            self.AttachedTemplate = _Template(r"\\fileserver\share\secret.dotx")
        self.UpdateStylesOnOpen = True
        self.MailMerge = type("Merge", (), {"State": 0})()
        self.export_args = None
        self.closed = None

    def ExportAsFixedFormat(self, *args, **kwargs) -> None:
        self.log.add("ExportAsFixedFormat")
        self.export_args = args

    def Close(self, **kwargs) -> None:
        self.log.add("Close")
        self.closed = kwargs

    def Save(self) -> None:
        self.log.add("Save")

    def SaveAs(self, *args, **kwargs) -> None:
        self.log.add("SaveAs")

    def Update(self) -> None:
        self.log.add("Update")


class _Documents:
    def __init__(self, document: _Doc, word, log: _Log) -> None:
        self.document = document
        self.word = word
        self.log = log
        self.opened_args = None
        self.links_at_open = None
        self.feature_at_open = None

    def Open(self, *args, **kwargs):
        self.log.add("Open")
        self.opened_args = args
        self.links_at_open = self.word.Options.UpdateLinksAtOpen
        self.feature_at_open = self.word.FeatureInstall
        if self.word.fail_open:
            raise RuntimeError("open failed")
        return self.document


class _WordBasic:
    def __init__(self, log: _Log) -> None:
        self.log = log

    def DisableAutoMacros(self, value: int) -> None:
        self.log.add("DisableAutoMacros")


class _Word:
    def __init__(self, log: _Log, fail_open: bool = False, fail_break: bool = False) -> None:
        self.log = log
        self.fail_open = fail_open
        self.Documents = _Documents(_Doc(log, fail_break=fail_break), self, log)
        self.Options = type("Options", (), {"UpdateLinksAtOpen": True})()
        self.FeatureInstall = 1
        self.NormalTemplate = _Template(r"C:\Users\Public\Normal.dotm")
        self.Visible = True
        self.DisplayAlerts = 1
        self.AutomationSecurity = 1
        self.WordBasic = _WordBasic(log)

    def Update(self) -> None:
        self.log.add("Update")

    def FollowHyperlink(self, *args, **kwargs) -> None:
        self.log.add("FollowHyperlink")


def test_clean_docx_is_copied_unchanged(tmp_path) -> None:
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>そのまま</w:t></w:r></w:p></w:body>
</w:document>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    package_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_rels)
        archive.writestr("word/document.xml", document)
    raw = buffer.getvalue()
    source = tmp_path / "clean.docx"
    source.write_bytes(raw)
    dest = tmp_path / "copy.docx"
    neutralize_docx(source, dest)
    assert dest.read_bytes() == raw


def test_fixture_contains_http_picture_and_unc_template() -> None:
    parts = _parts(FIXTURE.read_bytes())
    assert parts == _parts(build_external_docx())
    assert "INCLUDEPICTURE" in parts["word/document.xml"]
    assert "http://example.invalid/photo.png" in parts["word/document.xml"]
    assert "invalid/split.png" in parts["word/document.xml"]
    assert "INCLUDETEXT" in parts["word/document.xml"]
    assert "fileserver" in parts["word/_rels/settings.xml.rels"]
    assert "secret.dotx" in parts["word/_rels/settings.xml.rels"]
    assert "attachedTemplate" in parts["word/settings.xml"]
    assert is_remote("\\\\fileserver\\share\\secret.dotx")
    assert is_remote("http://example.invalid/photo.png")
    assert not is_remote("C:\\Users\\Public\\Normal.dotm")


def test_neutralize_removes_fetch_targets_and_keeps_text_and_hyperlink(tmp_path) -> None:
    source = tmp_path / "external-links.docx"
    source.write_bytes(FIXTURE.read_bytes())
    dest = tmp_path / "clean.docx"
    neutralize_docx(source, dest)
    assert source.read_bytes() == FIXTURE.read_bytes()
    parts = _parts(dest.read_bytes())
    document = parts["word/document.xml"]
    assert "控える文章です" in document
    assert "写真" in document
    assert "条項" in document
    assert "http://example.invalid/photo.png" not in document
    assert "split.png" not in document
    assert "fileserver" not in document
    assert "INCLUDEPICTURE" not in document
    assert "INCLUDETEXT" not in document
    assert "fileserver" not in parts["word/_rels/settings.xml.rels"]
    assert "attachedTemplate" not in parts["word/settings.xml"]
    assert "http://example.invalid/info" in parts["word/_rels/document.xml.rels"]
    assert "QUOTE" in document


def test_convert_gives_word_the_neutralized_copy_and_deletes_it(tmp_path, monkeypatch) -> None:
    seen: dict = {}

    def fake_export(source, dest) -> None:
        seen["path"] = Path(source)
        seen["bytes"] = Path(source).read_bytes()
        dest.write_bytes(b"%PDF-1.4\n" + b"0" * 32)

    monkeypatch.setattr("ekisui.pdf.wordconvert._export_word", fake_export)
    monkeypatch.setattr("ekisui.pdf.wordconvert._strip_pdf_metadata", lambda _path: None)
    original = FIXTURE.read_bytes()
    result = convert_word_to_pdf(FIXTURE, tmp_path / "work")
    assert result.is_file()
    assert FIXTURE.read_bytes() == original
    assert seen["path"].resolve() != FIXTURE.resolve()
    assert not seen["path"].exists()
    parts = _parts(seen["bytes"])
    assert "http://example.invalid/photo.png" not in parts["word/document.xml"]
    assert "fileserver" not in "".join(parts.values())
    assert "控える文章です" in parts["word/document.xml"]


def test_external_com_document_is_unlinked_without_an_update(tmp_path) -> None:
    log = _Log()
    word = _Word(log)
    source = tmp_path / "契約.docx"
    source.write_bytes(b"original")
    _export_with_application(word, source, tmp_path / "out.pdf")
    assert word.Documents.links_at_open is False
    assert word.Documents.feature_at_open == 0
    assert word.Options.UpdateLinksAtOpen is True
    assert word.FeatureInstall == 1
    assert word.AutomationSecurity == 3
    opened = word.Documents.opened_args
    assert opened[3] is False
    assert word.Documents.document.picture.unlinked is True
    assert word.Documents.document.date.unlinked is False
    assert word.Documents.document.date.Locked is True
    assert word.Documents.document.AttachedTemplate.FullName.endswith("Normal.dotm")
    assert word.Documents.document.UpdateStylesOnOpen is False
    story_link = word.Documents.document.StoryRanges[0].InlineShapes[0].LinkFormat
    assert story_link.SourceFullName == ""
    assert story_link.AutoUpdate is False
    assert word.Documents.document.export_args is not None
    assert word.Documents.document.closed == {"SaveChanges": 0}
    assert source.read_bytes() == b"original"
    assert not (FORBIDDEN & set(log.calls))
    assert "Unlink" in log.calls
    assert "BreakLink" in log.calls
    assert "Open" in log.calls


def test_break_link_failure_refuses_without_export_or_update(tmp_path) -> None:
    log = _Log()
    word = _Word(log, fail_break=True)
    with pytest.raises(WordConvertError) as caught:
        _export_with_application(word, tmp_path / "a.docx", tmp_path / "out.pdf")
    assert str(caught.value) == external_reference_message()
    assert word.Documents.document.export_args is None
    assert word.Options.UpdateLinksAtOpen is True
    assert not (FORBIDDEN & set(log.calls))


def test_open_failure_restores_link_updates(tmp_path) -> None:
    log = _Log()
    word = _Word(log, fail_open=True)
    with pytest.raises(WordConvertError) as caught:
        _export_with_application(word, tmp_path / "a.docx", tmp_path / "out.pdf")
    assert "開けません" in str(caught.value)
    assert word.Documents.links_at_open is False
    assert word.Options.UpdateLinksAtOpen is True
    assert not (FORBIDDEN & set(log.calls))


def test_doc_with_remote_field_never_starts_word(tmp_path, monkeypatch) -> None:
    source = tmp_path / "外部.doc"
    source.write_bytes('前文 INCLUDEPICTURE "http://example.invalid/a.png" 後文'.encode("utf-16-le"))
    called = []
    monkeypatch.setattr("ekisui.pdf.wordconvert._export_word", lambda *args, **kwargs: called.append(args))
    with pytest.raises(WordConvertError) as caught:
        convert_word_to_pdf(source, tmp_path / "work")
    assert str(caught.value) == external_reference_message()
    assert called == []


def test_doc_body_url_and_plain_unc_are_not_treated_as_fields(tmp_path, monkeypatch) -> None:
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    citation = tmp_path / "引用.doc"
    citation.write_bytes(ole + "裁判所のサイトは http://courts.go.jp/ です".encode("utf-16-le"))
    notes = tmp_path / "メモ.doc"
    notes.write_bytes(ole + b"see \\\\fileserver\\share\\notes.txt")
    assert doc_has_remote_fields(citation) is False
    assert doc_has_remote_fields(notes) is False
    template = tmp_path / "ひな形.doc"
    template.write_bytes(ole + "attached \\\\srv\\Shared Templates\\firm.dotx".encode("utf-16-le"))
    assert doc_has_remote_fields(template) is True
    monkeypatch.setattr("ekisui.pdf.wordconvert.sys.platform", "linux")
    with pytest.raises(WordConvertError) as caught:
        convert_word_to_pdf(citation, tmp_path / "work")
    assert "Windows" in str(caught.value)


def test_split_field_and_file_unc_and_vml_are_removed_before_word(tmp_path) -> None:
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <w:p><w:r><w:t>残す</w:t></w:r></w:p>
    <w:p><w:r>
      <w:fldChar w:fldCharType="begin"/>
      <w:instrText> INCLUDETEXT "htt</w:instrText>
      <w:instrText>p://example.invalid/a.docx" </w:instrText>
      <w:fldChar w:fldCharType="end"/>
    </w:r></w:p>
    <w:p><w:r><v:imagedata src="http://example.invalid/photo.png"/></w:r></w:p>
  </w:body>
</w:document>
"""
    settings = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:attachedTemplate r:id="rId1"/>
  <w:updateFields w:val="true"/>
</w:settings>
"""
    settings_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" Target="file:////fileserver/share/secret.dotx" TargetMode="External"/>
</Relationships>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    package_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    source = tmp_path / "split.doc"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_rels)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/settings.xml", settings)
        archive.writestr("word/_rels/settings.xml.rels", settings_rels)
    source.write_bytes(buffer.getvalue())
    dest = tmp_path / "clean.docx"
    neutralize_docx(source, dest)
    parts = _parts(dest.read_bytes())
    blob = "\n".join(parts.values())
    assert "残す" in parts["word/document.xml"]
    assert "example.invalid" not in blob
    assert "fileserver" not in blob
    assert "updateFields" not in parts["word/settings.xml"]
    assert "attachedTemplate" not in parts["word/settings.xml"]
    assert 'fldLock="true"' in parts["word/document.xml"]


def test_html_and_irm_utf16_are_refused_before_word(tmp_path, monkeypatch) -> None:
    from ekisui.pdf.wordconvert import _prepare_source
    from ekisui.pdf.wordlinks import looks_like_irm

    html_doc = tmp_path / "page.doc"
    html_doc.write_bytes(b"<html><img src=\"http://example.invalid/a.png\"></html>")
    called = []
    monkeypatch.setattr("ekisui.pdf.wordconvert._export_word", lambda *args, **kwargs: called.append(args))
    with pytest.raises(WordConvertError) as caught:
        convert_word_to_pdf(html_doc, tmp_path / "work")
    assert "外部" in str(caught.value)
    assert called == []
    irm = tmp_path / "rights.docx"
    irm.write_bytes(b"\xd0\xcf\x11\xe0" + "DRMEncryptedTransform".encode("utf-16-le"))
    assert looks_like_irm(irm) is True
    with pytest.raises(WordConvertError) as caught:
        _prepare_source(irm, tmp_path / "work")
    assert "権利管理" in str(caught.value)


def test_irm_document_is_refused_before_word(tmp_path, monkeypatch) -> None:
    source = tmp_path / "権利.docx"
    source.write_bytes(b"OLE" + b"DRMEncryptedTransform" + b"rest")
    called = []
    monkeypatch.setattr("ekisui.pdf.wordconvert._export_word", lambda *args, **kwargs: called.append(args))
    with pytest.raises(WordConvertError) as caught:
        convert_word_to_pdf(source, tmp_path / "work")
    assert "権利管理" in str(caught.value)
    assert called == []


def test_connected_mail_merge_is_refused(tmp_path) -> None:
    log = _Log()
    word = _Word(log)
    word.Documents.document.MailMerge.State = 2
    word.Documents.document.AttachedTemplate = _Template(r"C:\Users\Public\Normal.dotm")
    word.Documents.document.StoryRanges = []
    with pytest.raises(WordConvertError) as caught:
        _export_with_application(word, tmp_path / "a.docx", tmp_path / "out.pdf")
    assert "外部" in str(caught.value)
    assert word.Documents.document.export_args is None
    assert not (FORBIDDEN & set(log.calls))
