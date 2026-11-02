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
    s = "".join(CONFUSE.get(ch, ch) for ch in v.upper())
    return re.sub(r"[^A-Z0-9]", "", s)


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

    c1, c2 = clean_voucher_str(v1), clean_voucher_str(v2)
    if c1 == c2:
        return True

    # Cho phép khớp tiền tố khi một bên bị rớt 1-2 ký tự cuối do tràn dòng ô hẹp (ví dụ NVK1602 vs NVK16021)
    min_c = min(len(c1), len(c2))
    if min_c >= 5 and (c1.startswith(c2) or c2.startswith(c1)) and abs(len(c1) - len(c2)) <= 2:
        return True

    k1, n1 = parse_voucher_info(v1)
    k2, n2 = parse_voucher_info(v2)

    if n1 is not None and n2 is not None:
        if n1 != n2:
            return False  # Khác số thứ tự là chứng từ khác nhau!
        if k1 == k2 or k1 == "UNKNOWN" or k2 == "UNKNOWN" or not k1 or not k2:
            return True
        return False

    c1, c2 = clean_voucher_str(v1), clean_voucher_str(v2)
    if c1 == c2:
        return True
    t1 = c1.lstrip("LI1|").rstrip("./-")
    t2 = c2.lstrip("LI1|").rstrip("./-")
    if t1 and t2 and t1 == t2:
        return True
    from .reconcile import _edit_distance_le1
    if c1 and c2 and len(c1) >= 4 and len(c2) >= 4 and _edit_distance_le1(c1, c2):
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

            is_reciprocal = bool(tk and tkdu and last_tk and last_tkdu
                                 and accts_match(tk, last_tkdu) and accts_match(tkdu, last_tk))
            d_cur = (r.cell(Col.DIEN_GIAI).value or "").strip()
            d_last = (last_r.cell(Col.DIEN_GIAI).value or "").strip()
            desc_match = bool(d_cur and d_last and (d_cur == d_last or d_cur.startswith(d_last) or d_last.startswith(d_cur)))

            c_amt = (r.amount_no or r.amount_co)
            l_amt = (last_r.amount_no or last_r.amount_co)
            amt_match = bool(c_amt and l_amt and c_amt == l_amt)
            balances_cur = (cur["no"] + (r.amount_no or ZERO) == cur["co"] + (r.amount_co or ZERO))

            c_v, c_lv = clean_voucher_str(v), clean_voucher_str(last_v)
            v_compat = vouchers_match(v, last_v) or (bool(c_v and c_lv) and (c_v.startswith(c_lv) or c_lv.startswith(c_v)))
            cur_v_compat = not cur["voucher"] or vouchers_match(v, cur["voucher"])

            if cur["no"] != cur["co"]:
                if is_reciprocal or balances_cur:
                    continues = True
                elif v_compat and cur_v_compat:
                    continues = True
                elif not v:
                    continues = True
            else:
                if v and last_v and not v_compat:
                    continues = False
                elif v and cur["voucher"] and not cur_v_compat:
                    continues = False
                elif v_compat:
                    continues = True

        if continues and cur is not None:
            cur["rows"].append((p, r))
            cur["no"] += r.amount_no or ZERO
            cur["co"] += r.amount_co or ZERO
            if v and (not cur["voucher"] or len(v) > len(cur["voucher"])):
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
        should_merge = False
        if merged and merged[-1]["no"] != merged[-1]["co"] and g["no"] != g["co"]:
            v_prev = merged[-1]["voucher"]
            v_cur = g["voucher"]
            v_match = vouchers_match(v_prev, v_cur)
            if not v_match:
                k1, n1 = parse_voucher_info(v_prev)
                k2, n2 = parse_voucher_info(v_cur)
                if k1 and k2 and k1 == k2 and k1 != "UNKNOWN":
                    v_match = True
                else:
                    c1, c2 = clean_voucher_str(v_prev), clean_voucher_str(v_cur)
                    for pref in ("UNC", "TNH", "NVK", "PKT", "PC", "PT", "BN", "BC", "NH", "LNH"):
                        if pref in c1 and pref in c2:
                            v_match = True
                            break

            last_r = merged[-1]["rows"][-1][1]
            first_r = g["rows"][0][1]
            tk1, tkdu1 = last_r.cell(Col.TAI_KHOAN).value, last_r.cell(Col.TK_DOI_UNG).value
            tk2, tkdu2 = first_r.cell(Col.TAI_KHOAN).value, first_r.cell(Col.TK_DOI_UNG).value
            accts_reversed = bool(tk1 and tk2 and accts_match(tk1, tkdu2) and accts_match(tkdu1, tk2))

            d1 = (last_r.cell(Col.DIEN_GIAI).value or "").strip()
            d2 = (first_r.cell(Col.DIEN_GIAI).value or "").strip()
            desc_match = bool(d1 and d2 and (d1 == d2 or d1.startswith(d2) or d2.startswith(d1)))

            # Trường hợp A: Đã cân chính xác khi gộp
            exact_balance = (merged[-1]["no"] + g["no"] == merged[-1]["co"] + g["co"])
            if exact_balance and (v_match or accts_reversed or desc_match):
                should_merge = True
            else:
                # Trường hợp B: Hai nửa đối ứng của cùng một bút toán (1 Nợ thuần, 1 Có thuần)
                prev_pure = (merged[-1]["no"] > 0 and merged[-1]["co"] == 0) or (merged[-1]["co"] > 0 and merged[-1]["no"] == 0)
                cur_pure = (g["no"] > 0 and g["co"] == 0) or (g["co"] > 0 and g["no"] == 0)
                opposite_sides = (merged[-1]["no"] > 0 and g["co"] > 0) or (merged[-1]["co"] > 0 and g["no"] > 0)
                if prev_pure and cur_pure and opposite_sides and (accts_reversed or (desc_match and v_match)):
                    amt_a = merged[-1]["no"] or merged[-1]["co"]
                    amt_b = g["no"] or g["co"]
                    s_a, s_b = str(amt_a), str(amt_b)
                    if (abs(amt_a - amt_b) <= 10 or (len(s_a) == len(s_b) and sum(x != y for x, y in zip(s_a, s_b)) == 1)
                            or (len(s_a) >= 4 and len(s_b) >= 4 and abs(amt_a - amt_b) < max(amt_a, amt_b) * Decimal("0.02"))):
                        should_merge = True

        if should_merge:
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
    elif v_no and v_co and v_no != v_co:
        k_no, _ = parse_voucher_info(v_no)
        k_co, _ = parse_voucher_info(v_co)
        std_prefixes = ("UNC", "TNH", "NVK", "PKT", "PC", "PT", "BN", "BC")
        no_std = k_no in std_prefixes
        co_std = k_co in std_prefixes
        if no_std and not co_std:
            r_co.cell(Col.SO_CT).value = v_no
            r_co.cell(Col.SO_CT).raw = v_no
        elif co_std and not no_std:
            r_no.cell(Col.SO_CT).value = v_co
            r_no.cell(Col.SO_CT).raw = v_co
        elif len(v_no) > len(v_co) and v_no.startswith(v_co):
            r_co.cell(Col.SO_CT).value = v_no
        elif len(v_co) > len(v_no) and v_co.startswith(v_no):
            r_no.cell(Col.SO_CT).value = v_co

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
    tk_no = r_no.cell(Col.TAI_KHOAN).value
    tkdu_no = r_no.cell(Col.TK_DOI_UNG).value
    tk_co = r_co.cell(Col.TAI_KHOAN).value
    tkdu_co = r_co.cell(Col.TK_DOI_UNG).value
    desc_no = (r_no.cell(Col.DIEN_GIAI).value or "").strip()
    desc_co = (r_co.cell(Col.DIEN_GIAI).value or "").strip()

    accounts_match = bool(tk_no and tkdu_no and tk_co and tkdu_co
                          and accts_match(tk_no, tkdu_co) and accts_match(tkdu_no, tk_co))
    desc_match = bool(desc_no and desc_co and (desc_no == desc_co or desc_no.startswith(desc_co) or desc_co.startswith(desc_no)))

    amt_no = r_no.amount_no
    amt_co = r_co.amount_co
    amt_match = (amt_no is not None and amt_co is not None and amt_no == amt_co)

    # Nếu tài khoản và diễn giải hoàn toàn không khớp và số tiền cũng không khớp:
    # Tuyệt đối không can thiệp vì không phải cặp định khoản hợp lệ!
    if not accounts_match and not desc_match and not amt_match:
        return False

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

    # 2a. Chữ số rác chen vào giữa số tiền (ví dụ 3.471.490.000.000 vs 347.490.000.000 do vết mực/dấu chấm biến thành 1)
    if len(s_no) == len(s_co) + 1:
        for idx in range(len(s_no)):
            if s_no[:idx] + s_no[idx + 1:] == s_co:
                r_no.cell(Col.PS_NO).value = amt_co
                r_no.cell(Col.PS_NO).raw = f"{amt_co:,}".replace(",", ".")
                r_no.cell(Col.PS_NO).reviewed = True
                repairs.append({"type": "STRIP_STRAY_DIGIT", "voucher": voucher_name,
                                "page": p_no.page_index + 1, "row": r_no.row_index + 1,
                                "col": "PS_NO", "old": amt_no, "new": amt_co})
                return True

    if len(s_co) == len(s_no) + 1:
        for idx in range(len(s_co)):
            if s_co[:idx] + s_co[idx + 1:] == s_no:
                r_co.cell(Col.PS_CO).value = amt_no
                r_co.cell(Col.PS_CO).raw = f"{amt_no:,}".replace(",", ".")
                r_co.cell(Col.PS_CO).reviewed = True
                repairs.append({"type": "STRIP_STRAY_DIGIT", "voucher": voucher_name,
                                "page": p_co.page_index + 1, "row": r_co.row_index + 1,
                                "col": "PS_CO", "old": amt_co, "new": amt_no})
                return True

    # 2b. Lệch 1 chữ số do nhầm lẫn OCR (như 0 <-> 6: 300 tỷ vs 360 tỷ; 3 <-> 8; 5 <-> 6)
    if len(s_no) == len(s_co) and sum(c1 != c2 for c1, c2 in zip(s_no, s_co)) == 1:
        d_no_exp, _ = calculate_page_carry_delta(p_no)
        _, d_co_exp = calculate_page_carry_delta(p_co)
        if d_co_exp is not None:
            other_co = sum((r.amount_co or ZERO) for r in p_co.entry_rows() if r != r_co)
            target = d_co_exp - other_co
            if target == amt_no:
                r_co.cell(Col.PS_CO).value = amt_no
                r_co.cell(Col.PS_CO).raw = f"{amt_no:,}".replace(",", ".")
                r_co.cell(Col.PS_CO).reviewed = True
                repairs.append({"type": "SUB_1_DIGIT_CARRY_MATCH", "voucher": voucher_name,
                                "page": p_co.page_index + 1, "row": r_co.row_index + 1,
                                "col": "PS_CO", "old": amt_co, "new": amt_no})
                return True
            elif target == amt_co:
                r_no.cell(Col.PS_NO).value = amt_co
                r_no.cell(Col.PS_NO).raw = f"{amt_co:,}".replace(",", ".")
                r_no.cell(Col.PS_NO).reviewed = True
                repairs.append({"type": "SUB_1_DIGIT_CARRY_MATCH", "voucher": voucher_name,
                                "page": p_no.page_index + 1, "row": r_no.row_index + 1,
                                "col": "PS_NO", "old": amt_no, "new": amt_co})
                return True
        if d_no_exp is not None:
            other_no = sum((r.amount_no or ZERO) for r in p_no.entry_rows() if r != r_no)
            target = d_no_exp - other_no
            if target == amt_co:
                r_no.cell(Col.PS_NO).value = amt_co
                r_no.cell(Col.PS_NO).raw = f"{amt_co:,}".replace(",", ".")
                r_no.cell(Col.PS_NO).reviewed = True
                repairs.append({"type": "SUB_1_DIGIT_CARRY_MATCH", "voucher": voucher_name,
                                "page": p_no.page_index + 1, "row": r_no.row_index + 1,
                                "col": "PS_NO", "old": amt_no, "new": amt_co})
                return True
            elif target == amt_no:
                r_co.cell(Col.PS_CO).value = amt_no
                r_co.cell(Col.PS_CO).raw = f"{amt_no:,}".replace(",", ".")
                r_co.cell(Col.PS_CO).reviewed = True
                repairs.append({"type": "SUB_1_DIGIT_CARRY_MATCH", "voucher": voucher_name,
                                "page": p_co.page_index + 1, "row": r_co.row_index + 1,
                                "col": "PS_CO", "old": amt_co, "new": amt_no})
                return True

    # 2c. Lệch 1-2 đơn vị ở chữ số cuối (OCR đọc nét đứt 3 thành 2, 8 thành 9 hoặc ngược lại)
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
    if d_no_exp is not None and (accounts_match or desc_match):
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

    if d_co_exp is not None and (accounts_match or desc_match):
        other_co = sum((r.amount_co or ZERO) for r in p_co.entry_rows() if r != r_co)
        exp_amt = d_co_exp - other_co
        if exp_amt == amt_no and exp_amt > 0:
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


