"""Mô hình dữ liệu nội bộ cho toàn bộ luồng chuyển đổi."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class Col(Enum):
    NGAY_HT = "ngay_hach_toan"
    NGAY_CT = "ngay_chung_tu"
    SO_CT = "so_chung_tu"
    DIEN_GIAI = "dien_giai"
    TAI_KHOAN = "tai_khoan"
    TK_DOI_UNG = "tk_doi_ung"
    PS_NO = "phat_sinh_no"
    PS_CO = "phat_sinh_co"


COLUMN_ORDER = [
    Col.NGAY_HT,
    Col.NGAY_CT,
    Col.SO_CT,
    Col.DIEN_GIAI,
    Col.TAI_KHOAN,
    Col.TK_DOI_UNG,
    Col.PS_NO,
    Col.PS_CO,
]

COLUMN_TITLES = {
    Col.NGAY_HT: "Ngày hạch toán",
    Col.NGAY_CT: "Ngày chứng từ",
    Col.SO_CT: "Số chứng từ",
    Col.DIEN_GIAI: "Diễn giải",
    Col.TAI_KHOAN: "Tài khoản",
    Col.TK_DOI_UNG: "TK đối ứng",
    Col.PS_NO: "Phát sinh Nợ",
    Col.PS_CO: "Phát sinh Có",
}


class RowKind(Enum):
    ENTRY = "but_toan"
    CARRY_IN = "so_trang_truoc_chuyen_sang"
    CARRY_OUT = "cong_chuyen_sang_trang_sau"
    GRAND_TOTAL = "tong_cong"
    HEADER = "tieu_de_cot"
    INFO = "thong_tin_loai"
    EMPTY = "dong_trong"
    UNKNOWN = "chua_ro"


class FileStatus(Enum):
    CHUA_XU_LY = "Chưa xử lý"
    DANG_CHUYEN_DOI = "Đang chuyển đổi"
    CAN_DOI_CHIEU = "Cần đối chiếu"
    DA_DOI_CHIEU = "Đã đối chiếu khớp PDF"
    DA_DUNG = "Đã dừng"
    LOI = "Lỗi – cần xử lý"


class AccountingCheck(Enum):
    CHUA_KIEM_TRA = "Chưa kiểm tra xong"
    CAN_DOI = "Cân đối"
    SAI_LECH_NGUON = "Có sai lệch trên PDF gốc"


class WarningLevel(Enum):
    EXTRACTION = "trich_xuat"      # chặn trạng thái Đã đối chiếu
    ACCOUNTING = "ke_toan"         # không chặn, giữ riêng
    INFO = "thong_tin"


@dataclass
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    def center(self):
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    def as_tuple(self):
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass
class CellValue:
    col: Col
    raw: str = ""
    value: object = None            # str | Decimal | datetime.date | None
    rect: Optional[Rect] = None
    confidence: Optional[float] = None
    source: str = "ocr"             # ocr | text_layer | nguoi_dung
    reviewed: bool = False
    confirmed: bool = False
    edited: bool = False
    original_value: object = None
    warnings: list = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.raw.strip() == ""


@dataclass
class SourceRow:
    page_index: int
    row_index: int
    kind: RowKind
    cells: dict = field(default_factory=dict)
    rect: Optional[Rect] = None
    printed_page: Optional[int] = None
    merged_from: list = field(default_factory=list)
    excluded_reason: str = ""
    confirmed: bool = False
    warnings: list = field(default_factory=list)

    def cell(self, col: Col) -> CellValue:
        return self.cells.setdefault(col, CellValue(col=col))

    @property
    def amount_no(self) -> Optional[Decimal]:
        v = self.cells.get(Col.PS_NO)
        return v.value if v and isinstance(v.value, Decimal) else None

    @property
    def amount_co(self) -> Optional[Decimal]:
        v = self.cells.get(Col.PS_CO)
        return v.value if v and isinstance(v.value, Decimal) else None


@dataclass
class WarningItem:
    code: str
    message: str
    level: WarningLevel
    page_index: Optional[int] = None
    row_index: Optional[int] = None
    col: Optional[Col] = None
    resolved: bool = False
    resolution: str = ""
    wid: int = 0


@dataclass
class PageResult:
    page_index: int
    printed_page: Optional[int] = None
    rows: list = field(default_factory=list)
    carry_in_no: Optional[Decimal] = None
    carry_in_co: Optional[Decimal] = None
    carry_out_no: Optional[Decimal] = None
    carry_out_co: Optional[Decimal] = None
    grand_total_no: Optional[Decimal] = None
    grand_total_co: Optional[Decimal] = None
    has_carry_in_row: bool = False
    has_carry_out_row: bool = False
    has_grand_total_row: bool = False
    confirmed: bool = False
    image_path: str = ""
    info_page: bool = False
    grid_xs: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def entry_rows(self):
        return [r for r in self.rows if r.kind == RowKind.ENTRY]

    def sum_no(self) -> Decimal:
        return sum((r.amount_no or Decimal(0) for r in self.entry_rows()), Decimal(0))

    def sum_co(self) -> Decimal:
        return sum((r.amount_co or Decimal(0) for r in self.entry_rows()), Decimal(0))


@dataclass
class ReconcileItem:
    name: str
    formula: str
    expected: Optional[Decimal]
    actual: Optional[Decimal]
    diff: Optional[Decimal]
    ok: bool
    applicable: bool
    note: str = ""


@dataclass
class FileResult:
    path: str
    sha256: str = ""
    page_count: int = 0
    pages: list = field(default_factory=list)
    status: FileStatus = FileStatus.CHUA_XU_LY
    accounting: AccountingCheck = AccountingCheck.CHUA_KIEM_TRA
    warnings: list = field(default_factory=list)
    reconcile: list = field(default_factory=list)
    processed_pages: int = 0
    stopped: bool = False
    error: str = ""
    draft_excel: str = ""
    final_excel: str = ""

    def entry_rows(self):
        sorted_pages = sorted(self.pages, key=lambda p: (p.printed_page if p.printed_page else (p.page_index + 1)))
        for p in sorted_pages:
            yield from p.entry_rows()

    def total_no(self) -> Decimal:
        return sum((r.amount_no or Decimal(0) for r in self.entry_rows()), Decimal(0))

    def total_co(self) -> Decimal:
        return sum((r.amount_co or Decimal(0) for r in self.entry_rows()), Decimal(0))

    def open_extraction_warnings(self):
        return [w for w in self.warnings if w.level == WarningLevel.EXTRACTION and not w.resolved]

    def unconfirmed_pages(self):
        return [p for p in self.pages if not p.confirmed]
