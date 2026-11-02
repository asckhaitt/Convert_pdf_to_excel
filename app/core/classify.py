"""Phân loại dòng nguồn: bút toán, chuyển trang, tổng cộng, tiêu đề, chưa rõ."""
from __future__ import annotations

import unicodedata

from .model import Col, RowKind


def fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower().strip()


# nhãn “Tổng cộng” in mờ nên OCR hay nhầm chữ thành chữ số (T→1, o→0...);
# ánh xạ ngược để vẫn nhận ra nhãn khi đối chiếu
_CONFUSE = str.maketrans({"0": "o", "1": "t", "2": "z", "3": "e", "4": "a",
                          "5": "s", "6": "b", "7": "t", "8": "b", "9": "g"})
TOTAL_LABELS = ("tong cong", "tong so", "tong phat sinh", "cong cuoi")


def label_norm(s: str) -> str:
    s = fold(s).translate(_CONFUSE)
    return " ".join("".join(ch for ch in s if ch.isalnum() or ch == " ").split())


def is_total_label(s: str) -> bool:
    ln = label_norm(s)
    return bool(ln) and any(t in ln for t in TOTAL_LABELS)


def classify_row(cells_text: dict) -> RowKind:
    dg = fold(cells_text.get(Col.DIEN_GIAI, ""))
    # Tiêu đề bảng: cột diễn giải có chữ "diễn giải"
    if ("dien giai" in dg and len(dg) <= 25) or ("dien giai" in dg and "tai khoan" in fold(cells_text.get(Col.TAI_KHOAN, ""))):
        return RowKind.HEADER
    ht = fold(cells_text.get(Col.NGAY_HT, ""))
    so_ct = fold(cells_text.get(Col.SO_CT, ""))
    if "hach toan" in ht or "chung tu" in ht or "chung tu" in so_ct or "so hieu" in so_ct:
        return RowKind.HEADER
    # Dòng số thứ tự cột: A, B, C, D, E, 1, 2, 3, 4, 5, 6, 7, 8
    subhead_tokens = {"a", "b", "c", "d", "e", "1", "2", "3", "4", "5", "6", "7", "8"}
    non_empty = [fold(cells_text.get(c, "")) for c in Col if cells_text.get(c, "").strip()]
    if non_empty and all(t in subhead_tokens for t in non_empty) and not any(len(t) > 2 for t in non_empty):
        return RowKind.HEADER

    dg_compact = dg.replace(" ", "")
    if ("trang truoc" in dg or "trangtruoc" in dg_compact
            or ("truoc" in dg_compact and ("chuyen" in dg_compact or "sang" in dg_compact))):
        return RowKind.CARRY_IN
    if ("chuyen sang trang sau" in dg or "trang sau" in dg or "trangsau" in dg_compact
            or ("sau" in dg_compact and ("chuyen" in dg_compact or "sang" in dg_compact))):
        return RowKind.CARRY_OUT
    if is_total_label(dg) or "tong cong" in dg or "cong cuoi" in dg:
        return RowKind.GRAND_TOTAL
    if cells_text.get("__left_label__"):
        # nhãn in tràn các cột trái, có tiền cả hai bên nhưng đọc không ra chữ:
        # không dám coi là bút toán, để người soát xem ảnh và phân loại lại
        return RowKind.UNKNOWN
    values = [cells_text.get(c, "").strip() for c in Col]
    if not any(values):
        return RowKind.EMPTY
    has_money = bool(cells_text.get(Col.PS_NO, "").strip() or cells_text.get(Col.PS_CO, "").strip())
    has_key = bool(cells_text.get(Col.NGAY_HT, "").strip() or cells_text.get(Col.SO_CT, "").strip()
                   or cells_text.get(Col.TAI_KHOAN, "").strip())
    if has_money or has_key:
        return RowKind.ENTRY
    if dg:
        return RowKind.UNKNOWN  # chỉ có diễn giải: nghi dòng nối của ô trên
    return RowKind.UNKNOWN


EXCLUDE_REASON = {
    RowKind.HEADER: "Tiêu đề cột lặp lại",
    RowKind.INFO: "Thông tin doanh nghiệp / số trang",
    RowKind.EMPTY: "Dòng trống",
    RowKind.CARRY_IN: "Số trang trước chuyển sang (chỉ giữ ở sheet Đối soát)",
    RowKind.CARRY_OUT: "Cộng chuyển sang trang sau (chỉ giữ ở sheet Đối soát)",
    RowKind.GRAND_TOTAL: "Tổng cộng toàn sổ (chỉ giữ ở sheet Đối soát)",
}