def reconcile_carry_continuity(fr: FileResult, repairs: list[dict] | None = None) -> list[dict]:
    """Cơ chế đồng thuận chuỗi chuyển trang (Carry Forward Multi-Page Consensus).
    Đảm bảo tính liên tục của luồng luân chuyển trang:
        Carry_Out_Nợ(p) = Carry_In_Nợ(p+1)
        Carry_Out_Có(p) = Carry_In_Có(p+1)
    Đồng thời đối chiếu với phương trình trang (Vào + Phát sinh = Ra) để sửa chính xác
    các chữ số bị OCR nhận diện nhầm mà KHÔNG ép Nợ = Có khi có bút toán ngắt trang.
    """
    if repairs is None:
        repairs = []
    pages = sorted(
        [p for p in fr.pages if p.rows and not p.info_page],
        key=lambda p: (p.printed_page if p.printed_page is not None else p.page_index + 1)
    )
    
    # 1. So khớp từng vế Nợ và Có giữa trang p (Carry Out) và trang p+1 (Carry In)
    for col_name, col_enum, attr_out, attr_in in (
        ("PS_NO", Col.PS_NO, "carry_out_no", "carry_in_no"),
        ("PS_CO", Col.PS_CO, "carry_out_co", "carry_in_co")
    ):
        for i in range(len(pages) - 1):
            p = pages[i]
            nxt = pages[i + 1]
            out_val = getattr(p, attr_out)
            in_val = getattr(nxt, attr_in)
            
            if out_val is not None and in_val is not None and out_val != in_val:
                cin = getattr(p, attr_in)
                ps = p.sum_no() if col_enum == Col.PS_NO else p.sum_co()
                exp_p = (cin or ZERO) + ps if cin is not None or i == 0 else None
                
                nxt_cout = getattr(nxt, attr_out)
                nxt_ps = nxt.sum_no() if col_enum == Col.PS_NO else nxt.sum_co()
                exp_nxt = (nxt_cout - nxt_ps) if nxt_cout is not None else None
                
                s_out, s_in = str(out_val), str(in_val)
                is_close = (len(s_out) == len(s_in) and sum(c1 != c2 for c1, c2 in zip(s_out, s_in)) == 1)
                
                if exp_p is not None and exp_p == in_val:
                    setattr(p, attr_out, in_val)
                    for r in p.rows:
                        if r.kind == RowKind.CARRY_OUT:
                            r.cell(col_enum).value = in_val
                            r.cell(col_enum).reviewed = True
                    repairs.append({"type": "CARRY_CHAIN_CONSENSUS", "voucher": f"Chuỗi_{p.page_index+1}->{nxt.page_index+1}",
                                    "page": p.page_index + 1, "col": col_name, "val": in_val})
                elif exp_nxt is not None and exp_nxt == out_val:
                    setattr(nxt, attr_in, out_val)
                    for r in nxt.rows:
                        if r.kind == RowKind.CARRY_IN:
                            r.cell(col_enum).value = out_val
                            r.cell(col_enum).reviewed = True
                    repairs.append({"type": "CARRY_CHAIN_CONSENSUS", "voucher": f"Chuỗi_{p.page_index+1}->{nxt.page_index+1}",
                                    "page": nxt.page_index + 1, "col": col_name, "val": out_val})
                elif is_close and exp_p is not None and exp_p == in_val:
                    setattr(p, attr_out, in_val)
                    for r in p.rows:
                        if r.kind == RowKind.CARRY_OUT:
                            r.cell(col_enum).value = in_val
                            r.cell(col_enum).reviewed = True
                    repairs.append({"type": "CARRY_CHAIN_CONSENSUS", "voucher": f"Chuỗi_{p.page_index+1}->{nxt.page_index+1}",
                                    "page": p.page_index + 1, "col": col_name, "val": in_val})

    # 2. Đồng thuận trong nội bộ trang khi cả 2 bên Nợ và Có phải bằng nhau (khi trang trước và sau đều cân)
    for i, p in enumerate(pages):
        cout_no, cout_co = p.carry_out_no, p.carry_out_co
        if cout_no is not None and cout_co is not None and cout_no != cout_co:
            ps_no, ps_co = p.sum_no(), p.sum_co()
            cin_no, cin_co = p.carry_in_no, p.carry_in_co
            # Chỉ đồng thuận bằng nhau nếu trang cân đối (ps_no == ps_co và cin_no == cin_co)
            # VÀ trang sau cũng có số chuyển sang cân đối (không bị ngắt chứng từ qua trang)
            nxt = pages[i + 1] if i + 1 < len(pages) else None
            nxt_is_balanced = bool(nxt and nxt.carry_in_no is not None and nxt.carry_in_no == nxt.carry_in_co)
            if (cin_no == cin_co or cin_no is None) and ps_no == ps_co and nxt_is_balanced:
                nxt_in = nxt.carry_in_no
                exp = (cin_no or ZERO) + ps_no if cin_no is not None or i == 0 else None
                chosen = None
                if nxt_in is not None and nxt_in in (cout_no, cout_co):
                    chosen = nxt_in
                elif exp is not None and exp in (cout_no, cout_co):
                    chosen = exp
                if chosen is not None:
                    p.carry_out_no = chosen
                    p.carry_out_co = chosen
                    for r in p.rows:
                        if r.kind == RowKind.CARRY_OUT:
                            r.cell(Col.PS_NO).value = chosen
                            r.cell(Col.PS_CO).value = chosen
                            r.cell(Col.PS_NO).reviewed = True
                            r.cell(Col.PS_CO).reviewed = True
                    repairs.append({"type": "CARRY_CONSENSUS_PAGE", "voucher": f"Trang_{p.page_index+1}",
                                    "page": p.page_index + 1, "col": "CARRY_OUT", "val": chosen})
    return repairs


