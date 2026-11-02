"""Kiểm thử nghiệp vụ: chuẩn hóa, phân loại, đối soát, Excel, lưu vết."""
from datetime import date
from decimal import Decimal

import openpyxl
import pytest

from app.core import storage
from app.core.classify import classify_row
from app.core.excel_export import export_workbook, verify_workbook
from app.core.model import (Col, COLUMN_TITLES, CellValue, FileResult, FileStatus,
                            PageResult, RowKind, SourceRow, WarningLevel)
from app.core.normalize import normalize_cell, parse_account, parse_amount, parse_date
from app.core.reconcile import can_export_final, reconcile_file


def row(page, idx, kind=RowKind.ENTRY, ct="NVK15.001", no=None, co=None,
        tk="1111", du="5111", dg="Thu tiền bán hàng"):
    r = SourceRow(page_index=page, row_index=idx, kind=kind)
    raws = {Col.NGAY_HT: "01/01/2015", Col.NGAY_CT: "01/01/2015", Col.SO_CT: ct,
            Col.DIEN_GIAI: dg, Col.TAI_KHOAN: tk, Col.TK_DOI_UNG: du,
            Col.PS_NO: no or "", Col.PS_CO: co or ""}
    for col, raw in raws.items():
        value, warns = normalize_cell(col, raw, page, idx)
        r.cells[col] = CellValue(col=col, raw=raw, value=value, warnings=warns)
    return r


def carry(page, idx, kind, no, co):
    r = row(page, idx, kind=kind, ct="", no=no, co=co, tk="", du="",
            dg="Cộng chuyển sang trang sau" if kind == RowKind.CARRY_OUT
            else "Số trang trước chuyển sang")
    return r


def two_pages():
    p0 = PageResult(page_index=0)
    p0.rows = [row(0, 0, no="1.000.000"), row(0, 1, ct="NVK15.001", co="1.000.000", tk="5111", du="1111"),
               carry(0, 2, RowKind.CARRY_OUT, "1.000.000", "1.000.000")]
    p1 = PageResult(page_index=1)
    p1.rows = [carry(1, 0, RowKind.CARRY_IN, "1.000.000", "1.000.000"),
               row(1, 1, ct="NVK15.002", no="2.000.000"),
               row(1, 2, ct="NVK15.002", co="2.000.000", tk="5111", du="1111"),
               carry(1, 3, RowKind.CARRY_OUT, "3.000.000", "3.000.000")]
    for p in (p0, p1):
        for r in p.rows:
            if r.kind == RowKind.CARRY_OUT:
                p.has_carry_out_row, p.carry_out_no, p.carry_out_co = True, r.amount_no, r.amount_co
            if r.kind == RowKind.CARRY_IN:
                p.has_carry_in_row, p.carry_in_no, p.carry_in_co = True, r.amount_no, r.amount_co
    fr = FileResult(path="dummy.pdf", page_count=2, processed_pages=2)
    fr.pages = [p0, p1]
    return fr


