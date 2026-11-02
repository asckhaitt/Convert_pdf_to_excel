"""Kiểm thử tính năng tự động cân đối và nhận dạng lại thông minh (Intelligent Reconcile)."""
from decimal import Decimal
from app.core.model import Col, CellValue, FileResult, PageResult, Rect, RowKind, SourceRow
from app.core.intelligent_reconcile import (
    parse_voucher_info, vouchers_match, accts_match,
    group_voucher_transactions, auto_reconcile_and_repair
)

def test_parse_voucher_info():
    assert parse_voucher_info("TNH15.061") == ("TNH", 61)
    assert parse_voucher_info("TNH15.062") == ("TNH", 62)
    assert parse_voucher_info("LUINC15.005") == ("UNC", 5)
    assert parse_voucher_info("UNC15.005") == ("UNC", 5)
    assert parse_voucher_info("UNC15.030/") == ("UNC", 30)
    assert parse_voucher_info("PC15.011.") == ("PC", 11)
    assert parse_voucher_info("PC5.011") == ("PC", 11)

def test_vouchers_match():
    # Cùng chứng từ dù OCR nhiễu
    assert vouchers_match("LUINC15.005", "UNC15.005") is True
    assert vouchers_match("PC15.011.", "PC5.011") is True
    assert vouchers_match("TNH15.010", "TNH5.010") is True
    # Khác số thứ tự -> không được gộp
    assert vouchers_match("TNH15.061", "TNH15.062") is False
    assert vouchers_match("UNC15.028", "UNC15.029") is False
    assert vouchers_match("UNC15.030/", "UNC15.031") is False

def test_accts_match():
    assert accts_match("1121", "1121") is True
    assert accts_match("15", "515") is True
    assert accts_match("21", "1121") is True
    assert accts_match("334", "3341") is True
    assert accts_match("1111", "1121") is False

def test_auto_strip_stray_1():
    """Kiểm tra tự động phát hiện nét viền dính số 1 (115 tỷ vs 15 tỷ)."""
    fr = FileResult(path="dummy.pdf", page_count=1)
    p = PageResult(page_index=0)
    r1 = SourceRow(page_index=0, row_index=0, kind=RowKind.ENTRY)
    r1.cells[Col.SO_CT] = CellValue(col=Col.SO_CT, raw="PC15.013", value="PC15.013")
    r1.cells[Col.TAI_KHOAN] = CellValue(col=Col.TAI_KHOAN, raw="1121", value="1121")
    r1.cells[Col.TK_DOI_UNG] = CellValue(col=Col.TK_DOI_UNG, raw="1111", value="1111")
    r1.cells[Col.PS_NO] = CellValue(col=Col.PS_NO, raw="15.000.000.000", value=Decimal("15000000000"))
    r1.cells[Col.PS_CO] = CellValue(col=Col.PS_CO, raw="", value=None)

    r2 = SourceRow(page_index=0, row_index=1, kind=RowKind.ENTRY)
    r2.cells[Col.SO_CT] = CellValue(col=Col.SO_CT, raw="PC15.013", value="PC15.013")
    r2.cells[Col.TAI_KHOAN] = CellValue(col=Col.TAI_KHOAN, raw="1111", value="1111")
    r2.cells[Col.TK_DOI_UNG] = CellValue(col=Col.TK_DOI_UNG, raw="1121", value="1121")
    r2.cells[Col.PS_NO] = CellValue(col=Col.PS_NO, raw="", value=None)
    r2.cells[Col.PS_CO] = CellValue(col=Col.PS_CO, raw="115.000.000.000", value=Decimal("115000000000"))

    p.rows = [r1, r2]
    fr.pages = [p]

    repairs = auto_reconcile_and_repair(fr)
    assert len(repairs) == 1
    assert repairs[0]["type"] == "STRIP_STRAY_1"
    assert r2.amount_co == Decimal("15000000000")
    assert fr.total_no() == fr.total_co() == Decimal("15000000000")