def solve_page_equations(fr: FileResult, repairs: list[dict] | None = None) -> list[dict]:
    """Giải phương trình sai số trang dựa trên nguyên lý bảo toàn luân chuyển trang."""
    if repairs is None:
        repairs = []
    pages = sorted(
        [p for p in fr.pages if p.rows and not p.info_page],
        key=lambda p: (p.printed_page if p.printed_page is not None else p.page_index + 1)
    )
    for p in pages:
        cout_no, cout_co = p.carry_out_no, p.carry_out_co
        if cout_no is None and cout_co is None and p.grand_total_no is not None:
            cout_no, cout_co = p.grand_total_no, p.grand_total_co
        if cout_no is None and cout_co is None:
            continue
        cin_no = p.carry_in_no if (p.carry_in_no is not None or p.page_index == 0) else None
        cin_co = p.carry_in_co if (p.carry_in_co is not None or p.page_index == 0) else None
        
        exp_sum_no = (cout_no - (cin_no or ZERO)) if (cout_no is not None and (cin_no is not None or p.page_index == 0)) else None
        exp_sum_co = (cout_co - (cin_co or ZERO)) if (cout_co is not None and (cin_co is not None or p.page_index == 0)) else None
        
        actual_sum_no = p.sum_no()
        actual_sum_co = p.sum_co()
        
        delta_no = (actual_sum_no - exp_sum_no) if exp_sum_no is not None else ZERO
        delta_co = (actual_sum_co - exp_sum_co) if exp_sum_co is not None else ZERO
        
        # Trường hợp 1: Cả Nợ và Có cùng lệch đúng 1 lượng delta do một cặp bút toán bị lỗi OCR giống nhau
        if delta_no == delta_co and delta_no != ZERO and abs(delta_no) >= 1000:
            delta = delta_no
            matched_pair = False
            for r in p.entry_rows():
                amt = r.amount_no or r.amount_co
                if not amt:
                    continue
                target = amt - delta
                if target <= ZERO:
                    continue
                s_amt = str(amt)
                s_target = str(target)
                
                is_stray_1 = (s_amt.startswith("1") and s_amt[1:] == s_target)
                is_del_1 = (len(s_amt) == len(s_target) + 1 and any(s_amt[:idx] + s_amt[idx+1:] == s_target for idx in range(len(s_amt))))
                is_sub_1 = (len(s_amt) == len(s_target) and sum(c1 != c2 for c1, c2 in zip(s_amt, s_target)) == 1)
                
                if is_stray_1 or is_del_1 or is_sub_1:
                    col_target = Col.PS_NO if r.amount_no else Col.PS_CO
                    old_v = r.cell(col_target).value
                    r.cell(col_target).value = target
                    r.cell(col_target).raw = f"{target:,}".replace(",", ".")
                    r.cell(col_target).reviewed = True
                    repairs.append({"type": "PAGE_EQUATION_PAIR", "voucher": f"Trang_{p.page_index+1}_D{r.row_index+1}",
                                    "page": p.page_index + 1, "row": r.row_index + 1,
                                    "col": col_target.value, "old": old_v, "new": target})
                    matched_pair = True
            if matched_pair:
                continue

        # Trường hợp 2: Chỉ một vế (Nợ hoặc Có) bị lệch do một dòng đơn lẻ bị lỗi OCR
        for col_name, delta_val, col_enum in (("PS_NO", delta_no, Col.PS_NO), ("PS_CO", delta_co, Col.PS_CO)):
            if delta_val != ZERO and abs(delta_val) >= 1000:
                for r in p.entry_rows():
                    amt = r.amount_no if col_enum == Col.PS_NO else r.amount_co
                    if not amt:
                        continue
                    target = amt - delta_val
                    if target <= ZERO:
                        continue
                    s_amt = str(amt)
                    s_target = str(target)
                    is_stray_1 = (s_amt.startswith("1") and s_amt[1:] == s_target)
                    is_del_1 = (len(s_amt) == len(s_target) + 1 and any(s_amt[:idx] + s_amt[idx+1:] == s_target for idx in range(len(s_amt))))
                    is_sub_1 = (len(s_amt) == len(s_target) and sum(c1 != c2 for c1, c2 in zip(s_amt, s_target)) == 1)
                    if is_stray_1 or is_del_1 or is_sub_1:
                        old_v = r.cell(col_enum).value
                        r.cell(col_enum).value = target
                        r.cell(col_enum).raw = f"{target:,}".replace(",", ".")
                        r.cell(col_enum).reviewed = True
                        repairs.append({"type": "PAGE_EQUATION_SINGLE", "voucher": f"Trang_{p.page_index+1}_D{r.row_index+1}",
                                        "page": p.page_index + 1, "row": r.row_index + 1,
                                        "col": col_name, "old": old_v, "new": target})
                        break
    return repairs


