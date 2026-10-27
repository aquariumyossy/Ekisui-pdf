from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Action(str, Enum):
    REDACT = "redact"
    PSEUDONYM = "pseudonym"


@dataclass(frozen=True)
class Rect:
    """PDF の点座標。原点はページ左上、y は下向き（PyMuPDF と同じ）。"""

    x0: float
    y0: float
    x1: float
    y1: float

    def normalized(self) -> Rect:
        return Rect(
            min(self.x0, self.x1),
            min(self.y0, self.y1),
            max(self.x0, self.x1),
            max(self.y0, self.y1),
        )

    @property
    def width(self) -> float:
        rect = self.normalized()
        return rect.x1 - rect.x0

    @property
    def height(self) -> float:
        rect = self.normalized()
        return rect.y1 - rect.y0

    def intersects(self, other: Rect) -> bool:
        this = self.normalized()
        that = other.normalized()
        return (
            this.x0 < that.x1
            and this.x1 > that.x0
            and this.y0 < that.y1
            and this.y1 > that.y0
        )

    def clamp(self, bounds: Rect) -> Rect:
        limit = bounds.normalized()
        rect = self.normalized()
        x0 = min(max(rect.x0, limit.x0), limit.x1)
        y0 = min(max(rect.y0, limit.y0), limit.y1)
        x1 = min(max(rect.x1, limit.x0), limit.x1)
        y1 = min(max(rect.y1, limit.y0), limit.y1)
        if x1 < x0:
            x0 = x1
        if y1 < y0:
            y0 = y1
        return Rect(x0, y0, x1, y1)

    def with_width(self, width: float, page_width: float) -> Rect:
        rect = self.normalized()
        width = max(float(width), 1.0)
        center = (rect.x0 + rect.x1) / 2
        x0 = center - width / 2
        x1 = center + width / 2
        if x0 < 0:
            x1 -= x0
            x0 = 0.0
        if x1 > page_width:
            shift = x1 - page_width
            x0 = max(0.0, x0 - shift)
            x1 = page_width
        return Rect(x0, rect.y0, x1, rect.y1)


@dataclass(frozen=True)
class OcrLine:
    page_index: int
    text: str
    rect: Rect
    confidence: float = 1.0
    line_id: str = ""
    # 文字数と同じ長さのときだけ使う。等幅で割った位置は漢字と英字の混在でずれる。
    char_rects: tuple[Rect, ...] = ()


@dataclass
class Selection:
    id: str
    page_index: int
    rect: Rect
    matched_text: str
    action: Action = Action.REDACT
    pseudonym: str = ""
    source: str = "manual"
    line_id: str = ""
    char_start: int = -1
    char_end: int = -1


@dataclass
class ReplacementEntry:
    term: str
    pseudonym: str


@dataclass(frozen=True)
class SaveOptions:
    strip_metadata: bool = True
    fixed_width: bool = False
    fixed_width_pt: float = 160.0


@dataclass(frozen=True)
class TextInsert:
    rect: Rect
    text: str
    visible: bool


@dataclass(frozen=True)
class PagePlan:
    redactions: tuple[Rect, ...]
    inserts: tuple[TextInsert, ...]


@dataclass(frozen=True)
class Leftover:
    term: str
    page_index: int
    where: str

    def describe(self) -> str:
        place = "ファイル全体" if self.page_index < 0 else f"{self.page_index + 1}ページ"
        kinds = {
            "text": "テキスト",
            "bytes": "ファイル内のバイト列",
            "outline": "しおり",
            "metadata": "文書情報",
            "annot": "注釈",
            "label": "ページラベル",
        }
        return f"{place}: 「{self.term}」（{kinds.get(self.where, self.where)}）"


@dataclass(frozen=True)
class VerifyReport:
    passed: bool
    leftovers: tuple[Leftover, ...]
    checked_terms: tuple[str, ...]

    @property
    def summary(self) -> str:
        if not self.checked_terms:
            return "確認する文字列がありません。選択に文字が入っていないため、残存は調べていません。"
        if self.passed:
            return "合格。選んだ元の文字列は、保存したPDFのテキストから見つかりませんでした。"
        return f"残存あり。{len(self.leftovers)}件見つかりました。"


@dataclass(frozen=True)
class ExportResult:
    report: VerifyReport
    redaction_count: int
    pseudonym_count: int
    output_path: str
    applied_box_width: float | None
