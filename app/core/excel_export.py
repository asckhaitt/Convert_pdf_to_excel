"""Xuất workbook 3 sheet và mở lại kiểm tra khớp dữ liệu đã duyệt."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .model import (Col, COLUMN_ORDER, COLUMN_TITLES, FileResult, FileStatus,
                    RowKind)
from .reconcile import can_export_final

HEADER_FILL = PatternFill("solid", fgColor="DDEBF7")
WARN_FILL = PatternFill("solid", fgColor="FCE4D6")


def _amount_format(values) -> str:
    decs = 0
    for v in values:
        if isinstance(v, Decimal):
            decs = max(decs, max(0, -v.as_tuple().exponent))
    return "#,##0" if decs == 0 else "#,##0." + "0" * decs


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while True:
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1


def export_workbook(fr: FileResult, out_dir: str, final: bool) -> str:
    if final:
        ok, reasons = can_export_final(fr)
        if not ok:
            raise PermissionError("Chưa đủ điều kiện xuất file cuối: " + " ".join(reasons))
    suffix = "_DA_DOI_CHIEU.xlsx" if final else "_CHUA_XAC_NHAN.xlsx"
    target = _unique_path(Path(out_dir) / (Path(fr.path).stem + suffix))
    target.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Nhật ký chung"
    extra_headers = ["Trang số", "Cộng chuyển sang trang sau (Nợ)", "Cộng chuyển sang trang sau (Có)"]
    ws.append([COLUMN_TITLES[c] for c in COLUMN_ORDER] + extra_headers)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    sorted_pages = sorted(
        [p for p in fr.pages if not p.info_page],
        key=lambda p: (p.printed_page if p.printed_page is not None else (p.page_index + 1))
    )
    entries = []
    page_for_entry = []
    for p in sorted_pages:
        p_entries = list(p.entry_rows())
        entries.extend(p_entries)
        page_for_entry.extend([p] * len(p_entries))

    no_vals = [r.amount_no for r in entries if r.amount_no is not None]
    co_vals = [r.amount_co for r in entries if r.amount_co is not None]
    fmt_no, fmt_co = _amount_format(no_vals), _amount_format(co_vals)

    for idx, r in enumerate(entries):
        row = []
        for c in COLUMN_ORDER:
            v = r.cell(c).value
            if c in (Col.PS_NO, Col.PS_CO):
                row.append(float(v) if isinstance(v, Decimal) else None)
            elif isinstance(v, date):
                row.append(v)
            else:
                row.append(v if v not in ("", None) else None)
        # Cột Trang số sau cột Phát sinh Có
        p = page_for_entry[idx]
        p_num = (p.printed_page if p and p.printed_page is not None else (p.page_index + 1))
        row.append(p_num)

        # Cột Cộng chuyển sang trang sau (Nợ) & (Có) - chỉ điền ở dòng cuối của trang: công thức SUM từ dòng 2 đến dòng hiện tại
        is_last_in_page = (idx == len(entries) - 1) or (page_for_entry[idx + 1] != p)
        curr_row = idx + 2
        if is_last_in_page:
            row.append(f"=SUM(G2:G{curr_row})")
            row.append(f"=SUM(H2:H{curr_row})")
        else:
            row.append(None)
            row.append(None)

        ws.append(row)
        i = ws.max_row
        for ci, c in enumerate(COLUMN_ORDER, start=1):
            cell = ws.cell(row=i, column=ci)
            if c in (Col.NGAY_HT, Col.NGAY_CT):
                cell.number_format = "dd/mm/yyyy"
            elif c == Col.PS_NO:
                cell.number_format = fmt_no
            elif c == Col.PS_CO:
                cell.number_format = fmt_co
            elif c in (Col.SO_CT, Col.TAI_KHOAN, Col.TK_DOI_UNG):
                cell.number_format = "@"
            if c == Col.DIEN_GIAI:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

        page_cell = ws.cell(row=i, column=len(COLUMN_ORDER) + 1)
        page_cell.alignment = Alignment(horizontal="center", vertical="center")
        page_cell.number_format = "0"

        c_no_cell = ws.cell(row=i, column=len(COLUMN_ORDER) + 2)
        c_no_cell.alignment = Alignment(horizontal="right", vertical="center")
        c_no_cell.number_format = fmt_no

        c_co_cell = ws.cell(row=i, column=len(COLUMN_ORDER) + 3)
        c_co_cell.alignment = Alignment(horizontal="right", vertical="center")
        c_co_cell.number_format = fmt_co

    widths = [13, 13, 14, 60, 10, 10, 18, 18, 12, 22, 22]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    last_entry_row = ws.max_row
    ws.auto_filter.ref = f"A1:K{last_entry_row}"

    # Dòng Tổng cộng cuối bảng
    tot_row_idx = last_entry_row + 1
    total_row = [None] * (len(COLUMN_ORDER) + len(extra_headers))
    total_row[COLUMN_ORDER.index(Col.DIEN_GIAI)] = "Tổng cộng"
    start_row = 2
    end_row = max(2, last_entry_row)
    total_row[COLUMN_ORDER.index(Col.PS_NO)] = f"=SUM(G{start_row}:G{end_row})"
    total_row[COLUMN_ORDER.index(Col.PS_CO)] = f"=SUM(H{start_row}:H{end_row})"
    ws.append(total_row)

    total_border = Border(top=Side(style="thin"), bottom=Side(style="double"))
    total_font = Font(bold=True, size=11)
    total_fill = PatternFill("solid", fgColor="F2F2F2")
    for ci in range(1, len(COLUMN_ORDER) + len(extra_headers) + 1):
        cell = ws.cell(row=tot_row_idx, column=ci)
        cell.font = total_font
        cell.border = total_border
        cell.fill = total_fill
        if ci <= len(COLUMN_ORDER):
            c = COLUMN_ORDER[ci - 1]
            if c == Col.PS_NO:
                cell.number_format = fmt_no
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif c == Col.PS_CO:
                cell.number_format = fmt_co
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif c == Col.DIEN_GIAI:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    _write_doi_soat(wb.create_sheet("Đối soát"), fr)
    _write_thong_tin(wb.create_sheet("Thông tin"), fr, final)
    wb.save(target)
    if final:
        fr.final_excel = str(target)
    else:
        fr.draft_excel = str(target)
    return str(target)


def _write_doi_soat(ws, fr: FileResult):
    bold = Font(bold=True)
    ws.append(["ĐỐI SOÁT CHUYỂN TRANG VÀ KIỂM TRA KẾ TOÁN"])
    ws["A1"].font = bold
    ws.append([])
    ws.append(["Trang", "Số trang trước chuyển sang (Nợ)", "Số trang trước chuyển sang (Có)",
               "Tổng phát sinh trong trang (Nợ)", "Tổng phát sinh trong trang (Có)",
               "Cộng chuyển sang trang sau (Nợ)", "Cộng chuyển sang trang sau (Có)",
               "Chênh lệch Nợ", "Chênh lệch Có", "Ghi chú"])
    for c in ws[3]:
        c.font = bold
        c.fill = HEADER_FILL
    sorted_pages = sorted(
        [p for p in fr.pages if not p.info_page],
        key=lambda p: (p.printed_page if p.printed_page is not None else (p.page_index + 1))
    )
    for p in sorted_pages:
        ps_no, ps_co = p.sum_no(), p.sum_co()
        if p.has_grand_total_row:
            exp_no = (p.carry_in_no or Decimal(0)) + ps_no if p.carry_in_no is not None else None
            exp_co = (p.carry_in_co or Decimal(0)) + ps_co if p.carry_in_co is not None else None
            dn = None if exp_no is None or p.grand_total_no is None else p.grand_total_no - exp_no
            dc = None if exp_co is None or p.grand_total_co is None else p.grand_total_co - exp_co
            note = "Đối chiếu với dòng Tổng cộng"
        elif p.has_carry_out_row:
            exp_no = (p.carry_in_no or Decimal(0)) + ps_no if p.carry_in_no is not None else ps_no
            exp_co = (p.carry_in_co or Decimal(0)) + ps_co if p.carry_in_co is not None else ps_co
            dn = None if p.carry_out_no is None else p.carry_out_no - exp_no
            dc = None if p.carry_out_co is None else p.carry_out_co - exp_co
            note = "" if p.has_carry_in_row else "Trang đầu sổ"
        else:
            dn = dc = None
            note = "Thiếu dòng chuyển trang / tổng cộng"
        ws.append([p.printed_page or (p.page_index + 1),
                   float(p.carry_in_no) if p.carry_in_no is not None else None,
                   float(p.carry_in_co) if p.carry_in_co is not None else None,
                   float(ps_no), float(ps_co),
                   float(p.carry_out_no) if p.carry_out_no is not None else None,
                   float(p.carry_out_co) if p.carry_out_co is not None else None,
                   float(dn) if dn is not None else None,
                   float(dc) if dc is not None else None, note])
        for ci in range(2, 10):
            ws.cell(row=ws.max_row, column=ci).number_format = "#,##0"
    ws.append([])
    ws.append(["Tổng Nợ toàn sổ", float(fr.total_no()), "Tổng Có toàn sổ", float(fr.total_co()),
               "Chênh lệch", float(fr.total_no() - fr.total_co())])
    ws.cell(row=ws.max_row, column=1).font = bold
    for ci in (2, 4, 6):
        ws.cell(row=ws.max_row, column=ci).number_format = "#,##0"
    ws.append(["Số dòng hạch toán", len(list(fr.entry_rows()))])
    ws.append([])
    ws.append(["CÔNG THỨC ĐỐI SOÁT"])
    ws.cell(row=ws.max_row, column=1).font = bold
    ws.append(["Nội dung", "Công thức", "Số trên PDF", "Số trích xuất", "Chênh lệch", "Kết quả"])
    for c in ws[ws.max_row]:
        c.font = bold
    for it in fr.reconcile:
        ws.append([it.name, it.formula,
                   float(it.expected) if it.expected is not None else None,
                   float(it.actual) if it.actual is not None else None,
                   float(it.diff) if it.diff is not None else None,
                   "Khớp" if it.ok else ("Không áp dụng" if not it.applicable else "Lệch")])
        for ci in (3, 4, 5):
            ws.cell(row=ws.max_row, column=ci).number_format = "#,##0"
        if not it.ok and it.applicable:
            for ci in range(1, 7):
                ws.cell(row=ws.max_row, column=ci).fill = WARN_FILL
    ws.append([])
    ws.append(["CẢNH BÁO KẾ TOÁN (giữ nguyên, không tự sửa)"])
    ws.cell(row=ws.max_row, column=1).font = bold
    from .model import WarningLevel
    acc = [w for w in fr.warnings if w.level == WarningLevel.ACCOUNTING]
    if not acc:
        ws.append(["Không có cảnh báo kế toán."])
    for w in acc:
        ws.append([w.message, "Đã xác nhận sai lệch nguồn" if w.resolved else "Chưa xác nhận", w.resolution])
    ws.append([])
    ws.append(["DÒNG KHÔNG ĐƯA VÀO SHEET NGHIỆP VỤ"])
    ws.cell(row=ws.max_row, column=1).font = bold
    ws.append(["Trang", "Dòng", "Loại", "Lý do loại", "Nội dung nhận diện"])
    for c in ws[ws.max_row]:
        c.font = bold
    for p in fr.pages:
        for r in p.rows:
            if r.kind == RowKind.ENTRY:
                continue
            txt = r.cell(Col.DIEN_GIAI).raw or " / ".join(
                r.cell(c).raw for c in COLUMN_ORDER if r.cell(c).raw)
            ws.append([p.printed_page or (p.page_index + 1), r.row_index + 1, r.kind.value,
                       r.excluded_reason or "Dòng chưa rõ", txt.replace("\n", " / ")])
    ws.append([])
    ws.append(["Trạng thái đối chiếu PDF", fr.status.value])
    ws.append(["Kết quả kiểm tra kế toán", fr.accounting.value])
    for i, w in enumerate([10, 30, 30, 30, 30, 30, 30, 16, 16, 40], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _write_thong_tin(ws, fr: FileResult, final: bool):
    from ..version import VERSION
    rows = [
        ("Tên PDF nguồn", Path(fr.path).name),
        ("Mã SHA-256", fr.sha256),
        ("Số trang", fr.page_count),
        ("Số trang đã xử lý", fr.processed_pages),
        ("Ngày giờ xử lý", datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
        ("Phiên bản phần mềm", VERSION),
        ("Mô hình OCR", "Tesseract vie (tessdata_best)"),
        ("Trạng thái đối chiếu", fr.status.value),
        ("Kết quả kiểm tra kế toán", fr.accounting.value),
        ("Loại file", "Đã đối chiếu khớp PDF" if final else "Nháp – cần đối chiếu"),
    ]
    for k, v in rows:
        ws.append([k, v])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 80


def verify_workbook(fr: FileResult, path: str) -> list:
    """Mở lại file và so 100% giá trị, kiểu, thứ tự với dữ liệu đã duyệt."""
    problems = []
    wb = load_workbook(path, data_only=False)
    if wb.sheetnames != ["Nhật ký chung", "Đối soát", "Thông tin"]:
        problems.append("Sai tên hoặc thứ tự sheet.")
    ws = wb["Nhật ký chung"]
    titles = [c.value for c in ws[1]]
    extra_headers = ["Trang số", "Cộng chuyển sang trang sau (Nợ)", "Cộng chuyển sang trang sau (Có)"]
    expected_titles = [COLUMN_TITLES[c] for c in COLUMN_ORDER] + extra_headers
    if titles != expected_titles:
        problems.append(f"Sai tiêu đề các cột: got {titles} != expected {expected_titles}.")
    sorted_pages = sorted(
        [p for p in fr.pages if not p.info_page],
        key=lambda p: (p.printed_page if p.printed_page is not None else (p.page_index + 1))
    )
    entries = []
    page_for_entry = []
    for p in sorted_pages:
        p_entries = list(p.entry_rows())
        entries.extend(p_entries)
        page_for_entry.extend([p] * len(p_entries))

    if ws.max_row - 2 != len(entries):
        problems.append(f"Số dòng lệch: Excel {ws.max_row - 2}, dữ liệu duyệt {len(entries)}.")
    for i, r in enumerate(entries):
        for ci, c in enumerate(COLUMN_ORDER, start=1):
            got = ws.cell(row=i + 2, column=ci).value
            want = r.cell(c).value
            if c in (Col.PS_NO, Col.PS_CO):
                if want is None:
                    if got is not None:
                        problems.append(f"Dòng {i + 1} cột {COLUMN_TITLES[c]}: PDF trống nhưng Excel có giá trị.")
                elif got is None:
                    problems.append(f"Dòng {i + 1} cột {COLUMN_TITLES[c]}: thiếu số tiền.")
                else:
                    gd = Decimal(repr(float(got)))
                    if gd.quantize(Decimal(1).scaleb(want.as_tuple().exponent)) != want:
                        problems.append(f"Dòng {i + 1} cột {COLUMN_TITLES[c]}: lệch số tiền {got} != {want}.")
            elif isinstance(want, date):
                if not isinstance(got, datetime) or got.date() != want:
                    problems.append(f"Dòng {i + 1} cột {COLUMN_TITLES[c]}: sai ngày hoặc kiểu ngày.")
            else:
                w = want if want not in ("", None) else None
                g = got if got not in ("", None) else None
                if (w or None) != (g or None):
                    problems.append(f"Dòng {i + 1} cột {COLUMN_TITLES[c]}: “{g}” != “{w}”.")
                elif w is not None and not isinstance(got, str):
                    problems.append(f"Dòng {i + 1} cột {COLUMN_TITLES[c]}: phải là kiểu văn bản.")
        got_page = ws.cell(row=i + 2, column=len(COLUMN_ORDER) + 1).value
        p = page_for_entry[i]
        want_page = (p.printed_page if p and p.printed_page is not None else (p.page_index + 1))
        if got_page != want_page:
            problems.append(f"Dòng {i + 1} cột Trang số: {got_page} != {want_page}.")

        is_last = (i == len(entries) - 1) or (page_for_entry[i + 1] != p)
        got_c_no = ws.cell(row=i + 2, column=len(COLUMN_ORDER) + 2).value
        got_c_co = ws.cell(row=i + 2, column=len(COLUMN_ORDER) + 3).value
        curr_row = i + 2
        if is_last:
            exp_c_no = f"=SUM(G2:G{curr_row})"
            exp_c_co = f"=SUM(H2:H{curr_row})"
            if got_c_no != exp_c_no or got_c_co != exp_c_co:
                problems.append(f"Dòng {curr_row} sai công thức cộng chuyển trang: ({got_c_no}, {got_c_co}) != ({exp_c_no}, {exp_c_co}).")
        elif got_c_no is not None or got_c_co is not None:
            problems.append(f"Dòng {curr_row} không phải cuối trang nhưng có số cộng chuyển trang.")
    tot_row = len(entries) + 2
    tot_lbl = ws.cell(row=tot_row, column=COLUMN_ORDER.index(Col.DIEN_GIAI) + 1).value
    if tot_lbl != "Tổng cộng":
        problems.append(f"Dòng tổng cộng thiếu hoặc sai nhãn: “{tot_lbl}”.")
    tot_no = ws.cell(row=tot_row, column=COLUMN_ORDER.index(Col.PS_NO) + 1).value
    tot_co = ws.cell(row=tot_row, column=COLUMN_ORDER.index(Col.PS_CO) + 1).value
    exp_tot_no = f"=SUM(G2:G{tot_row - 1})"
    exp_tot_co = f"=SUM(H2:H{tot_row - 1})"
    if tot_no != exp_tot_no or tot_co != exp_tot_co:
        problems.append(f"Dòng tổng cộng sai công thức: ({tot_no}, {tot_co}) != ({exp_tot_no}, {exp_tot_co}).")
    wb.close()
    return problems
