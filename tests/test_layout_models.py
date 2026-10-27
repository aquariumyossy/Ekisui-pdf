"""The layout ONNX models are not part of text extraction, search, or redaction."""

import importlib.abc
import importlib.machinery
import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

import pymupdf

_ROOT = Path(__file__).resolve().parents[1]


def test_app_source_does_not_call_layout_or_table_detection():
    needles = []
    for path in list((_ROOT / "src").rglob("*.py")) + [_ROOT / "ekisui.spec"]:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("import pymupdf.layout") or stripped.startswith("from pymupdf.layout"):
                needles.append(f"{path}:{lineno}")
            if stripped.startswith("import pymupdf4llm") or stripped.startswith("from pymupdf4llm"):
                needles.append(f"{path}:{lineno}")
            if "find_tables(" in line or ".get_layout(" in line:
                needles.append(f"{path}:{lineno}")
    assert needles == []


def test_text_search_and_redaction_do_not_call_the_layout_hook():
    get_text = inspect.getsource(pymupdf.Page.get_text)
    search_for = inspect.getsource(pymupdf.Page.search_for)
    apply_redactions = inspect.getsource(pymupdf.Page.apply_redactions)
    get_layout = inspect.getsource(pymupdf.Page.get_layout)
    find_tables = inspect.getsource(pymupdf.table.find_tables)
    assert "_get_layout" not in get_text
    assert "_get_layout" not in search_for
    assert "_get_layout" not in apply_redactions
    assert "_get_layout" in get_layout
    assert "get_layout(" in find_tables


def test_those_apis_open_no_layout_model(tmp_path):
    script = textwrap.dedent(
        """
        from pathlib import Path
        import onnxruntime as ort

        opened = []
        original = ort.InferenceSession

        class Counting(original):
            def __init__(self, model_path, *args, **kwargs):
                opened.append(Path(str(model_path)).name)
                super().__init__(model_path, *args, **kwargs)

        ort.InferenceSession = Counting
        import pymupdf
        imported = list(opened)
        opened.clear()
        layout_calls = {"n": 0}
        if pymupdf._get_layout is not None:
            inner = pymupdf._get_layout

            def wrapped(*args, **kwargs):
                layout_calls["n"] += 1
                return inner(*args, **kwargs)

            pymupdf._get_layout = wrapped
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "hello layout")
        text = page.get_text()
        hits = page.search_for("hello")
        page.add_redact_annot(pymupdf.Rect(72, 60, 200, 90))
        redacted = page.apply_redactions()
        doc.close()
        print("IMPORT_MODELS", ",".join(imported))
        print("API_MODELS", ",".join(opened))
        print("LAYOUT_CALLS", layout_calls["n"])
        print("GET_TEXT_OK", "hello" in text)
        print("SEARCH_OK", len(hits) > 0)
        print("REDACT_OK", redacted is not None)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output

    def field(name: str) -> str:
        prefix = name + " "
        for line in result.stdout.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :]
        raise AssertionError(f"{name} missing\n{output}")

    assert field("API_MODELS") == ""
    assert field("LAYOUT_CALLS") == "0"
    assert field("GET_TEXT_OK") == "True"
    assert field("SEARCH_OK") == "True"
    assert field("REDACT_OK") == "True"


def test_missing_layout_package_still_extracts_searches_and_redacts(tmp_path):
    script = textwrap.dedent(
        """
        import importlib.abc
        import importlib.machinery
        import sys

        class Missing(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path, target=None):
                if fullname == "pymupdf.layout" or fullname.startswith("pymupdf.layout."):
                    return importlib.machinery.ModuleSpec(fullname, self, is_package=False)
                return None

            def create_module(self, spec):
                return None

            def exec_module(self, module):
                raise ModuleNotFoundError(module.__name__)

        sys.meta_path.insert(0, Missing())
        import pymupdf
        assert "pymupdf.layout" not in sys.modules
        assert pymupdf._get_layout is None
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 80), "依頼者は山田太郎です", fontname="japan", fontsize=16)
        text = "".join(page.get_text().split())
        hits = page.search_for("太郎")
        page.add_redact_annot(hits[0])
        page.apply_redactions()
        after = "".join(page.get_text().split())
        doc.close()
        assert "依頼者" in text and "太郎" in text
        assert "太郎" not in after and "依頼者" in after
        print("BLOCKED_OK")
        print("BEFORE", text)
        print("AFTER", after)
        """
    )
    env = os_env_without_layout_preload()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
        env=env,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "BLOCKED_OK" in result.stdout


def os_env_without_layout_preload():
    import os

    env = os.environ.copy()
    env.pop("PYMUPDF_LAYOUT", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env