# ---------------- chuẩn hóa ----------------
def test_amount_vn_formats():
    assert parse_amount("1.234.567", Col.PS_NO, 0, 0)[0] == Decimal(1234567)
    assert parse_amount("1.234.567,89", Col.PS_NO, 0, 0)[0] == Decimal("1234567.89")
    assert parse_amount("(1.000)", Col.PS_NO, 0, 0)[0] == Decimal(-1000)
    assert parse_amount("", Col.PS_NO, 0, 0) == (None, [])
    assert parse_amount("410.000.000.000.", Col.PS_NO, 0, 0)[0] == Decimal(410000000000)
    # Định dạng dấu phẩy ngăn nghìn (sổ 2016, 2018, 2019)
    assert parse_amount("772,285,664,112", Col.PS_NO, 0, 0)[0] == Decimal(772285664112)
    assert parse_amount("120,000", Col.PS_NO, 0, 0)[0] == Decimal(120000)
    assert parse_amount("1,266", Col.PS_NO, 0, 0)[0] == Decimal(1266)
    assert parse_amount("30,000,000,", Col.PS_NO, 0, 0)[0] == Decimal(30000000)
    assert parse_amount("1,234,567.89", Col.PS_NO, 0, 0)[0] == Decimal("1234567.89")
    # OCR nhầm lẫn dấu chấm và phẩy trong số tiền hàng nghìn VNĐ
    assert parse_amount("2,043.077", Col.PS_NO, 0, 0)[0] == Decimal(2043077)
    assert parse_amount("313,377,712.095", Col.PS_NO, 0, 0)[0] == Decimal(313377712095)
    assert parse_amount("10,898,994,361,269", Col.PS_NO, 0, 0)[0] == Decimal(10898994361269)
    assert parse_amount("10.898,994,361,269", Col.PS_NO, 0, 0)[0] == Decimal(10898994361269)
    # Khôi phục số tiền bị xén số 0 cuối ở mép bảng hoặc tàn dư mép ô
    assert parse_amount("3.000.00(", Col.PS_NO, 0, 0)[0] == Decimal(3000000)
    assert parse_amount("100,000,000,00", Col.PS_NO, 0, 0)[0] == Decimal(100000000000)
    assert parse_amount("168,500,000,00(", Col.PS_NO, 0, 0)[0] == Decimal(168500000000)
    assert parse_amount("248.750.000.00", Col.PS_NO, 0, 0)[0] == Decimal(248750000000)
    assert parse_amount("1,530,00", Col.PS_NO, 0, 0)[0] == Decimal(1530000)


def test_amount_ambiguous_warns():
    for raw in ("12.34", "1.234.56", "1,2,3"):
        val, warns = parse_amount(raw, Col.PS_NO, 0, 0)
        assert val is None and warns, raw
        assert warns[0].level == WarningLevel.EXTRACTION


def test_date_strict():
    assert parse_date("01/02/2015", Col.NGAY_HT, 0, 0)[0] == date(2015, 2, 1)
    assert parse_date("31/02/2015", Col.NGAY_HT, 0, 0)[0] is None
    assert parse_date("2015-01-01", Col.NGAY_HT, 0, 0)[0] is None
    assert parse_date("", Col.NGAY_HT, 0, 0) == (None, [])


def test_account_keeps_text_and_flags_confusion():
    assert parse_account("0111", Col.TAI_KHOAN, 0, 0)[0] == "0111"
    val, warns = parse_account("1I11", Col.TAI_KHOAN, 0, 0)
    assert val == "1I11" and warns[0].code == "TK_NHI_DOAN"


def test_voucher_normalization():
    from app.core.normalize import parse_voucher
    assert parse_voucher("UNCI16.004", Col.SO_CT, 0, 0)[0] == "UNC16.004"
    assert parse_voucher("UNGCI7.003", Col.SO_CT, 0, 0)[0] == "UNC17.003"
    assert parse_voucher("NVKI15.001", Col.SO_CT, 0, 0)[0] == "NVK15.001"
    assert parse_voucher("NVKI1S.001", Col.SO_CT, 0, 0)[0] == "NVK15.001"
    assert parse_voucher("TNH16.00\n2", Col.SO_CT, 0, 0)[0] == "TNH16.002"
    assert parse_voucher("NVK15.005.", Col.SO_CT, 0, 0)[0] == "NVK15.005"
    assert parse_voucher("UNC17.001.", Col.SO_CT, 0, 0)[0] == "UNC17.001"
    assert parse_voucher("PC18.003", Col.SO_CT, 0, 0)[0] == "PC18.003"


def test_dien_giai_cleaning():
    v, _ = normalize_cell(Col.DIEN_GIAI, "Thuế GTGT đầu vào HĐ 0000283 |", 0, 0)
    assert v == "Thuế GTGT đầu vào HĐ 0000283"
    v2, _ = normalize_cell(Col.DIEN_GIAI, "| Chuyển từ TK 1388 sang TK\n| 3388 do 2014 |", 0, 0)
    assert v2 == "Chuyển từ TK 1388 sang TK\n3388 do 2014"


