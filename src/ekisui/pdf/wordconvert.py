"""Turn a local Word file into a PDF with Microsoft Word, when it is installed.

The original .doc or .docx is opened read-only and never saved. Comments and
tracked-change markup stay out of the PDF. Document properties are removed.
Linked images, INCLUDETEXT, and remote templates are removed or left untouched
before Word can fetch them. Link updates stay off for this Word instance.
"""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

import pymupdf

from ekisui.errors import WordConvertError
from ekisui.pdf.wordlinks import (
    contains_remote,
    doc_has_remote_fields,
    external_reference_message,
    irm_message,
    is_remote,
    looks_like_irm,
    neutralize_docx,
)

# Word VBA constants. Hard-coded so the typelib does not have to be generated.
_WD_ALERTS_NONE = 0
_WD_DO_NOT_SAVE_CHANGES = 0
_WD_EXPORT_FORMAT_PDF = 17
_WD_EXPORT_OPTIMIZE_FOR_PRINT = 0
_WD_EXPORT_ALL_DOCUMENT = 0
_WD_EXPORT_DOCUMENT_CONTENT = 0
_WD_EXPORT_CREATE_NO_BOOKMARKS = 0
_WD_REVISIONS_VIEW_FINAL = 0
# msoFeatureInstallNone. Do not download a missing Office feature.
_MSO_FEATURE_INSTALL_NONE = 0
# wdMainAndDataSource, wdMainAndHeader, wdMainAndSourceAndHeader, wdDataSource.
_MERGE_WITH_DATA = {2, 3, 4, 5}

_MISSING = "Microsoft Word が見つかりません。インストールしてから、もう一度開いてください。"
_OPEN_FAILED = "Word でファイルを開けませんでした。パスワードが掛かっているか、ファイルが壊れている可能性があります。"
_EXPORT_FAILED = "Word で PDF に変換できませんでした。"
_NOT_WINDOWS = "Word 文書は、Microsoft Word が入った Windows で開いてください。"


def convert_word_to_pdf(source: str | Path, work_dir: str | Path) -> Path:
    """Write a PDF next to nothing the user owns. Returns the temp PDF path."""
    source = Path(source).resolve()
    if source.suffix.lower() not in {".doc", ".docx"}:
        raise WordConvertError("Word 文書（.doc / .docx）を指定してください。")
    directory = Path(work_dir)
    directory.mkdir(parents=True, exist_ok=True)
    dest = _unique_pdf(directory, source.stem)
    prepared: Path | None = None
    try:
        prepared = _prepare_source(source, directory)
        _export_word(prepared, dest)
        _strip_pdf_metadata(dest)
    except WordConvertError:
        dest.unlink(missing_ok=True)
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise WordConvertError(_EXPORT_FAILED) from exc
    finally:
        if prepared is not None and prepared.resolve() != source.resolve():
            prepared.unlink(missing_ok=True)
    if not dest.is_file() or dest.stat().st_size < 8:
        dest.unlink(missing_ok=True)
        raise WordConvertError(_EXPORT_FAILED)
    return dest


def _prepare_source(source: Path, work_dir: Path) -> Path:
    """Return a file Word may open. The caller's file is not modified."""
    if looks_like_irm(source):
        raise WordConvertError(irm_message())
    kind = _file_kind(source)
    if kind == "zip":
        dest = _unique_docx(work_dir, source.stem)
        neutralize_docx(source, dest)
        return dest
    if kind == "ole":
        if doc_has_remote_fields(source):
            raise WordConvertError(external_reference_message())
        return source
    raise WordConvertError(external_reference_message())


def _file_kind(path: Path) -> str:
    with path.open("rb") as handle:
        head = handle.read(8)
    if head.startswith(b"PK"):
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "ole"
    return "other"


def _export_word(source: Path, dest: Path) -> None:
    if sys.platform != "win32":
        raise WordConvertError(_NOT_WINDOWS)
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise WordConvertError(_MISSING) from exc
    pythoncom.CoInitialize()
    word = None
    error: WordConvertError | None = None
    try:
        try:
            word = win32com.client.DispatchEx("Word.Application")
        except Exception:
            error = WordConvertError(_MISSING)
        else:
            try:
                _export_with_application(word, source, dest)
            except WordConvertError as exc:
                error = WordConvertError(str(exc))
            except Exception:
                error = WordConvertError(_EXPORT_FAILED)
    finally:
        if word is not None:
            try:
                word.Quit(SaveChanges=_WD_DO_NOT_SAVE_CHANGES)
            except Exception:
                pass
        word = None
        gc.collect()
        pythoncom.CoUninitialize()
    if error is not None:
        raise error


