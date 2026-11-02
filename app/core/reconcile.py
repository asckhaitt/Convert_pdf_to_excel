"""Đối soát kế toán: công thức trang, chuỗi trang, chứng từ, toàn sổ."""
from __future__ import annotations

from decimal import Decimal

from .model import (AccountingCheck, Col, FileResult, ReconcileItem, RowKind,
                    WarningItem, WarningLevel)
from .normalize import CONFUSE

ZERO = Decimal(0)

RECONCILE_CODES = {
    "CONG_THUC_LECH", "CHUNG_TU_KHONG_CAN", "TOAN_SO_KHONG_CAN",
    "SO_CT_KHONG_THONG_NHAT", "THIEU_DONG_CHUYEN_VAO", "THIEU_DONG_CHUYEN_RA",
    "DUT_CHUOI_TRANG", "SO_TRANG_IN_LECH", "TRANG_DAU_CO_CHUYEN_VAO",
}


def refresh_page_totals(p) -> None:
    """Tính lại các số chuyển trang / tổng cộng từ dòng hiện tại (sau khi người dùng sửa)."""
    for kind, flag, no_attr, co_attr in (
            (RowKind.CARRY_IN, "has_carry_in_row", "carry_in_no", "carry_in_co"),
            (RowKind.CARRY_OUT, "has_carry_out_row", "carry_out_no", "carry_out_co"),
            (RowKind.GRAND_TOTAL, "has_grand_total_row", "grand_total_no", "grand_total_co")):
        rows = [r for r in p.rows if r.kind == kind]
        setattr(p, flag, bool(rows))
        setattr(p, no_attr, rows[0].amount_no if rows else None)
        setattr(p, co_attr, rows[0].amount_co if rows else None)


def voucher_key(v: str) -> str:
    return "".join(CONFUSE.get(ch, ch) for ch in v.strip().strip("."))