def test_auto_fill_missing_counterpart():
    """Kiểm tra tự động điền vế đối ứng bị thiếu (None) khi vế kia có số."""
    fr = FileResult(path="dummy.pdf", page_count=1)
    p = PageResult(page_index=0)
    r1 = SourceRow(page_index=0, row_index=0, kind=RowKind.ENTRY)
    r1.cells[Col.SO_CT] = CellValue(col=Col.SO_CT, raw="NVK15.070", value="NVK15.070")
    r1.cells[Col.TAI_KHOAN] = CellValue(col=Col.TAI_KHOAN, raw="15", value="15")
    r1.cells[Col.TK_DOI_UNG] = CellValue(col=Col.TK_DOI_UNG, raw="911", value="911")
    r1.cells[Col.PS_NO] = CellValue(col=Col.PS_NO, raw="49.2492", value=None)
    r1.cells[Col.PS_CO] = CellValue(col=Col.PS_CO, raw="", value=None)

    r2 = SourceRow(page_index=0, row_index=1, kind=RowKind.ENTRY)
    r2.cells[Col.SO_CT] = CellValue(col=Col.SO_CT, raw="NVK15.070", value="NVK15.070")
    r2.cells[Col.TAI_KHOAN] = CellValue(col=Col.TAI_KHOAN, raw="911", value="911")
    r2.cells[Col.TK_DOI_UNG] = CellValue(col=Col.TK_DOI_UNG, raw="515", value="515")
    r2.cells[Col.PS_NO] = CellValue(col=Col.PS_NO, raw="", value=None)
    r2.cells[Col.PS_CO] = CellValue(col=Col.PS_CO, raw="42.242", value=Decimal("42242"))

    p.rows = [r1, r2]
    fr.pages = [p]

    repairs = auto_reconcile_and_repair(fr)
    assert len(repairs) == 1
    assert repairs[0]["type"] == "FILL_PAIR_MATCH"
    assert r1.amount_no == Decimal("42242")
    assert fr.total_no() == fr.total_co() == Decimal("42242")

def test_sync_pair_accounts_and_dates():
    from datetime import date
    from app.core.intelligent_reconcile import sync_pair_accounts_and_dates

    r_no = SourceRow(page_index=0, row_index=0, kind=RowKind.ENTRY)
    r_no.cells[Col.NGAY_HT] = CellValue(col=Col.NGAY_HT, raw="31/12/2017", value=date(2017, 12, 31))
    r_no.cells[Col.NGAY_CT] = CellValue(col=Col.NGAY_CT, raw="31/12/2017", value=date(2017, 12, 31))
    r_no.cells[Col.TAI_KHOAN] = CellValue(col=Col.TAI_KHOAN, raw="1121", value="1121")
    r_no.cells[Col.TK_DOI_UNG] = CellValue(col=Col.TK_DOI_UNG, raw="515", value="515")
    r_no.cells[Col.PS_NO] = CellValue(col=Col.PS_NO, raw="7,569", value=Decimal("7569"))
    r_no.cells[Col.PS_CO] = CellValue(col=Col.PS_CO, raw="", value=None)

    r_co = SourceRow(page_index=0, row_index=1, kind=RowKind.ENTRY)
    r_co.cells[Col.NGAY_HT] = CellValue(col=Col.NGAY_HT, raw="", value=None)
    r_co.cells[Col.NGAY_CT] = CellValue(col=Col.NGAY_CT, raw="", value=None)
    r_co.cells[Col.TAI_KHOAN] = CellValue(col=Col.TAI_KHOAN, raw="15", value="15")  # bị cụt số 5
    r_co.cells[Col.TK_DOI_UNG] = CellValue(col=Col.TK_DOI_UNG, raw="1121", value="1121")
    r_co.cells[Col.PS_NO] = CellValue(col=Col.PS_NO, raw="", value=None)
    r_co.cells[Col.PS_CO] = CellValue(col=Col.PS_CO, raw="7,569", value=Decimal("7569"))

    sync_pair_accounts_and_dates(r_no, r_co)

    assert r_co.cell(Col.TAI_KHOAN).value == "515"
    assert r_co.cell(Col.NGAY_HT).value == date(2017, 12, 31)
    assert r_co.cell(Col.NGAY_CT).value == date(2017, 12, 31)

def test_group_voucher_transactions_out_of_order_pages():
    fr = FileResult(path="dummy.pdf", page_count=2)
    p_info = PageResult(page_index=0, printed_page=2, info_page=True)
    p_trans = PageResult(page_index=1, printed_page=1, info_page=False)

    r = SourceRow(page_index=1, row_index=0, kind=RowKind.ENTRY)
    r.cells[Col.SO_CT] = CellValue(col=Col.SO_CT, raw="PC01", value="PC01")
    p_trans.rows = [r]

    fr.pages = [p_info, p_trans]
    groups = group_voucher_transactions(fr)
    assert len(groups) == 1
    assert groups[0]["voucher"] == "PC01"

