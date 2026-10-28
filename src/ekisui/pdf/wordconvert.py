"""Turn a local Word file into a PDF with Microsoft Word, when it is installed.

The original .doc or .docx is opened read-only and never saved. Comments and
tracked-change markup stay out of the PDF. Document properties are removed.
"""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

import pymupdf

from ekisui.errors import WordConvertError

# Word VBA constants. Hard-coded so the typelib does not have to be generated.
_WD_ALERTS_NONE = 0
_WD_DO_NOT_SAVE_CHANGES = 0
_WD_EXPORT_FORMAT_PDF = 17
_WD_EXPORT_OPTIMIZE_FOR_PRINT = 0
_WD_EXPORT_ALL_DOCUMENT = 0
_WD_EXPORT_DOCUMENT_CONTENT = 0
_WD_EXPORT_CREATE_NO_BOOKMARKS = 0
_WD_REVISIONS_VIEW_FINAL = 0

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
    try:
        _export_word(source, dest)
        _strip_pdf_metadata(dest)
    except WordConvertError:
        dest.unlink(missing_ok=True)
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise WordConvertError(_EXPORT_FAILED) from exc
    if not dest.is_file() or dest.stat().st_size < 8:
        dest.unlink(missing_ok=True)
        raise WordConvertError(_EXPORT_FAILED)
    return dest


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
    try:
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
    except Exception as exc:
        raise WordConvertError(_OPEN_FAILED) from exc
    try:
        _prepare_final_view(document)
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
        document.Close(SaveChanges=_WD_DO_NOT_SAVE_CHANGES)


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
    path = directory / f"{stem}.pdf"
    number = 2
    while path.exists():
        path = directory / f"{stem} ({number}).pdf"
        number += 1
    return path