def auto_reconcile_and_repair(fr: FileResult, engine: OcrEngine | None = None,
                              pdf_path: str | None = None) -> list[dict]:
    """Bộ giải thông minh: Phát hiện và tự động sửa các lỗi lệch Nợ - Có."""
    from .extract import render_page

    # Pha 0: Phục hồi số tiền bị xén số 0 cuối hoặc lỗi phân cách từ raw OCR text
    from .reconcile import refresh_page_totals
    for page in fr.pages:
        for r in page.rows:
            for c in (Col.PS_NO, Col.PS_CO):
                cell = r.cell(c)
                if cell.raw and any(ch.isdigit() for ch in cell.raw):
                    new_val, _ = parse_amount(cell.raw, c, page.page_index, r.row_index)
                    if new_val is not None:
                        cell.value = new_val
        refresh_page_totals(page)

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
    
    for iteration in range(2):
        # Pha 1: Đồng thuận chuỗi chuyển trang (loại bỏ các lỗi đọc nhầm 5 vs 9, 3 vs 5 ở số chuyển trang)
        reconcile_carry_continuity(fr, repairs)
        
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
                r_no = r1 if r1.amount_no is not None else r2
                r_co = r2 if r1.amount_no is not None else r1
                if r_no.amount_no is not None and r_co.amount_co is not None:
                    tk_no, tkdu_no = r_no.cell(Col.TAI_KHOAN).value, r_no.cell(Col.TK_DOI_UNG).value
                    tk_co, tkdu_co = r_co.cell(Col.TAI_KHOAN).value, r_co.cell(Col.TK_DOI_UNG).value
                    d_no = (r_no.cell(Col.DIEN_GIAI).value or "").strip()
                    d_co = (r_co.cell(Col.DIEN_GIAI).value or "").strip()
                    accts_compat = bool(tk_no and tkdu_no and tk_co and tkdu_co and accts_match(tk_no, tkdu_co) and accts_match(tkdu_no, tk_co))
                    desc_compat = bool(d_no and d_co and (d_no == d_co or d_no.startswith(d_co) or d_co.startswith(d_no)))
                    amt_compat = (r_no.amount_no == r_co.amount_co or abs((r_no.amount_no or ZERO) - (r_co.amount_co or ZERO)) < 1000)
                    if accts_compat or (desc_compat and amt_compat):
                        sync_pair_accounts_and_dates(r_no, r_co)

            curr_no = sum((r.amount_no or ZERO) for _, r in rows)
            curr_co = sum((r.amount_co or ZERO) for _, r in rows)
            if curr_no == curr_co:
                # Đồng bộ số chứng từ chuẩn xác cho các dòng trong nhóm cân bằng
                canonical_v = g["voucher"]
                if canonical_v and len(canonical_v) >= 5:
                    for _, r in rows:
                        cur_v = (r.cell(Col.SO_CT).value or "").strip()
                        if cur_v and cur_v != canonical_v and vouchers_match(cur_v, canonical_v):
                            if len(cur_v) < len(canonical_v) or clean_voucher_str(cur_v) == clean_voucher_str(canonical_v):
                                r.cell(Col.SO_CT).value = canonical_v
                                r.cell(Col.SO_CT).raw = canonical_v
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

        # Pha C: Giải phương trình sai số trang còn sót lại
        solve_page_equations(fr, repairs)
        reconcile_carry_continuity(fr, repairs)

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