def test_classify():
    assert classify_row({Col.DIEN_GIAI: "Diễn giải", Col.TAI_KHOAN: "TI",
                         Col.TK_DOI_UNG: "TK"}) == RowKind.HEADER
    assert classify_row({Col.DIEN_GIAI: "Số trang trước chuyển sang"}) == RowKind.CARRY_IN
    assert classify_row({Col.DIEN_GIAI: "Cộng chuyển sang trang sau"}) == RowKind.CARRY_OUT
    assert classify_row({Col.DIEN_GIAI: "Tổng cộng"}) == RowKind.GRAND_TOTAL
    assert classify_row({Col.PS_NO: "1.000"}) == RowKind.ENTRY
    assert classify_row({Col.DIEN_GIAI: "chữ nối tiếp"}) == RowKind.UNKNOWN
    assert classify_row({}) == RowKind.EMPTY


# ---------------- đối soát ----------------
def test_balanced_book():
    fr = two_pages()
    items = reconcile_file(fr)
    assert all(it.ok for it in items if it.applicable)
    assert fr.accounting.value == "Cân đối"
    assert not fr.open_extraction_warnings()


def test_injected_amount_error_detected():
    fr = two_pages()
    fr.pages[1].rows[1].cells[Col.PS_NO].value = Decimal(2500000)
    reconcile_file(fr)
    codes = {w.code for w in fr.warnings}
    assert "CONG_THUC_LECH" in codes
    assert "CHUNG_TU_KHONG_CAN" in codes
    assert fr.accounting.value == "Chưa kiểm tra xong"
    for p in fr.pages:
        p.confirmed = True
    ok, reasons = can_export_final(fr)
    assert not ok and reasons


def test_source_error_confirmed_still_final():
    fr = two_pages()
    fr.pages[1].rows[1].cells[Col.PS_NO].value = Decimal(2500000)
    reconcile_file(fr)
    for w in fr.warnings:
        w.resolved = True
        w.resolution = "Sai lệch trên PDF gốc"
    reconcile_file(fr)  # xác nhận phải sống sót qua lần đối soát lại
    assert fr.accounting.value == "Có sai lệch trên PDF gốc"
    for p in fr.pages:
        p.confirmed = True
    ok, reasons = can_export_final(fr)
    assert ok, reasons


def test_chain_break_detected():
    fr = two_pages()
    fr.pages[1].carry_in_no = Decimal(999)
    reconcile_file(fr)
    assert any(w.code == "CONG_THUC_LECH" and "Chuỗi trang" in w.message for w in fr.warnings)


def test_voucher_ocr_split_merged():
    fr = two_pages()
    fr.pages[1].rows[2].cells[Col.SO_CT].value = "NVK15.0002"
    reconcile_file(fr)
    assert not any(w.code == "CHUNG_TU_KHONG_CAN" for w in fr.warnings)
    assert any(w.code == "SO_CT_KHONG_THONG_NHAT" for w in fr.warnings)


def test_final_gate_requires_all_pages():
    fr = two_pages()
    reconcile_file(fr)
    fr.processed_pages = 1
    ok, reasons = can_export_final(fr)
    assert not ok and any("chưa xử lý" in r for r in reasons)


# ---------------- Excel ----------------
def test_excel_roundtrip(tmp_path):
    fr = two_pages()
    fr.pages[0].rows[0].cells[Col.TAI_KHOAN].value = "0111"
    fr.pages[0].rows[0].cells[Col.TAI_KHOAN].raw = "0111"
    reconcile_file(fr)
    path = export_workbook(fr, str(tmp_path), final=False)
    assert verify_workbook(fr, path) == []
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["Nhật ký chung", "Đối soát", "Thông tin"]
    ws = wb["Nhật ký chung"]
    assert [c.value for c in ws[1]] == [COLUMN_TITLES[c] for c in
                                        [Col.NGAY_HT, Col.NGAY_CT, Col.SO_CT, Col.DIEN_GIAI,
                                         Col.TAI_KHOAN, Col.TK_DOI_UNG, Col.PS_NO, Col.PS_CO]] + [
                                             "Trang số", "Cộng chuyển sang trang sau (Nợ)", "Cộng chuyển sang trang sau (Có)"
                                         ]
    assert ws.max_row == 6  # 4 bút toán + tiêu đề + dòng tổng cộng
    assert ws["D6"].value == "Tổng cộng"
    assert ws["G6"].value == "=SUM(G2:G5)"
    assert ws["H6"].value == "=SUM(H2:H5)"
    assert ws["I2"].value == 1  # Trang số của bút toán trang 1
    assert ws["J2"].value is None  # Bút toán 1 chưa phải dòng cuối trang 1
    assert ws["K2"].value is None
    assert ws["J3"].value == "=SUM(G2:G3)"  # Dòng cuối trang 1 (bút toán 2) có công thức cộng chuyển sang trang sau
    assert ws["K3"].value == "=SUM(H2:H3)"
    assert ws["J4"].value is None  # Bút toán 3 chưa phải dòng cuối trang 2
    assert ws["J5"].value == "=SUM(G2:G5)"  # Dòng cuối trang 2 (bút toán 4)
    assert ws["K5"].value == "=SUM(H2:H5)"
    assert ws["A2"].value == date(2015, 1, 1) or ws["A2"].value.year == 2015
    assert ws["E2"].value == "0111" and isinstance(ws["E2"].value, str)
    assert ws["G2"].value == 1000000 and isinstance(ws["G2"].value, (int, float))
    assert ws["H2"].value is None  # ô trống giữ trống
    assert ws["G3"].value is None and ws["H3"].value == 1000000