def _edit_distance_le1(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            j += 1
            if j - i > 1:
                return False
    return True


def _item(name, formula, expected, actual, applicable=True, note=""):
    diff = None if (expected is None or actual is None) else actual - expected
    ok = applicable and diff is not None and diff == ZERO
    return ReconcileItem(name=name, formula=formula, expected=expected,
                         actual=actual, diff=diff, ok=ok, applicable=applicable, note=note)


def heal_pairs(fr: FileResult) -> None:
    """Tự động đối chiếu cặp bút toán Nợ-Có cùng nghiệp vụ/chứng từ để chữa lỗi OCR mép số tiền."""
    for p in fr.pages:
        rows = [r for r in p.rows if r.kind == RowKind.ENTRY]
        for i in range(len(rows) - 1):
            r1, r2 = rows[i], rows[i + 1]
            same_voucher = bool(r1.cell(Col.SO_CT).value and r1.cell(Col.SO_CT).value == r2.cell(Col.SO_CT).value)
            same_desc = bool(r1.cell(Col.DIEN_GIAI).value and r1.cell(Col.DIEN_GIAI).value == r2.cell(Col.DIEN_GIAI).value)
            tk1 = r1.cell(Col.TAI_KHOAN).value
            tkdu1 = r1.cell(Col.TK_DOI_UNG).value
            tk2 = r2.cell(Col.TAI_KHOAN).value
            tkdu2 = r2.cell(Col.TK_DOI_UNG).value
            tk_rev = bool(tk1 and tk1 == tkdu2 and tkdu1 and tkdu1 == tk2)
            common_acct = bool((tkdu1 and tkdu1 == tk2) or (tk1 and tk1 == tkdu2))
            if same_voucher or same_desc or tk_rev or common_acct:
                # Đồng bộ số chứng từ bị thiếu chữ số cuối ở một trong 2 dòng của cặp
                if same_desc and (tk_rev or common_acct):
                    v1 = (r1.cell(Col.SO_CT).value or "").strip()
                    v2 = (r2.cell(Col.SO_CT).value or "").strip()
                    if v1 and v2 and v1 != v2:
                        if len(v2) > len(v1) and v2.startswith(v1):
                            r1.cell(Col.SO_CT).value = v2
                        elif len(v1) > len(v2) and v1.startswith(v2):
                            r2.cell(Col.SO_CT).value = v1
                if r1.amount_no is not None and r2.amount_co is None:
                    raw2 = "".join(ch for ch in r2.cell(Col.PS_CO).raw if ch.isdigit())
                    raw1 = str(r1.amount_no)
                    if not raw2 or _edit_distance_le1(raw1, raw2) or raw1.startswith(raw2) or raw2.startswith(raw1):
                        r2.cell(Col.PS_CO).value = r1.amount_no
                elif r2.amount_co is not None and r1.amount_no is None:
                    raw1 = "".join(ch for ch in r1.cell(Col.PS_NO).raw if ch.isdigit())
                    raw2 = str(r2.amount_co)
                    if not raw1 or _edit_distance_le1(raw1, raw2) or raw2.startswith(raw1) or raw1.startswith(raw2):
                        r1.cell(Col.PS_NO).value = r2.amount_co


def infer_missing_carry_totals(fr: FileResult) -> None:
    """Tự động suy luận số chuyển trang bị sót OCR nếu trang trước/sau hoặc phương trình trang khớp 100%."""
    pages = sorted(
        [p for p in fr.pages if p.rows and not p.info_page],
        key=lambda p: (p.printed_page if p.printed_page is not None else p.page_index + 1)
    )
    if not pages:
        return

    # 1. Trang đầu tiên: nếu phát sinh Có = 0 và carry_out_co is None, hoặc phát sinh Nợ = 0
    p0 = pages[0]
    if p0.has_carry_out_row:
        if p0.carry_out_no is None and p0.sum_no() == ZERO:
            p0.carry_out_no = ZERO
        if p0.carry_out_co is None and p0.sum_co() == ZERO:
            p0.carry_out_co = ZERO

    # 2. Chiều xuôi (Forward pass): Trang trước chuyển sang (p+1) = Chuyển sang sau (p)
    for i in range(len(pages) - 1):
        p, nxt = pages[i], pages[i + 1]
        if nxt.has_carry_in_row:
            if nxt.carry_in_no is None and p.carry_out_no is not None:
                nxt.carry_in_no = p.carry_out_no
                for r in nxt.rows:
                    if r.kind == RowKind.CARRY_IN:
                        r.cell(Col.PS_NO).value = p.carry_out_no
            if nxt.carry_in_co is None and p.carry_out_co is not None:
                nxt.carry_in_co = p.carry_out_co
                for r in nxt.rows:
                    if r.kind == RowKind.CARRY_IN:
                        r.cell(Col.PS_CO).value = p.carry_out_co

    # 3. Chiều ngược (Backward pass): Chuyển sang sau (p) = Trang trước chuyển sang (p+1)
    for i in range(len(pages) - 1, 0, -1):
        nxt, p = pages[i], pages[i - 1]
        if p.has_carry_out_row:
            if p.carry_out_no is None and nxt.carry_in_no is not None:
                p.carry_out_no = nxt.carry_in_no
                for r in p.rows:
                    if r.kind == RowKind.CARRY_OUT:
                        r.cell(Col.PS_NO).value = nxt.carry_in_no
            if p.carry_out_co is None and nxt.carry_in_co is not None:
                p.carry_out_co = nxt.carry_in_co
                for r in p.rows:
                    if r.kind == RowKind.CARRY_OUT:
                        r.cell(Col.PS_CO).value = nxt.carry_in_co
        elif not p.has_grand_total_row and nxt.has_carry_in_row:
            # Trang in kín dòng không in chữ 'Cộng chuyển sang sau' nhưng khớp số liệu với trang kế
            ps_no, ps_co = p.sum_no(), p.sum_co()
            cin_no = p.carry_in_no if p.carry_in_no is not None or i == 1 else ZERO
            cin_co = p.carry_in_co if p.carry_in_co is not None or i == 1 else ZERO
            if cin_no is not None and nxt.carry_in_no is not None and (cin_no + ps_no == nxt.carry_in_no):
                p.carry_out_no = nxt.carry_in_no
                p.has_carry_out_row = True
            if cin_co is not None and nxt.carry_in_co is not None and (cin_co + ps_co == nxt.carry_in_co):
                p.carry_out_co = nxt.carry_in_co
                p.has_carry_out_row = True

    # 4. Kiểm tra phương trình nội bộ trang: Vào + Phát sinh = Ra
    for p in pages:
        ps_no, ps_co = p.sum_no(), p.sum_co()
        if p.has_carry_out_row:
            if p.carry_out_no is None and p.carry_in_no is not None:
                p.carry_out_no = p.carry_in_no + ps_no
                for r in p.rows:
                    if r.kind == RowKind.CARRY_OUT:
                        r.cell(Col.PS_NO).value = p.carry_out_no
            if p.carry_out_co is None and p.carry_in_co is not None:
                p.carry_out_co = p.carry_in_co + ps_co
                for r in p.rows:
                    if r.kind == RowKind.CARRY_OUT:
                        r.cell(Col.PS_CO).value = p.carry_out_co


def reconcile_file(fr: FileResult) -> list:
    heal_pairs(fr)
    infer_missing_carry_totals(fr)
    # chạy lại sau mỗi lần sửa: thay cảnh báo cũ nhưng giữ xác nhận sai lệch nguồn
    resolved = {(w.code, w.page_index, w.row_index, w.col): (w.resolved, w.resolution)
                for w in fr.warnings if w.code in RECONCILE_CODES and w.resolved}
    fr.warnings = [w for w in fr.warnings if w.code not in RECONCILE_CODES]
    items = []
    pages = sorted(
        [p for p in fr.pages if p.rows and not p.info_page],
        key=lambda p: (p.printed_page if p.printed_page is not None else p.page_index + 1)
    )
    n = len(pages)
    for i, p in enumerate(pages):
        ps_no, ps_co = p.sum_no(), p.sum_co()
        label = f"Trang {p.page_index + 1}"
        if i == 0:
            if p.has_carry_in_row:
                fr.warnings.append(WarningItem(
                    code="TRANG_DAU_CO_CHUYEN_VAO",
                    message=f"{label}: có dòng “Số trang trước chuyển sang” (sổ nối tiếp kỳ trước).",
                    level=WarningLevel.INFO, page_index=p.page_index))
            if p.has_carry_out_row:
                if p.has_carry_in_row:
                    items.append(_item(f"{label}: vào + phát sinh = chuyển sang sau (Nợ)",
                                       "Vào_Nợ + PhátSinh_Nợ = Ra_Nợ", p.carry_out_no,
                                       (p.carry_in_no or ZERO) + ps_no))
                    items.append(_item(f"{label}: vào + phát sinh = chuyển sang sau (Có)",
                                       "Vào_Có + PhátSinh_Có = Ra_Có", p.carry_out_co,
                                       (p.carry_in_co or ZERO) + ps_co))
                else:
                    items.append(_item(f"{label}: phát sinh = chuyển sang sau (Nợ)",
                                       "PhátSinh_Nợ = Ra_Nợ", p.carry_out_no, ps_no))
                    items.append(_item(f"{label}: phát sinh = chuyển sang sau (Có)",
                                       "PhátSinh_Có = Ra_Có", p.carry_out_co, ps_co))
        else:
            if not p.has_carry_in_row:
                fr.warnings.append(WarningItem(
                    code="THIEU_DONG_CHUYEN_VAO",
                    message=f"{label}: thiếu dòng “Số trang trước chuyển sang”. Vui lòng đối chiếu ảnh nguồn.",
                    level=WarningLevel.EXTRACTION, page_index=p.page_index))
            if p.has_grand_total_row:
                items.append(_item(f"{label}: vào + phát sinh = tổng cộng (Nợ)",
                                   "Vào_Nợ + PhátSinh_Nợ = TổngCộng_Nợ",
                                   p.grand_total_no,
                                   (p.carry_in_no or ZERO) + ps_no if p.carry_in_no is not None else None))
                items.append(_item(f"{label}: vào + phát sinh = tổng cộng (Có)",
                                   "Vào_Có + PhátSinh_Có = TổngCộng_Có",
                                   p.grand_total_co,
                                   (p.carry_in_co or ZERO) + ps_co if p.carry_in_co is not None else None))
            elif p.has_carry_out_row:
                items.append(_item(f"{label}: vào + phát sinh = chuyển sang sau (Nợ)",
                                   "Vào_Nợ + PhátSinh_Nợ = Ra_Nợ", p.carry_out_no,
                                   (p.carry_in_no or ZERO) + ps_no if p.carry_in_no is not None else None))
                items.append(_item(f"{label}: vào + phát sinh = chuyển sang sau (Có)",
                                   "Vào_Có + PhátSinh_Có = Ra_Có", p.carry_out_co,
                                   (p.carry_in_co or ZERO) + ps_co if p.carry_in_co is not None else None))
            else:
                fr.warnings.append(WarningItem(
                    code="THIEU_DONG_CHUYEN_RA",
                    message=f"{label}: thiếu dòng “Cộng chuyển sang trang sau” hoặc “Tổng cộng”. Vui lòng đối chiếu ảnh nguồn.",
                    level=WarningLevel.EXTRACTION, page_index=p.page_index))

        if i + 1 < n:
            nxt = pages[i + 1]
            if p.info_page or nxt.info_page:
                pass
            elif p.has_carry_out_row and nxt.has_carry_in_row:
                items.append(_item(f"Chuỗi trang {p.page_index + 1}→{nxt.page_index + 1} (Nợ)",
                                   "Ra_Nợ(p) = Vào_Nợ(p+1)", nxt.carry_in_no, p.carry_out_no))
                items.append(_item(f"Chuỗi trang {p.page_index + 1}→{nxt.page_index + 1} (Có)",
                                   "Ra_Có(p) = Vào_Có(p+1)", nxt.carry_in_co, p.carry_out_co))
            else:
                fr.warnings.append(WarningItem(
                    code="DUT_CHUOI_TRANG",
                    message=f"Không nối được chuỗi chuyển trang giữa trang {p.page_index + 1} và {nxt.page_index + 1}. Vui lòng kiểm tra thiếu/trùng/sai thứ tự trang.",
                    level=WarningLevel.EXTRACTION, page_index=p.page_index))

    for p in fr.pages:
        if p.printed_page is not None and p.printed_page != p.page_index + 1:
            fr.warnings.append(WarningItem(
                code="SO_TRANG_IN_LECH",
                message=f"Trang PDF thứ {p.page_index + 1} in số trang {p.printed_page}. Vui lòng kiểm tra thứ tự trang của sổ.",
                level=WarningLevel.EXTRACTION, page_index=p.page_index))

    # chứng từ: nhóm các dòng bút toán theo nghiệp vụ (xuyên trang, chịu lỗi OCR số chứng từ)
    from .intelligent_reconcile import group_voucher_transactions
    voucher_groups = group_voucher_transactions(fr)
    for g in voucher_groups:
        raw_vouchers = set()
        for p, r in g["rows"]:
            val = (r.cell(Col.SO_CT).value or "").strip()
            if val:
                raw_vouchers.add(val)
        if len(raw_vouchers) > 1:
            first_p, first_r = g["rows"][0]
            is_balanced = (g["no"] == g["co"])
            if is_balanced:
                fr.warnings.append(WarningItem(
                    code="SO_CT_KHONG_THONG_NHAT",
                    message=f"Chứng từ {g['voucher']} (trang {first_p.page_index + 1}): số chứng từ các dòng khác nhau ({', '.join(sorted(raw_vouchers))}), đã tự động khớp theo nghiệp vụ đối ứng cân đối Nợ=Có.",
                    level=WarningLevel.INFO,
                    page_index=first_p.page_index,
                    row_index=first_r.row_index,
                    resolved=True,
                    resolution="Đã tự động cân đối đối ứng."))
            else:
                fr.warnings.append(WarningItem(
                    code="SO_CT_KHONG_THONG_NHAT",
                    message=f"Chứng từ {g['voucher']} (trang {first_p.page_index + 1}): số chứng từ các dòng không đồng nhất ({', '.join(sorted(raw_vouchers))}). Đã gộp theo nghiệp vụ đối ứng.",
                    level=WarningLevel.EXTRACTION,
                    page_index=first_p.page_index,
                    row_index=first_r.row_index))

        if g["no"] != g["co"]:
            first_p, first_r = g["rows"][0]
            fr.warnings.append(WarningItem(
                code="CHUNG_TU_KHONG_CAN",
                message=f"Chứng từ {g['voucher']} (trang {first_p.page_index + 1}): tổng Nợ {g['no']:,} khác tổng Có {g['co']:,}. Phần mềm giữ nguyên số liệu, không tự sửa.",
                level=WarningLevel.ACCOUNTING, page_index=first_p.page_index,
                row_index=first_r.row_index))

    tn, tc = fr.total_no(), fr.total_co()
    items.append(_item("Toàn sổ: Tổng Nợ = Tổng Có", "TổngNợ - TổngCó = 0", tc, tn))
    if tn != tc:
        fr.warnings.append(WarningItem(
            code="TOAN_SO_KHONG_CAN",
            message=f"Toàn sổ: Tổng Nợ {tn:,} khác Tổng Có {tc:,} (chênh {tn - tc:,}). Nếu PDF gốc in sai, hãy xác nhận sai lệch nguồn.",
            level=WarningLevel.ACCOUNTING))

    for it in items:
        if it.applicable and not it.ok:
            diff_msg = f"{it.diff:,}" if it.diff is not None else "không xác định"
            fr.warnings.append(WarningItem(
                code="CONG_THUC_LECH",
                message=f"{it.name}: chênh lệch {diff_msg}. Vui lòng đối chiếu các dòng liên quan với ảnh PDF.",
                level=WarningLevel.EXTRACTION,
                page_index=_page_of(fr, it.name)))
    for w in fr.warnings:
        if w.code in RECONCILE_CODES:
            old = resolved.get((w.code, w.page_index, w.row_index, w.col))
            if old:
                w.resolved, w.resolution = old
    fr.reconcile = items
    fr.accounting = compute_accounting(fr)
    return items


def _page_of(fr, name):
    import re
    m = re.search(r"Trang (\d+)", name)
    return int(m.group(1)) - 1 if m else None


def compute_accounting(fr: FileResult) -> AccountingCheck:
    acc = [w for w in fr.warnings if w.level == WarningLevel.ACCOUNTING]
    if not acc:
        return AccountingCheck.CAN_DOI
    if all(w.resolved for w in acc):
        return AccountingCheck.SAI_LECH_NGUON
    return AccountingCheck.CHUA_KIEM_TRA


def can_export_final(fr: FileResult) -> tuple:
    """Điều kiện trạng thái “Đã đối chiếu khớp PDF”."""
    reasons = []
    if fr.processed_pages < fr.page_count:
        reasons.append("Còn trang chưa xử lý.")
    if fr.unconfirmed_pages():
        reasons.append("Còn trang chưa được xác nhận trong chế độ nghiêm ngặt.")
    if fr.open_extraction_warnings():
        reasons.append("Còn cảnh báo trích xuất chưa xử lý.")
    for p in fr.pages:
        for r in p.rows:
            if r.kind == RowKind.UNKNOWN:
                reasons.append(f"Trang {p.page_index + 1} còn dòng chưa phân loại.")
                break
    return (len(reasons) == 0), reasons
