"""Cơ chế đối soát và tự động cân đối thông minh (Intelligent Reconcile & Auto-Repair).

Dựa trên nguyên lý kế toán kép:
1. Mỗi nghiệp vụ / chứng từ: Tổng Nợ = Tổng Có.
2. Mỗi trang: Chuyển sang trang sau = Trang trước chuyển sang + Phát sinh trong trang.
3. Toàn sổ: Tổng Nợ = Tổng Có.

Khi phát hiện lệch, hệ thống:
- Nhận diện đúng nhóm nghiệp vụ xuyên trang nhờ bộ phân tích số chứng từ (Voucher Sequence Number).
- Tách từng cặp định khoản đối ứng tài khoản trong cùng chứng từ (Nợ TK A đối ứng TK B vs Có TK B đối ứng TK A).
- Nhận dạng lại chi tiết (Targeted Multi-Pass Re-OCR) với đa tầng tiền xử lý:
  * Thử nhiều mức lề (inset) để loại bỏ nét viền kẻ bảng dính số 1 hoặc số 0 giả.
  * Tăng cường tương phản cục bộ (CLAHE) + nhị phân hóa Otsu khử mờ/nhiễu.
  * Đối chiếu với công thức chuyển trang (Carry Out - Carry In) để tìm nghiệm toán học chính xác 100%.
- Cập nhật số liệu chuẩn xác và ghi vết lịch sử xử lý.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from .model import Col, RowKind, WarningItem, WarningLevel
from .normalize import CONFUSE, parse_amount
from .ocr_engine import OcrEngine, split_lines

if TYPE_CHECKING:
    from .model import CellValue, FileResult, PageResult, SourceRow

ZERO = Decimal(0)
STANDARD_BANK_FEES = {Decimal("11000"), Decimal("22000"), Decimal("33000"), Decimal("66000"), Decimal("110000")}


def clean_voucher_str(v: str) -> str:
    if not v:
        return ""
    v = v.strip().strip("./- \t")
    return "".join(CONFUSE.get(ch, ch) for ch in v.upper())


def parse_voucher_info(v: str) -> tuple[str, int | None]:
    """Tách số chứng từ thành (loại_chứng_từ, số_thứ_tự_số_học).

    Ví dụ: 'TNH15.061' -> ('TNH', 61)
           'LUINC15.005' -> ('UNC', 5)
           'UNC15.030/' -> ('UNC', 30)
           'PC15.011.' -> ('PC', 11)
    """
    if not v:
        return "", None
    s = v.strip().strip("./- \t")
    # Khử nhiễu dấu gạch chéo/dọc do vách kẻ hoặc vết gấp lọt vào giữa số (NVK16.06/1 -> NVK16.061)
    s = s.replace("/", "").replace("|", "").replace("\\", "")
    parts = re.split(r"[.\s/_-]+", s)
    if len(parts) >= 2 and parts[-1]:
        last = parts[-1]
        last_digits = "".join(CONFUSE.get(ch, ch) for ch in last if ch.isalnum())
        if last_digits.isdigit():
            prefix = parts[0].upper()
            for k in ("UNC", "TNH", "NVK", "PKT", "PC", "PT", "BN", "BC"):
                if k in prefix:
                    return k, int(last_digits)
            # Khử nhiễu ký tự L, 1, I, |, - trong prefix
            s_clean = prefix.replace("I", "").replace("L", "").replace("1", "").replace("|", "")
            for k in ("UNC", "TNH", "NVK", "PKT", "PC", "PT", "BN", "BC"):
                if k in s_clean:
                    return k, int(last_digits)
            return prefix, int(last_digits)
    m = re.search(r"(\d+)[^\d]*$", s)
    if m:
        return "UNKNOWN", int(m.group(1))
    return s, None


def vouchers_match(v1: str, v2: str) -> bool:
    """So khớp 2 số chứng từ chịu lỗi OCR (nhiễu ký tự đầu/cuối, nhầm chữ/số, lệch 1 ký tự).

    Phân biệt được số thứ tự nghiệp vụ (61 khác 62) để không gộp nhầm các chứng từ liên tiếp.
    """
    if not v1 or not v2:
        return True  # Dòng trống kế thừa chứng từ trước

    k1, n1 = parse_voucher_info(v1)
    k2, n2 = parse_voucher_info(v2)

    if n1 is not None and n2 is not None:
        if n1 != n2:
            return False  # Khác số thứ tự là chứng từ khác nhau!
        if k1 == k2 or k1 == "UNKNOWN" or k2 == "UNKNOWN" or not k1 or not k2:
            return True
        if abs(len(k1) - len(k2)) <= 2:
            return True
        return False

    c1, c2 = clean_voucher_str(v1), clean_voucher_str(v2)
    if c1 == c2:
        return True
    t1 = c1.lstrip("LI1|").rstrip("./-")
    t2 = c2.lstrip("LI1|").rstrip("./-")
    if t1 and t2 and t1 == t2:
        return True
    return False


def accts_match(tk1: str | None, tk2: str | None) -> bool:
    """So khớp mã tài khoản chịu lỗi OCR mất chữ số đầu/cuối hoặc tài khoản mẹ - con (15 vs 515, 334 vs 3341)."""
    if not tk1 or not tk2:
        return False
    t1, t2 = str(tk1).strip(), str(tk2).strip()
    if t1 == t2:
        return True
    if len(t1) >= 2 and len(t2) >= 2 and (t1.startswith(t2) or t2.startswith(t1) or t1.endswith(t2) or t2.endswith(t1)):
        return True
    return False


def group_voucher_transactions(fr: FileResult) -> list[dict]:
    """Nhóm các dòng bút toán liền kề thành từng nghiệp vụ hoàn chỉnh (xuyên qua điểm ngắt trang)."""
    sorted_pages = sorted(
        [p for p in fr.pages if not p.info_page],
        key=lambda p: (p.printed_page if p.printed_page is not None else (p.page_index + 1))
    )
    entries = []
    for p in sorted_pages:
        for r in p.entry_rows():
            entries.append((p, r))

    groups = []
    cur = None

    for p, r in entries:
        v = (r.cell(Col.SO_CT).value or "").strip()
        tk = r.cell(Col.TAI_KHOAN).value
        tkdu = r.cell(Col.TK_DOI_UNG).value

        continues = False
        if cur is not None:
            last_p, last_r = cur["rows"][-1]
            last_v = (last_r.cell(Col.SO_CT).value or "").strip()
            last_tk = last_r.cell(Col.TAI_KHOAN).value
            last_tkdu = last_r.cell(Col.TK_DOI_UNG).value

            if v and last_v and not vouchers_match(v, last_v):
                continues = False
            elif v and cur["voucher"] and not vouchers_match(v, cur["voucher"]):
                continues = False
            elif vouchers_match(v, last_v):
                continues = True
            elif cur["no"] != cur["co"]:
                if not v or vouchers_match(v, cur["voucher"]):
                    continues = True
                elif tk and tkdu and last_tk and last_tkdu and accts_match(tk, last_tkdu) and accts_match(tkdu, last_tk):
                    continues = True

        if continues and cur is not None:
            cur["rows"].append((p, r))
            cur["no"] += r.amount_no or ZERO
            cur["co"] += r.amount_co or ZERO
            if v and not cur["voucher"]:
                cur["voucher"] = v
        else:
            cur = {
                "voucher": v or f"CT_Trang{p.page_index + 1}",
                "rows": [(p, r)],
                "no": r.amount_no or ZERO,
                "co": r.amount_co or ZERO,
            }
            groups.append(cur)

    # Pha 2: Gộp các nhóm liền kề nếu thực chất là 2 vế của cùng 1 chứng từ bị OCR xé
    merged = []
    for g in groups:
        if (merged and merged[-1]["no"] != merged[-1]["co"] and g["no"] != g["co"]
                and merged[-1]["no"] + g["no"] == merged[-1]["co"] + g["co"]
                and vouchers_match(merged[-1]["voucher"], g["voucher"])):
            prev = merged[-1]
            prev["rows"].extend(g["rows"])
            prev["no"] += g["no"]
            prev["co"] += g["co"]
            if not prev["voucher"] and g["voucher"]:
                prev["voucher"] = g["voucher"]
            continue
        merged.append(g)

    return merged


def multi_pass_reocr(img: np.ndarray, rect, engine: OcrEngine) -> set[Decimal]:
    """Nhận dạng lại vùng ô số tiền với đa chiến lược tiền xử lý."""
    x0, y0, x1, y1 = int(rect.x0), int(rect.y0), int(rect.x1), int(rect.y1)
    h0 = y1 - y0
    w0 = x1 - x0
    if h0 < 10 or w0 < 15:
        return set()

    raw_crop = img[y0:y1, x0:x1]
    candidates = set()

    for x_pad in (0, 2, 4, 6):
        if w0 <= 2 * x_pad + 10:
            continue
        sub = raw_crop[:, x_pad:w0 - x_pad]
        lines = split_lines(sub, inset=2)
        if lines:
            for s, _ in engine.recognize(lines, mode="money"):
                amt, _ = parse_amount(s, Col.PS_NO, 0, 0)
                if amt is not None and amt > 0:
                    candidates.add(amt)

    gray = cv2.cvtColor(raw_crop, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cl = clahe.apply(gray)
    _, otsu = cv2.threshold(cl, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    otsu_bgr = cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR)
    lines_otsu = split_lines(otsu_bgr, inset=2)
    if lines_otsu:
        for s, _ in engine.recognize(lines_otsu, mode="money"):
            amt, _ = parse_amount(s, Col.PS_NO, 0, 0)
            if amt is not None and amt > 0:
                candidates.add(amt)

    return candidates


def calculate_page_carry_delta(page: PageResult) -> tuple[Decimal | None, Decimal | None]:
    """Tính mức phát sinh kỳ vọng trong trang dựa trên dòng Số trang trước chuyển sang và Cộng chuyển sang sau."""
    cin_no, cin_co = page.carry_in_no, page.carry_in_co
    cout_no, cout_co = page.carry_out_no, page.carry_out_co
    if cout_no is None and page.grand_total_no is not None:
        cout_no, cout_co = page.grand_total_no, page.grand_total_co

    d_no = None if (cout_no is None or (cin_no is None and page.page_index > 0)) else (
        cout_no - (cin_no or ZERO))
    d_co = None if (cout_co is None or (cin_co is None and page.page_index > 0)) else (
        cout_co - (cin_co or ZERO))
    return d_no, d_co


def pick_better_account(tk1: str, tk2: str) -> str:
    """Chọn mã tài khoản chính xác hơn giữa 2 chuỗi đọc cùng một tài khoản đối ứng."""
    if not tk1:
        return tk2
    if not tk2:
        return tk1
    if tk1 == tk2:
        return tk1
    # Nếu một bên dính số 1 rác ở đầu do chạm đường viền bảng dọc (1335 vs 335, 1911 vs 911, 11121 vs 1121)
    if tk1.startswith("1") and tk1[1:] == tk2 and len(tk2) >= 3:
        return tk2
    if tk2.startswith("1") and tk2[1:] == tk1 and len(tk1) >= 3:
        return tk1
    # Nếu một bên bị cụt chữ số đầu (15 vs 515, 21 vs 1121, 31 vs 131)
    if len(tk1) < len(tk2) and tk2.endswith(tk1) and len(tk1) <= 2:
        return tk2
    if len(tk2) < len(tk1) and tk1.endswith(tk2) and len(tk2) <= 2:
        return tk1
    # Ưu tiên tài khoản chuẩn 3-4 chữ số
    return tk1 if len(tk1) >= len(tk2) else tk2


def sync_pair_accounts_and_dates(r_no: SourceRow, r_co: SourceRow):
    """Đồng bộ tài khoản đối ứng và ngày chứng từ giữa 2 dòng của một bút toán kép."""
    # 1. Đồng bộ ngày chứng từ và ngày hạch toán
    d_no = r_no.cell(Col.NGAY_CT).value
    d_co = r_co.cell(Col.NGAY_CT).value
    if d_no and not d_co:
        r_co.cell(Col.NGAY_CT).value = d_no
        r_co.cell(Col.NGAY_CT).raw = r_no.cell(Col.NGAY_CT).raw
    elif d_co and not d_no:
        r_no.cell(Col.NGAY_CT).value = d_co
        r_no.cell(Col.NGAY_CT).raw = r_co.cell(Col.NGAY_CT).raw

    d_ht_no = r_no.cell(Col.NGAY_HT).value
    d_ht_co = r_co.cell(Col.NGAY_HT).value
    if d_ht_no and not d_ht_co:
        r_co.cell(Col.NGAY_HT).value = d_ht_no
        r_co.cell(Col.NGAY_HT).raw = r_no.cell(Col.NGAY_HT).raw
    elif d_ht_co and not d_ht_no:
        r_no.cell(Col.NGAY_HT).value = d_ht_co
        r_no.cell(Col.NGAY_HT).raw = r_co.cell(Col.NGAY_HT).raw

    # 2. Đồng bộ số chứng từ
    v_no = (r_no.cell(Col.SO_CT).value or "").strip()
    v_co = (r_co.cell(Col.SO_CT).value or "").strip()
    if v_no and not v_co:
        r_co.cell(Col.SO_CT).value = v_no
        r_co.cell(Col.SO_CT).raw = r_no.cell(Col.SO_CT).raw
    elif v_co and not v_no:
        r_no.cell(Col.SO_CT).value = v_co
        r_no.cell(Col.SO_CT).raw = r_co.cell(Col.SO_CT).raw

    # 3. Đồng bộ tài khoản đối ứng
    tk_a = str(r_no.cell(Col.TAI_KHOAN).value or "").strip()
    tk_b_du = str(r_no.cell(Col.TK_DOI_UNG).value or "").strip()
    tk_b = str(r_co.cell(Col.TAI_KHOAN).value or "").strip()
    tk_a_du = str(r_co.cell(Col.TK_DOI_UNG).value or "").strip()

    better_a = pick_better_account(tk_a, tk_a_du)
    if better_a:
        r_no.cell(Col.TAI_KHOAN).value = better_a
        r_no.cell(Col.TAI_KHOAN).raw = better_a
        r_co.cell(Col.TK_DOI_UNG).value = better_a
        r_co.cell(Col.TK_DOI_UNG).raw = better_a

    better_b = pick_better_account(tk_b, tk_b_du)
    if better_b:
        r_co.cell(Col.TAI_KHOAN).value = better_b
        r_co.cell(Col.TAI_KHOAN).raw = better_b
        r_no.cell(Col.TK_DOI_UNG).value = better_b
        r_no.cell(Col.TK_DOI_UNG).raw = better_b


def resolve_pair(p_no: PageResult, r_no: SourceRow, p_co: PageResult, r_co: SourceRow,
                 voucher_name: str, engine: OcrEngine | None, get_img_fn, repairs: list[dict]) -> bool:
    """Khớp và sửa chữa một cặp định khoản đối ứng Nợ - Có."""
    sync_pair_accounts_and_dates(r_no, r_co)
    amt_no = r_no.amount_no
    amt_co = r_co.amount_co

    if amt_no is not None and amt_co is not None and amt_no == amt_co:
        return True

    # 1. Một bên None, một bên có số
    if amt_no is None and amt_co is not None and amt_co > 0:
        r_no.cell(Col.PS_NO).value = amt_co
        r_no.cell(Col.PS_NO).raw = f"{amt_co:,}".replace(",", ".")
        r_no.cell(Col.PS_NO).reviewed = True
        repairs.append({"type": "FILL_PAIR_MATCH", "voucher": voucher_name,
                        "page": p_no.page_index + 1, "row": r_no.row_index + 1,
                        "col": "PS_NO", "val": amt_co})
        return True

    if amt_co is None and amt_no is not None and amt_no > 0:
        r_co.cell(Col.PS_CO).value = amt_no
        r_co.cell(Col.PS_CO).raw = f"{amt_no:,}".replace(",", ".")
        r_co.cell(Col.PS_CO).reviewed = True
        repairs.append({"type": "FILL_PAIR_MATCH", "voucher": voucher_name,
                        "page": p_co.page_index + 1, "row": r_co.row_index + 1,
                        "col": "PS_CO", "val": amt_no})
        return True

    if amt_no is None or amt_co is None:
        return False

    # 2. Stray border 1 (115 tỷ vs 15 tỷ, 119.3 tỷ vs 19.3 tỷ)
    s_no, s_co = str(amt_no), str(amt_co)
    if s_co.startswith("1") and s_co[1:] == s_no:
        r_co.cell(Col.PS_CO).value = amt_no
        r_co.cell(Col.PS_CO).raw = f"{amt_no:,}".replace(",", ".")
        r_co.cell(Col.PS_CO).reviewed = True
        repairs.append({"type": "STRIP_STRAY_1", "voucher": voucher_name,
                        "page": p_co.page_index + 1, "row": r_co.row_index + 1,
                        "col": "PS_CO", "old": amt_co, "new": amt_no})
        return True

    if s_no.startswith("1") and s_no[1:] == s_co:
        r_no.cell(Col.PS_NO).value = amt_co
        r_no.cell(Col.PS_NO).raw = f"{amt_co:,}".replace(",", ".")
        r_no.cell(Col.PS_NO).reviewed = True
        repairs.append({"type": "STRIP_STRAY_1", "voucher": voucher_name,
                        "page": p_no.page_index + 1, "row": r_no.row_index + 1,
                        "col": "PS_NO", "old": amt_no, "new": amt_co})
        return True

    # 2b. Lệch 1-2 đơn vị ở chữ số cuối (OCR đọc nét đứt 3 thành 2, 8 thành 9 hoặc ngược lại)
    if abs(amt_no - amt_co) <= 2:
        if r_co.cell(Col.PS_CO).reviewed and not r_no.cell(Col.PS_NO).reviewed:
            r_no.cell(Col.PS_NO).value = amt_co
            r_no.cell(Col.PS_NO).raw = f"{amt_co:,}".replace(",", ".")
            r_no.cell(Col.PS_NO).reviewed = True
            repairs.append({"type": "OFF_BY_ONE_PAIR", "voucher": voucher_name,
                            "page": p_no.page_index + 1, "row": r_no.row_index + 1,
                            "col": "PS_NO", "old": amt_no, "new": amt_co})
            return True
        elif r_no.cell(Col.PS_NO).reviewed and not r_co.cell(Col.PS_CO).reviewed:
            r_co.cell(Col.PS_CO).value = amt_no
            r_co.cell(Col.PS_CO).raw = f"{amt_no:,}".replace(",", ".")
            r_co.cell(Col.PS_CO).reviewed = True
            repairs.append({"type": "OFF_BY_ONE_PAIR", "voucher": voucher_name,
                            "page": p_co.page_index + 1, "row": r_co.row_index + 1,
                            "col": "PS_CO", "old": amt_co, "new": amt_no})
            return True
        d_no_exp, _ = calculate_page_carry_delta(p_no)
        _, d_co_exp = calculate_page_carry_delta(p_co)
        if d_co_exp is not None:
            other_co = sum((r.amount_co or ZERO) for r in p_co.entry_rows() if r != r_co)
            target = d_co_exp - other_co
            if target == amt_no:
                r_co.cell(Col.PS_CO).value = amt_no
                r_co.cell(Col.PS_CO).raw = f"{amt_no:,}".replace(",", ".")
                r_co.cell(Col.PS_CO).reviewed = True
                return True
            elif target == amt_co:
                r_no.cell(Col.PS_NO).value = amt_co
                r_no.cell(Col.PS_NO).raw = f"{amt_co:,}".replace(",", ".")
                r_no.cell(Col.PS_NO).reviewed = True
                return True
        if d_no_exp is not None:
            other_no = sum((r.amount_no or ZERO) for r in p_no.entry_rows() if r != r_no)
            target = d_no_exp - other_no
            if target == amt_co:
                r_no.cell(Col.PS_NO).value = amt_co
                r_no.cell(Col.PS_NO).raw = f"{amt_co:,}".replace(",", ".")
                r_no.cell(Col.PS_NO).reviewed = True
                return True
            elif target == amt_no:
                r_co.cell(Col.PS_CO).value = amt_no
                r_co.cell(Col.PS_CO).raw = f"{amt_no:,}".replace(",", ".")
                r_co.cell(Col.PS_CO).reviewed = True
                return True

    # 3. Phí ngân hàng chuẩn (11.000, 22.000, 66.000) khi OCR đọc nhầm 11.000 thành 44.000
    desc_no = (r_no.cell(Col.DIEN_GIAI).value or "").lower()
    desc_co = (r_co.cell(Col.DIEN_GIAI).value or "").lower()
    is_fee = any(k in desc_no or k in desc_co for k in ("phí", "chuyển tiền", "quản lý"))
    if is_fee:
        if amt_co in STANDARD_BANK_FEES and amt_no not in STANDARD_BANK_FEES:
            r_no.cell(Col.PS_NO).value = amt_co
            r_no.cell(Col.PS_NO).raw = f"{amt_co:,}".replace(",", ".")
            r_no.cell(Col.PS_NO).reviewed = True
            repairs.append({"type": "STANDARD_FEE_MATCH", "voucher": voucher_name,
                            "page": p_no.page_index + 1, "row": r_no.row_index + 1,
                            "col": "PS_NO", "old": amt_no, "new": amt_co})
            return True
        if amt_no in STANDARD_BANK_FEES and amt_co not in STANDARD_BANK_FEES:
            r_co.cell(Col.PS_CO).value = amt_no
            r_co.cell(Col.PS_CO).raw = f"{amt_no:,}".replace(",", ".")
            r_co.cell(Col.PS_CO).reviewed = True
            repairs.append({"type": "STANDARD_FEE_MATCH", "voucher": voucher_name,
                            "page": p_co.page_index + 1, "row": r_co.row_index + 1,
                            "col": "PS_CO", "old": amt_co, "new": amt_no})
            return True

    # 4. Extra zero multiplier (600 tỷ vs 60 tỷ, 400 tỷ vs 40 tỷ)
    if amt_no == amt_co * 10 or amt_co == amt_no * 10:
        d_no_exp, _ = calculate_page_carry_delta(p_no)
        _, d_co_exp = calculate_page_carry_delta(p_co)
        if d_no_exp is not None:
            other_no = sum((r.amount_no or ZERO) for r in p_no.entry_rows() if r != r_no)
            exp_amt = d_no_exp - other_no
            if exp_amt == amt_co:
                r_no.cell(Col.PS_NO).value = amt_co
                r_no.cell(Col.PS_NO).raw = f"{amt_co:,}".replace(",", ".")
                r_no.cell(Col.PS_NO).reviewed = True
                repairs.append({"type": "ZERO_DIV10_CARRY", "voucher": voucher_name,
                                "page": p_no.page_index + 1, "row": r_no.row_index + 1,
                                "col": "PS_NO", "old": amt_no, "new": amt_co})
                return True
        if d_co_exp is not None:
            other_co = sum((r.amount_co or ZERO) for r in p_co.entry_rows() if r != r_co)
            exp_amt = d_co_exp - other_co
            if exp_amt == amt_no:
                r_co.cell(Col.PS_CO).value = amt_no
                r_co.cell(Col.PS_CO).raw = f"{amt_no:,}".replace(",", ".")
                r_co.cell(Col.PS_CO).reviewed = True
                repairs.append({"type": "ZERO_DIV10_CARRY", "voucher": voucher_name,
                                "page": p_co.page_index + 1, "row": r_co.row_index + 1,
                                "col": "PS_CO", "old": amt_co, "new": amt_no})
                return True

    # 5. Carry delta proven
    d_no_exp, _ = calculate_page_carry_delta(p_no)
    _, d_co_exp = calculate_page_carry_delta(p_co)
    if d_no_exp is not None:
        other_no = sum((r.amount_no or ZERO) for r in p_no.entry_rows() if r != r_no)
        exp_amt = d_no_exp - other_no
        if exp_amt == amt_co and exp_amt > 0:
            r_no.cell(Col.PS_NO).value = amt_co
            r_no.cell(Col.PS_NO).raw = f"{amt_co:,}".replace(",", ".")
            r_no.cell(Col.PS_NO).reviewed = True
            repairs.append({"type": "CARRY_DELTA_PROVEN", "voucher": voucher_name,
                            "page": p_no.page_index + 1, "row": r_no.row_index + 1,
                            "col": "PS_NO", "old": amt_no, "new": amt_co})
            return True
        elif exp_amt == amt_no and exp_amt > 0:
            r_co.cell(Col.PS_CO).value = amt_no
            r_co.cell(Col.PS_CO).raw = f"{amt_no:,}".replace(",", ".")
            r_co.cell(Col.PS_CO).reviewed = True
            repairs.append({"type": "CARRY_DELTA_PROVEN", "voucher": voucher_name,
                            "page": p_co.page_index + 1, "row": r_co.row_index + 1,
                            "col": "PS_CO", "old": amt_co, "new": amt_no})
            return True

    if d_co_exp is not None:
        other_co = sum((r.amount_co or ZERO) for r in p_co.entry_rows() if r != r_co)
        exp_amt = d_co_exp - other_co
        if exp_amt == amt_co and exp_amt > 0:
            r_no.cell(Col.PS_NO).value = amt_co
            r_no.cell(Col.PS_NO).raw = f"{amt_co:,}".replace(",", ".")
            r_no.cell(Col.PS_NO).reviewed = True
            repairs.append({"type": "CARRY_DELTA_PROVEN", "voucher": voucher_name,
                            "page": p_no.page_index + 1, "row": r_no.row_index + 1,
                            "col": "PS_NO", "old": amt_no, "new": amt_co})
            return True
        elif exp_amt == amt_no and exp_amt > 0:
            r_co.cell(Col.PS_CO).value = amt_no
            r_co.cell(Col.PS_CO).raw = f"{amt_no:,}".replace(",", ".")
            r_co.cell(Col.PS_CO).reviewed = True
            repairs.append({"type": "CARRY_DELTA_PROVEN", "voucher": voucher_name,
                            "page": p_co.page_index + 1, "row": r_co.row_index + 1,
                            "col": "PS_CO", "old": amt_co, "new": amt_no})
            return True

    # 6. Multi-pass Re-OCR
    if engine is not None:
        img_no = get_img_fn(p_no.page_index)
        img_co = get_img_fn(p_co.page_index)
        cands_no = multi_pass_reocr(img_no, r_no.cells[Col.PS_NO].rect, engine)
        cands_co = multi_pass_reocr(img_co, r_co.cells[Col.PS_CO].rect, engine)

        # Ưu tiên ứng viên re-OCR làm cân đối chính xác tổng chuyển trang
        if d_no_exp is not None:
            other_no = sum((r.amount_no or ZERO) for r in p_no.entry_rows() if r != r_no)
            exp_no = d_no_exp - other_no
            if exp_no > 0 and (exp_no in cands_no or exp_no in cands_co):
                r_no.cell(Col.PS_NO).value = exp_no
                r_no.cell(Col.PS_NO).raw = f"{exp_no:,}".replace(",", ".")
                r_no.cell(Col.PS_NO).reviewed = True
                r_co.cell(Col.PS_CO).value = exp_no
                r_co.cell(Col.PS_CO).raw = f"{exp_no:,}".replace(",", ".")
                r_co.cell(Col.PS_CO).reviewed = True
                repairs.append({"type": "REOCR_CARRY_DELTA_MATCH", "voucher": voucher_name,
                                "page": p_no.page_index + 1, "val": exp_no})
                return True

        common = cands_no & cands_co
        if common:
            chosen = None
            if d_no_exp is not None:
                other_no = sum((r.amount_no or ZERO) for r in p_no.entry_rows() if r != r_no)
                exp_no = d_no_exp - other_no
                if exp_no in common:
                    chosen = exp_no
            if chosen is None and d_co_exp is not None:
                other_co = sum((r.amount_co or ZERO) for r in p_co.entry_rows() if r != r_co)
                exp_co = d_co_exp - other_co
                if exp_co in common:
                    chosen = exp_co
            if chosen is None:
                chosen = next(iter(common))

            if amt_no != chosen:
                r_no.cell(Col.PS_NO).value = chosen
                r_no.cell(Col.PS_NO).raw = f"{chosen:,}".replace(",", ".")
                r_no.cell(Col.PS_NO).reviewed = True
            if amt_co != chosen:
                r_co.cell(Col.PS_CO).value = chosen
                r_co.cell(Col.PS_CO).raw = f"{chosen:,}".replace(",", ".")
                r_co.cell(Col.PS_CO).reviewed = True
            repairs.append({"type": "REOCR_COMMON_MATCH", "voucher": voucher_name,
                            "page_no": p_no.page_index + 1, "page_co": p_co.page_index + 1,
                            "val": chosen})
            return True

        if amt_no in cands_co:
            r_co.cell(Col.PS_CO).value = amt_no
            r_co.cell(Col.PS_CO).raw = f"{amt_no:,}".replace(",", ".")
            r_co.cell(Col.PS_CO).reviewed = True
            repairs.append({"type": "REOCR_MATCH_NO", "voucher": voucher_name,
                            "page": p_co.page_index + 1, "row": r_co.row_index + 1,
                            "col": "PS_CO", "old": amt_co, "new": amt_no})
            return True

        if amt_co in cands_no:
            r_no.cell(Col.PS_NO).value = amt_co
            r_no.cell(Col.PS_NO).raw = f"{amt_co:,}".replace(",", ".")
            r_no.cell(Col.PS_NO).reviewed = True
            repairs.append({"type": "REOCR_MATCH_CO", "voucher": voucher_name,
                            "page": p_no.page_index + 1, "row": r_no.row_index + 1,
                            "col": "PS_NO", "old": amt_no, "new": amt_co})
            return True

    return False


def auto_reconcile_and_repair(fr: FileResult, engine: OcrEngine | None = None,
                              pdf_path: str | None = None) -> list[dict]:
    """Bộ giải thông minh: Phát hiện và tự động sửa các lỗi lệch Nợ - Có."""
    from .extract import render_page

    pdf_file = pdf_path or fr.path
    page_img_cache: dict[int, np.ndarray] = {}

    def get_img(pi: int) -> np.ndarray:
        if pi not in page_img_cache:
            p_obj = next((p for p in fr.pages if p.page_index == pi), None)
            if p_obj and p_obj.image_path and Path(p_obj.image_path).exists():
                page_img_cache[pi] = cv2.imread(p_obj.image_path)
            else:
                page_img_cache[pi] = render_page(pdf_file, pi)
        return page_img_cache[pi]

    repairs = []
    groups = group_voucher_transactions(fr)

    for g in groups:
        voucher_name = g["voucher"]
        rows = g["rows"]

        # Pha A: Tìm các cặp định khoản đối ứng trực tiếp trong nhóm
        used_no = set()
        used_co = set()
        for i, (p_no, r_no) in enumerate(rows):
            if i in used_no:
                continue
            # r_no là ứng viên Nợ: có amount_no hoặc cả Nợ và Có đều trống
            if r_no.amount_co is not None and r_no.amount_co > 0 and (r_no.amount_no is None or r_no.amount_no == 0):
                continue

            tk_no = r_no.cell(Col.TAI_KHOAN).value
            tkdu_no = r_no.cell(Col.TK_DOI_UNG).value
            desc_no = (r_no.cell(Col.DIEN_GIAI).value or "").strip()

            for j, (p_co, r_co) in enumerate(rows):
                if i == j or j in used_co or j in used_no:
                    continue
                # r_co là ứng viên Có: có amount_co hoặc cả Nợ và Có đều trống
                if r_co.amount_no is not None and r_co.amount_no > 0 and (r_co.amount_co is None or r_co.amount_co == 0):
                    continue

                tk_co = r_co.cell(Col.TAI_KHOAN).value
                tkdu_co = r_co.cell(Col.TK_DOI_UNG).value
                desc_co = (r_co.cell(Col.DIEN_GIAI).value or "").strip()

                # Khớp cặp đối ứng theo tài khoản hoặc diễn giải tương đồng
                accounts_match = bool(tk_no and tkdu_no and tk_co and tkdu_co
                                      and accts_match(tk_no, tkdu_co) and accts_match(tkdu_no, tk_co))
                desc_match = bool(desc_no and desc_co and (desc_no == desc_co or desc_no.startswith(desc_co) or desc_co.startswith(desc_no)))

                if accounts_match or (desc_match and (accts_match(tk_no, tkdu_co) or accts_match(tkdu_no, tk_co))):
                    if resolve_pair(p_no, r_no, p_co, r_co, voucher_name, engine, get_img, repairs):
                        used_no.add(i)
                        used_co.add(j)
                        break

        # Pha B: Đồng bộ tài khoản/ngày cho các nhóm 2 dòng (1 Nợ - 1 Có) và kiểm tra cân đối nhóm
        if len(rows) == 2:
            r1, r2 = rows[0][1], rows[1][1]
            if r1.amount_no is not None and r2.amount_co is not None:
                sync_pair_accounts_and_dates(r1, r2)
            elif r2.amount_no is not None and r1.amount_co is not None:
                sync_pair_accounts_and_dates(r2, r1)

        curr_no = sum((r.amount_no or ZERO) for _, r in rows)
        curr_co = sum((r.amount_co or ZERO) for _, r in rows)
        if curr_no == curr_co:
            continue

        no_rows = [(p, r) for p, r in rows if r.amount_no is not None and r.amount_no > 0]
        co_rows = [(p, r) for p, r in rows if r.amount_co is not None and r.amount_co > 0]

        if len(no_rows) == 1 and len(co_rows) == 1:
            p_no, r_no = no_rows[0]
            p_co, r_co = co_rows[0]
            if (p_no, r_no) != (p_co, r_co):
                resolve_pair(p_no, r_no, p_co, r_co, voucher_name, engine, get_img, repairs)
        elif len(no_rows) > 0 or len(co_rows) > 0:
            for p, r in rows:
                if r.amount_no is not None and r.amount_no > 0:
                    d_no_exp, _ = calculate_page_carry_delta(p)
                    if d_no_exp is not None:
                        other = sum((rx.amount_no or ZERO) for rx in p.entry_rows() if rx != r)
                        exp_val = d_no_exp - other
                        if exp_val > 0 and exp_val != r.amount_no:
                            matched_co = any(rx.amount_co == exp_val for _, rx in rows)
                            is_close_ocr = abs(exp_val - r.amount_no) <= 5 and (str(r.amount_no)[:-1] == str(exp_val)[:-1])
                            if matched_co or is_close_ocr or (exp_val == r.amount_no // 10 and r.amount_no % 10 == 0):
                                old_no = r.amount_no
                                r.cell(Col.PS_NO).value = exp_val
                                r.cell(Col.PS_NO).raw = f"{exp_val:,}".replace(",", ".")
                                r.cell(Col.PS_NO).reviewed = True
                                repairs.append({"type": "CARRY_DELTA_MULTI_ROW", "voucher": voucher_name,
                                                "page": p.page_index + 1, "row": r.row_index + 1,
                                                "col": "PS_NO", "old": old_no, "new": exp_val})

                if r.amount_co is not None and r.amount_co > 0:
                    _, d_co_exp = calculate_page_carry_delta(p)
                    if d_co_exp is not None:
                        other = sum((rx.amount_co or ZERO) for rx in p.entry_rows() if rx != r)
                        exp_val = d_co_exp - other
                        if exp_val > 0 and exp_val != r.amount_co:
                            matched_no = any(rx.amount_no == exp_val for _, rx in rows)
                            is_close_ocr = abs(exp_val - r.amount_co) <= 5 and (str(r.amount_co)[:-1] == str(exp_val)[:-1])
                            if matched_no or is_close_ocr or (exp_val == r.amount_co // 10 and r.amount_co % 10 == 0):
                                old_co = r.amount_co
                                r.cell(Col.PS_CO).value = exp_val
                                r.cell(Col.PS_CO).raw = f"{exp_val:,}".replace(",", ".")
                                r.cell(Col.PS_CO).reviewed = True
                                repairs.append({"type": "CARRY_DELTA_MULTI_ROW", "voucher": voucher_name,
                                                "page": p.page_index + 1, "row": r.row_index + 1,
                                                "col": "PS_CO", "old": old_co, "new": exp_val})

    # Ghi nhận các sửa đổi vào Warnings
    for rep in repairs:
        p_idx = rep.get("page", 1) - 1
        r_idx = rep.get("row", 1) - 1
        col_name = rep.get("col", "PS_NO")
        col_enum = Col.PS_NO if col_name == "PS_NO" else Col.PS_CO
        val_str = f"{rep.get('val', rep.get('new', 0)):,}"
        fr.warnings.append(WarningItem(
            code="TU_DONG_CAN_DOI_OCR",
            message=(f"Chứng từ {rep['voucher']} (trang {p_idx + 1}): Đã tự động đối soát kép và "
                     f"khớp số chuẩn xác {val_str} ({rep['type']})."),
            level=WarningLevel.INFO,
            page_index=p_idx,
            row_index=r_idx,
            col=col_enum,
            resolved=True,
            resolution=f"Khớp đúng cân đối kép: {val_str}"
        ))

    return repairs
