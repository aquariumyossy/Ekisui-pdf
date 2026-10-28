"""Turn docs/使い方.md into a single HTML page for the installer."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inline(text: str) -> str:
    """Bold and `code`. Backticks are tags, not characters on the page."""
    stripped = text.strip()
    parts: list[str] = []
    cursor = 0
    for match in re.finditer(r"`([^`]+)`", stripped):
        parts.append(_emphasis(stripped[cursor:match.start()]))
        parts.append(f"<code>{html.escape(match.group(1))}</code>")
        cursor = match.end()
    parts.append(_emphasis(stripped[cursor:]))
    return "".join(parts)


def _emphasis(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text))


def render_guide(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").split("\n")
    body: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("### "):
            body.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("- "):
            items: list[str] = []
            while index < len(lines) and lines[index].startswith("- "):
                items.append(f"<li>{inline(lines[index][2:])}</li>")
                index += 1
            body.append("<ul>\n" + "\n".join(items) + "\n</ul>")
            continue
        elif line.startswith("!["):
            match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", line.strip())
            if match is None:
                raise ValueError(f"image line is not a simple link: {line}")
            alt, src = match.group(1), match.group(2)
            body.append(f'<p><img alt="{html.escape(alt)}" src="{html.escape(src)}"></p>')
        else:
            parts = [line.strip()]
            index += 1
            while index < len(lines) and lines[index].strip() and not lines[index].startswith(("#", "-", "!")):
                parts.append(lines[index].strip())
                index += 1
            body.append(f"<p>{inline(' '.join(parts))}</p>")
            continue
        index += 1
    inner = "\n".join(body)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>使い方ガイド — ekisui-pdf</title>
<style>
body {{
  font-family: "Yu Gothic UI", "Yu Gothic", "Hiragino Sans", "Noto Sans CJK JP", sans-serif;
  line-height: 1.75;
  max-width: 880px;
  margin: 32px auto;
  padding: 0 20px 48px;
  color: #1b1b1b;
  background: #fff;
}}
img {{ max-width: 100%; height: auto; border: 1px solid #d0d0d0; }}
code {{
  font-family: Consolas, "Cascadia Mono", "Yu Gothic UI", monospace;
  background: #f3f3f3;
  padding: 0 0.25em;
}}
h1 {{ font-size: 28px; }}
h2 {{ font-size: 22px; margin-top: 2.2em; padding-bottom: 4px; border-bottom: 1px solid #e6e6e6; }}
h3 {{ font-size: 18px; margin-top: 1.6em; }}
</style>
</head>
<body>
{inner}
</body>
</html>
"""


def main() -> None:
    source = ROOT / "docs" / "使い方.md"
    target = ROOT / "docs" / "使い方.html"
    target.write_text(render_guide(source.read_text(encoding="utf-8")), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    sys.exit(main())