def test_excel_verify_detects_tamper(tmp_path):
    fr = two_pages()
    reconcile_file(fr)
    path = export_workbook(fr, str(tmp_path), final=False)
    wb = openpyxl.load_workbook(path)
    wb["Nhật ký chung"]["G2"] = 777
    wb.save(path)
    assert verify_workbook(fr, path)


def test_excel_never_overwrites(tmp_path):
    fr = two_pages()
    reconcile_file(fr)
    p1 = export_workbook(fr, str(tmp_path), final=False)
    p2 = export_workbook(fr, str(tmp_path), final=False)
    assert p1 != p2


def test_final_export_blocked(tmp_path):
    fr = two_pages()
    reconcile_file(fr)
    with pytest.raises(PermissionError):
        export_workbook(fr, str(tmp_path), final=True)


# ---------------- lưu vết ----------------
def test_storage_roundtrip(tmp_path):
    fr = two_pages()
    reconcile_file(fr)
    fr.pages[0].confirmed = True
    con = storage.open_db(str(tmp_path / "phien.sqlite"))
    storage.save_file_result(con, fr)
    storage.add_history(con, fr.path, "sua_o", "thử")
    got = storage.load_file_result(con, fr.path)
    assert got.pages[0].confirmed
    assert got.pages[1].rows[1].amount_no == Decimal(2000000)
    assert len(got.warnings) == len(fr.warnings)
    assert got.status == fr.status
    n = con.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    assert n == 1


def test_infer_missing_carry_totals():
    fr = two_pages()
    # Giả lập trang 2 bị sót nhận dạng carry_in_no
    fr.pages[1].carry_in_no = None
    reconcile_file(fr)
    # infer_missing_carry_totals phải tự điền từ carry_out_no của trang 1
    assert fr.pages[1].carry_in_no == fr.pages[0].carry_out_no


def test_balanced_voucher_warning_info():
    fr = two_pages()
    # Đổi số chứng từ dòng 2 khác dòng 1 nhưng tiền vẫn cân đối (Nợ = Có)
    fr.pages[0].rows[1].cells[Col.SO_CT].value = "HD001"
    reconcile_file(fr)
    # Phải có cảnh báo SO_CT_KHONG_THONG_NHAT nhưng đã tự resolved
    w = next(w for w in fr.warnings if w.code == "SO_CT_KHONG_THONG_NHAT")
    assert w.resolved is True
    assert w.level == WarningLevel.INFO


def test_image_view_highlight_ensure_visible(qtbot):
    from app.gui.image_view import ImageView
    from app.core.model import Rect
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(600, 800)
    view._scene.setSceneRect(0, 0, 2400, 3500)
    # Highlight một vùng ở phía dưới
    target = Rect(100, 1800, 400, 1850)
    view.highlight(target, ensure_visible=True)
    vis = view.mapToScene(view.viewport().rect()).boundingRect()
    # Kiểm tra viewport đã tự cuộn xuống bao phủ target
    assert vis.top() <= 1800 <= vis.bottom()