def _export_with_application(word, source: Path, dest: Path) -> None:
    """Ask one Word instance for a content-only PDF. The caller owns Quit.

    Arguments are positional. A late-bound Word call drops every named
    argument that follows a skipped optional, which would put comments and
    document properties back into the PDF.
    """
    word.Visible = False
    word.DisplayAlerts = _WD_ALERTS_NONE
    # msoAutomationSecurityForceDisable. Automation otherwise runs macros.
    word.AutomationSecurity = 3
    try:
        word.WordBasic.DisableAutoMacros(1)
    except Exception:
        pass
    # UpdateLinksAtOpen is stored in the user profile, so it is restored.
    saved = _silence_network(word)
    document = None
    try:
        try:
            # Word's Open has no UpdateLinks argument. The option above is what
            # stops it from refreshing links as the file opens. AddToRecentFiles
            # stays false. Fields are not updated; see _block_external.
            document = word.Documents.Open(
                str(source),
                False,  # ConfirmConversions
                True,  # ReadOnly
                False,  # AddToRecentFiles
                "ekisui",  # PasswordDocument: a protected file fails instead of prompting
                "",  # PasswordTemplate
                False,  # Revert
                "",  # WritePasswordDocument
                "",  # WritePasswordTemplate
                0,  # Format: wdOpenFormatAuto
                50001,  # Encoding: msoEncodingAutoDetect
                False,  # Visible
                False,  # OpenAndRepair
                0,  # DocumentDirection
                True,  # NoEncodingDialog
            )
        except WordConvertError:
            raise
        except Exception as exc:
            raise WordConvertError(_OPEN_FAILED) from exc
        try:
            _prepare_final_view(document)
            _block_external(word, document)
            document.ExportAsFixedFormat(
                str(dest),
                _WD_EXPORT_FORMAT_PDF,
                False,  # OpenAfterExport
                _WD_EXPORT_OPTIMIZE_FOR_PRINT,
                _WD_EXPORT_ALL_DOCUMENT,
                1,  # From
                1,  # To
                _WD_EXPORT_DOCUMENT_CONTENT,
                False,  # IncludeDocProps
                False,  # KeepIRM
                _WD_EXPORT_CREATE_NO_BOOKMARKS,
                False,  # DocStructureTags
                False,  # BitmapMissingFonts: keep real text
                False,  # UseISO19005_1
            )
        finally:
            try:
                document.Close(SaveChanges=_WD_DO_NOT_SAVE_CHANGES)
            except Exception:
                pass
    finally:
        _restore_network(word, saved)


def _silence_network(word) -> dict:
    """Turn off link updates for this Word instance. The caller restores them."""
    saved: dict = {}
    try:
        options = word.Options
        saved["update_links"] = options.UpdateLinksAtOpen
        options.UpdateLinksAtOpen = False
    except Exception as exc:
        raise WordConvertError(external_reference_message()) from exc
    try:
        saved["feature_install"] = word.FeatureInstall
        word.FeatureInstall = _MSO_FEATURE_INSTALL_NONE
    except Exception:
        saved.pop("feature_install", None)
    options = getattr(word, "Options", None)
    for option_name in ("UpdateFieldsAtPrint", "UpdateLinksAtPrint"):
        if options is None:
            break
        try:
            saved[option_name] = getattr(options, option_name)
            setattr(options, option_name, False)
        except Exception:
            saved.pop(option_name, None)
    return saved


def _restore_network(word, saved: dict) -> None:
    if "update_links" in saved:
        try:
            word.Options.UpdateLinksAtOpen = saved["update_links"]
        except Exception:
            pass
    if "feature_install" in saved:
        try:
            word.FeatureInstall = saved["feature_install"]
        except Exception:
            pass
    options = getattr(word, "Options", None)
    for option_name in ("UpdateFieldsAtPrint", "UpdateLinksAtPrint"):
        if option_name not in saved or options is None:
            continue
        try:
            setattr(options, option_name, saved[option_name])
        except Exception:
            pass


def _block_external(word, document) -> None:
    """Lock fields and break remote links. Never asks Word to update them."""
    try:
        document.UpdateStylesOnOpen = False
    except Exception:
        pass
    _detach_remote_template(word, document)
    fields: list = []
    shapes: list = []
    try:
        main_fields = document.Fields
    except Exception as exc:
        raise WordConvertError(external_reference_message()) from exc
    fields.extend(_members(main_fields, required=True))
    shapes.extend(_members(getattr(document, "InlineShapes", None), required=False))
    shapes.extend(_members(getattr(document, "Shapes", None), required=False))
    for scope in _extra_scopes(document):
        fields.extend(_members(getattr(scope, "Fields", None), required=False))
        shapes.extend(_members(getattr(scope, "InlineShapes", None), required=False))
        shapes.extend(_members(getattr(scope, "Shapes", None), required=False))
        shapes.extend(_members(getattr(scope, "ShapeRange", None), required=False))
    # Hold every wrapper until the pass ends. pywin32 reuses freed ids.
    seen_fields: set[int] = set()
    seen_shapes: set[int] = set()
    for field in fields:
        if id(field) in seen_fields:
            continue
        seen_fields.add(id(field))
        _freeze_field(field)
    for shape in shapes:
        if id(shape) in seen_shapes:
            continue
        seen_shapes.add(id(shape))
        _break_shape(shape)
    _refuse_connected_merge(document)


