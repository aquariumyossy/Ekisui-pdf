from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Category(Enum):
    PHRASE = "phrase"
    REGION = "region"
    PERSON = "person"
    COMPANY = "company"
    PHONE = "phone"
    EMAIL = "email"
    ACCOUNT = "account"
    POSTAL = "postal"
    ADDRESS = "address"
    ALNUM = "alnum"


CATEGORY_LABEL = {
    Category.PHRASE: "語句",
    Category.REGION: "範囲",
    Category.PERSON: "人名",
    Category.COMPANY: "会社",
    Category.PHONE: "電話番号",
    Category.EMAIL: "メール",
    Category.ACCOUNT: "口座番号",
    Category.POSTAL: "郵便番号",
    Category.ADDRESS: "住所",
    Category.ALNUM: "英数字",
}


class Action(Enum):
    BLACKOUT = "blackout"
    REPLACE = "replace"


# Names and companies are replaced. Contact points are blacked out.
# A dragged region defaults to blackout; a typed phrase defaults to replace.
DEFAULT_ACTION = {
    Category.PERSON: Action.REPLACE,
    Category.COMPANY: Action.REPLACE,
    Category.PHRASE: Action.REPLACE,
    Category.REGION: Action.BLACKOUT,
    Category.PHONE: Action.BLACKOUT,
    Category.EMAIL: Action.BLACKOUT,
    Category.ACCOUNT: Action.BLACKOUT,
    Category.POSTAL: Action.BLACKOUT,
    Category.ADDRESS: Action.REPLACE,
    Category.ALNUM: Action.BLACKOUT,
}


class MatchKind(Enum):
    EXACT = "exact"
    FUZZY = "fuzzy"


class TextSource(Enum):
    NATIVE = "native"
    OCR = "ocr"
    CORRECTED = "corrected"


class PageKind(Enum):
    NATIVE = "native"
    SCANNED = "scanned"


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def union(self, other: Rect) -> Rect:
        return Rect(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def pad(self, dx: float, dy: float) -> Rect:
        return Rect(self.x0 - dx, self.y0 - dy, self.x1 + dx, self.y1 + dy)

    def intersects(self, other: Rect) -> bool:
        return (
            self.x0 < other.x1
            and other.x0 < self.x1
            and self.y0 < other.y1
            and other.y0 < self.y1
        )

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def intersection(self, other: Rect) -> Rect | None:
        rect = Rect(
            max(self.x0, other.x0),
            max(self.y0, other.y0),
            min(self.x1, other.x1),
            min(self.y1, other.y1),
        )
        if rect.width <= 0 or rect.height <= 0:
            return None
        return rect

    def clip(self, bounds: Rect) -> Rect:
        rect = Rect(
            min(max(self.x0, bounds.x0), bounds.x1),
            min(max(self.y0, bounds.y0), bounds.y1),
            min(max(self.x1, bounds.x0), bounds.x1),
            min(max(self.y1, bounds.y0), bounds.y1),
        )
        return rect

    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


def iou(a: Rect, b: Rect) -> float:
    inter = a.intersection(b)
    if inter is None:
        return 0.0
    union = a.area() + b.area() - inter.area()
    if union <= 0:
        return 0.0
    return inter.area() / union


@dataclass(frozen=True)
class Settings:
    fuzzy_threshold: float = 0.60
    deskew: bool = True
    review_below: float = 0.80
    align_chars: int = 5
    ocr_dpi: int = 200

    def __post_init__(self) -> None:
        if not 0.50 <= self.fuzzy_threshold <= 0.90:
            raise ValueError("ゆるい一致のしきい値は 50% から 90% です")
        if self.align_chars < 1:
            raise ValueError("枠の文字数が不正です")


@dataclass(frozen=True)
class SaveOptions:
    align_box_width: bool = True
    strip_metadata: bool = True
    export_log: bool = True
    include_original_terms: bool = False
    export_replacement_table: bool = False


@dataclass(frozen=True)
class TextLine:
    id: str
    page_index: int
    text: str
    bbox: Rect
    confidence: float
    source: TextSource
    chars: tuple[Rect, ...] = ()
    # False for a printer's invisible text. Those lines are not copied onto the
    # page we save after OCR.
    visible: bool = True


@dataclass(frozen=True)
class Page:
    index: int
    width: float
    height: float
    kind: PageKind
    lines: tuple[TextLine, ...]
    image_path: str | None = None
    dpi: int = 72
    rotation: int = 0
    skew: float = 0.0
    correction_label: str | None = None
    source_index: int = 0
    # Quarter turn applied before the small skew. 180° from the line model is
    # only in ``rotation``, and it happens after the skew.
    quarter: int = 0
    source_width: float = 0.0
    source_height: float = 0.0


@dataclass(frozen=True)
class Document:
    source_path: str
    pages: tuple[Page, ...]
    # PDF bytes the view, OCR, and save read. Empty until a confirmation
    # burns redactions into a temp file. ``source_path`` stays the name the
    # user opened, and that file is never modified.
    working_path: str | None = None

    def page(self, index: int) -> Page:
        return self.pages[index]


@dataclass(frozen=True)
class Hit:
    page_index: int
    surface: str
    bbox: Rect
    kind: MatchKind
    score: float
    explanation: str
    line_ids: tuple[str, ...]
    ocr_like: bool = False
    # Every automatic hit starts checked, including a bare prefecture.
    checked: bool = True


@dataclass(frozen=True)
class Glyph:
    strict: str
    loose: str
    page_index: int
    line_id: str
    bbox: Rect
    src_index: int


@dataclass(frozen=True)
class PageIndex:
    page_index: int
    glyphs: tuple[Glyph, ...]
    strict: str
    loose: str
    paragraphs: tuple[tuple[int, int], ...]
    lines: dict[str, TextLine]


@dataclass(frozen=True)
class Span:
    page_index: int
    start: int
    end: int
    surface: str
    bbox: Rect
    line_ids: tuple[str, ...]
    category: Category
    checked: bool = True
    # None keeps the category default. Public-body addresses override it to blackout.
    action: Action | None = None
    # Glyph indexes when the span is not one contiguous run (a name split by a gap).
    indexes: tuple[int, ...] = ()