def _detach_remote_template(word, document) -> None:
    try:
        path = _template_path(document.AttachedTemplate)
    except Exception as exc:
        raise WordConvertError(external_reference_message()) from exc
    if not is_remote(path) and not contains_remote(path):
        return
    try:
        document.UpdateStylesOnOpen = False
        document.AttachedTemplate = word.NormalTemplate
        again = _template_path(document.AttachedTemplate)
    except Exception as exc:
        raise WordConvertError(external_reference_message()) from exc
    if is_remote(again) or contains_remote(again):
        raise WordConvertError(external_reference_message())


def _template_path(template) -> str:
    if template is None:
        return ""
    if isinstance(template, str):
        return template
    for attr in ("FullName", "Name"):
        try:
            value = getattr(template, attr)
        except Exception:
            continue
        if isinstance(value, str) and value:
            return value
    return ""


def _extra_scopes(document):
    try:
        stories = document.StoryRanges
    except Exception:
        return
    try:
        items = list(stories)
    except Exception:
        return
    for item in items:
        current = item
        seen = 0
        while current is not None and seen < 40:
            if current is not document:
                yield current
            seen += 1
            try:
                current = getattr(current, "NextStoryRange", None)
            except Exception:
                break


def _freeze_field(field) -> None:
    code = _field_code(field)
    remote = contains_remote(code)
    if remote:
        try:
            field.Unlink()
        except Exception as exc:
            raise WordConvertError(external_reference_message()) from exc
        return
    try:
        field.Locked = True
    except Exception:
        return


def _field_code(field) -> str:
    try:
        code = field.Code
    except Exception:
        return ""
    if isinstance(code, str):
        return code
    try:
        return str(getattr(code, "Text", "") or "")
    except Exception:
        return ""


def _break_shape(shape) -> None:
    try:
        link = shape.LinkFormat
    except Exception:
        return
    if link is None:
        return
    try:
        source = str(getattr(link, "SourceFullName", "") or "")
    except Exception:
        kind = getattr(shape, "Type", None)
        if kind in (2, 4):
            raise WordConvertError(external_reference_message()) from None
        return
    try:
        link.AutoUpdate = False
    except Exception:
        pass
    if not is_remote(source) and not contains_remote(source):
        return
    try:
        link.BreakLink()
    except Exception as exc:
        raise WordConvertError(external_reference_message()) from exc
    try:
        left = str(getattr(link, "SourceFullName", "") or "")
    except Exception:
        left = ""
    if is_remote(left) or contains_remote(left):
        raise WordConvertError(external_reference_message())


def _refuse_connected_merge(document) -> None:
    try:
        merge = document.MailMerge
        state = merge.State
    except Exception:
        return
    if state in _MERGE_WITH_DATA:
        raise WordConvertError(external_reference_message())


def _members(collection, required: bool) -> list:
    if collection is None:
        if required:
            raise WordConvertError(external_reference_message())
        return []
    try:
        return list(collection)
    except TypeError:
        pass
    except Exception:
        if required:
            raise WordConvertError(external_reference_message()) from None
        return []
    try:
        count = int(collection.Count)
    except Exception:
        if required:
            raise WordConvertError(external_reference_message()) from None
        return []
    found = []
    for index in range(1, count + 1):
        try:
            found.append(collection.Item(index))
        except Exception:
            if required:
                raise WordConvertError(external_reference_message()) from None
    return found


def _prepare_final_view(document) -> None:
    """Show the accepted text, with comments and revision marks hidden.

    Export Item is still document-content (no markup). The view is set too,
    because some Word versions follow the window when they print.
    """
    try:
        view = document.ActiveWindow.View
        try:
            view.RevisionsFilter.Markup = 0
            view.RevisionsFilter.View = _WD_REVISIONS_VIEW_FINAL
        except Exception:
            pass
        view.RevisionsView = _WD_REVISIONS_VIEW_FINAL
        view.ShowRevisionsAndComments = False
        view.ShowComments = False
        view.ShowInsertionsAndDeletions = False
    except Exception:
        return


def _strip_pdf_metadata(path: Path) -> None:
    from ekisui.pdf.export import strip_document

    source = pymupdf.open(path)
    temporary = path.with_name(path.name + ".partial")
    try:
        cleaned = strip_document(source)
        try:
            cleaned.save(
                temporary,
                garbage=4,
                deflate=True,
                clean=True,
                incremental=False,
                encryption=pymupdf.PDF_ENCRYPT_NONE,
                preserve_metadata=0,
            )
        finally:
            cleaned.close()
    finally:
        source.close()
    os.replace(temporary, path)


def _unique_pdf(directory: Path, stem: str) -> Path:
    return _unique_named(directory, stem, ".pdf")


def _unique_docx(directory: Path, stem: str) -> Path:
    return _unique_named(directory, f"{stem}.offline", ".docx")


def _unique_named(directory: Path, stem: str, suffix: str) -> Path:
    path = directory / f"{stem}{suffix}"
    number = 2
    while path.exists():
        path = directory / f"{stem} ({number}){suffix}"
        number += 1
    return path
