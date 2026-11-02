"""Chuẩn hóa giá trị ô theo từng loại, giữ ô trống và đánh dấu nghi ngờ."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from .model import Col, WarningItem, WarningLevel

DATE_RE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$")
AMOUNT_OK_RE = re.compile(r"^\(?\-?[\d.,]+\)?$")
CONFUSE = {"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"}


def norm_text(raw: str) -> str:
    return " ".join(raw.split())


def parse_date(raw: str, col: Col, page: int, row: int):
    """Trả về (date|None, danh sách cảnh báo). Không tự hoán đổi ngày."""
    warns = []
    s = norm_text(raw)
    if not s:
        return None, warns
    m = DATE_RE.match(s)
    if not m:
        warns.append(WarningItem(
            code="NGAY_SAI_DINH_DANG",
            message=f"Ngày tại trang {page + 1} không đúng dạng dd/mm/yyyy: “{s}”. Vui lòng đối chiếu ô được tô sáng với ảnh PDF.",
            level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
        return None, warns
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d), warns
    except ValueError:
        warns.append(WarningItem(
            code="NGAY_KHONG_HOP_LE",
            message=f"Ngày tại trang {page + 1} không hợp lệ: “{s}”. Vui lòng đối chiếu với ảnh PDF.",
            level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
        return None, warns


def parse_amount(raw: str, col: Col, page: int, row: int):
    """Số tiền kiểu Việt Nam và quốc tế:
    Hỗ trợ cả phân cách hàng nghìn bằng dấu chấm (2015, 2017)
    và phân cách hàng nghìn bằng dấu phẩy (2016, 2018, 2019).
    Giữ ô trống là None; không tự làm tròn; số trong ngoặc là số âm.
    """
    warns = []
    # Nếu có nhiều dòng trong ô tiền (do vết kẻ ô bị đứt), lấy dòng đầu tiên hoặc nối liền
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    if not lines:
        return None, warns
    raw_val = lines[0]  # xử lý giá trị chính của ô
    s = norm_text(raw_val).replace(" ", "")
    if not s:
        return None, warns
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    # Dấu chấm / phẩy / gạch nối / tàn dư mép ô do đường kẻ viền bảng
    s = s.strip(".,:;~_=-").rstrip("()")
    # Khắc phục vết mực / nhiễu OCR chèn thêm số 0 ngay sau dấu phân cách nghìn (ví dụ 7.0696.300 -> 7.696.300)
    s = re.sub(r"([.,])0(\d{3})(?=[.,]|$)", r"\1\2", s)
    if not s or not AMOUNT_OK_RE.match(s) or not any(ch.isdigit() for ch in s):
        warns.append(WarningItem(
            code="SO_TIEN_SAI_DINH_DANG",
            message=f"Số tiền tại trang {page + 1} có ký tự chưa rõ: “{raw}”. Vui lòng đối chiếu ô được tô sáng với ảnh PDF.",
            level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
        return None, warns

    int_part, dec_part = "", ""
    groups = re.split(r"[,.]", s)
    if len(groups) > 1 and all(len(g) == 3 for g in groups[1:]) and len(groups[0]) in (1, 2, 3) and all(g.isdigit() for g in groups):
        # 100% số nguyên có dấu phân cách hàng nghìn (kể cả khi OCR nhầm lẫn giữa dấu chấm và phẩy)
        int_part = "".join(groups)
    elif "," in s and "." in s:
        last_comma = s.rfind(",")
        last_dot = s.rfind(".")
        if last_comma > last_dot:
            # Dạng 1.234.567,89 (chấm ngăn nghìn, phẩy thập phân)
            int_part = s[:last_comma].replace(".", "")
            dec_part = s[last_comma + 1:]
        else:
            # Dạng 1,234,567.89 (phẩy ngăn nghìn, chấm thập phân)
            int_part = s[:last_dot].replace(",", "")
            dec_part = s[last_dot + 1:]
        if not int_part.isdigit() or not dec_part.isdigit():
            warns.append(WarningItem(
                code="SO_TIEN_MO_HO",
                message=f"Số tiền tại trang {page + 1} mơ hồ dấu chấm/phẩy: “{raw}”. Vui lòng xem ảnh gốc.",
                level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
            return None, warns
    elif "," in s:
        parts = s.split(",")
        if not all(p.isdigit() for p in parts):
            warns.append(WarningItem(
                code="SO_TIEN_MO_HO",
                message=f"Số tiền tại trang {page + 1} lẫn ký tự không rõ: “{raw}”.",
                level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
            return None, warns
        if len(parts) > 2:
            # Dạng 772,285,664,112 (nhiều dấu phẩy ngăn nghìn)
            if not all(len(p) == 3 for p in parts[1:]):
                warns.append(WarningItem(
                    code="SO_TIEN_MO_HO",
                    message=f"Số tiền tại trang {page + 1} mơ hồ dấu phẩy: “{raw}”. Vui lòng xem ảnh gốc.",
                    level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
                return None, warns
            int_part = "".join(parts)
        else:
            # len == 2, ví dụ: 120,000 (nghìn) hoặc 123,45 (thập phân)
            if len(parts[1]) == 3:
                int_part = "".join(parts)
            elif len(parts[1]) in (1, 2):
                int_part = parts[0]
                dec_part = parts[1]
            else:
                warns.append(WarningItem(
                    code="SO_TIEN_MO_HO",
                    message=f"Số tiền tại trang {page + 1} mơ hồ cấu trúc dấu phẩy: “{raw}”. Vui lòng xem ảnh gốc.",
                    level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
                return None, warns
    elif "." in s:
        groups = s.split(".")
        if not all(g.isdigit() for g in groups):
            warns.append(WarningItem(
                code="SO_TIEN_MO_HO",
                message=f"Số tiền tại trang {page + 1} lẫn ký tự không rõ: “{raw}”.",
                level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
            return None, warns
        if len(groups) > 2:
            # Dạng 410.000.000.000 (nhiều dấu chấm ngăn nghìn)
            if not all(len(g) == 3 for g in groups[1:]):
                warns.append(WarningItem(
                    code="SO_TIEN_MO_HO",
                    message=f"Số tiền tại trang {page + 1} mơ hồ dấu chấm: “{raw}”. Vui lòng xem ảnh gốc.",
                    level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
                return None, warns
            int_part = "".join(groups)
        else:
            # len == 2, ví dụ: 120.000 (nghìn)
            if len(groups[1]) == 3:
                int_part = "".join(groups)
            else:
                # 12.34 hoặc 1.234.56 là mơ hồ tại Việt Nam
                warns.append(WarningItem(
                    code="SO_TIEN_MO_HO",
                    message=f"Số tiền tại trang {page + 1} mơ hồ dấu chấm/phẩy: “{raw}”. Vui lòng xem ảnh gốc.",
                    level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
                return None, warns
    else:
        if not s.isdigit():
            warns.append(WarningItem(
                code="SO_TIEN_CO_CHU",
                message=f"Số tiền tại trang {page + 1} lẫn chữ cái: “{raw}”. Vui lòng đối chiếu với ảnh PDF.",
                level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
            return None, warns
        int_part = s

    try:
        val = Decimal(int_part + ("." + dec_part if dec_part else ""))
    except InvalidOperation:
        warns.append(WarningItem(
            code="SO_TIEN_SAI_DINH_DANG",
            message=f"Số tiền tại trang {page + 1} không đọc được: “{raw}”.",
            level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
        return None, warns
    if neg:
        val = -val
    return val, warns


def parse_account(raw: str, col: Col, page: int, row: int):
    warns = []
    s = norm_text(raw).replace(" ", "").strip(".")
    if not s:
        return None, warns
    if not s.isdigit():
        suspect = [ch for ch in s if ch in CONFUSE]
        if suspect and all(ch.isdigit() or ch in CONFUSE for ch in s):
            warns.append(WarningItem(
                code="TK_NHI_DOAN",
                message=f"Tài khoản tại trang {page + 1} có ký tự dễ nhầm ({', '.join(suspect)}): “{s}”. Vui lòng đối chiếu với ảnh PDF.",
                level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
        else:
            warns.append(WarningItem(
                code="TK_SAI_KY_TU",
                message=f"Tài khoản tại trang {page + 1} chứa ký tự không phù hợp: “{s}”.",
                level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
        return s, warns
    return s, warns


def parse_voucher(raw: str, col: Col, page: int, row: int):
    warns = []
    # Ghép các dòng nếu số chứng từ bị xuống dòng do cột hẹp
    s = "".join(raw.split())
    # Bỏ các ký tự rác mép ô do đường kẻ viền bảng
    s = s.strip(" .|;:_,-~`'\"_")
    if not s:
        return None, warns

    # Chuẩn hóa các lỗi OCR tiền tố do dính nét kẻ bảng hoặc font chữ
    s = re.sub(r"1[sS]\.", r"15.", s)
    s = re.sub(r"^NVE(\d)", r"NVK\1", s)
    s = re.sub(r"^UNGCI?([5-9]\.)", r"UNC1\1", s)
    s = re.sub(r"^UNC[I|]([5-9]\.)", r"UNC1\1", s)
    s = re.sub(r"^([A-Z]+)[I|](\d)", r"\1\2", s)
    s = re.sub(r"^I([A-Z]{2,4}\d)", r"\1", s)
    s = re.sub(r"[-_][I|]/$", "1", s)
    s = re.sub(r"[-_][I|]$", "1", s)
    s = re.sub(r"[-_]1/$", "1", s)
    s = re.sub(r"[I|]/$", "1", s)
    s = re.sub(r"\.(\d+)\.(\d+)$", r".\1\2", s)
    s = s.rstrip(".")

    if any(ch in CONFUSE for ch in s) and re.search(r"[A-Za-z]", s):
        pass  # số chứng từ vốn chứa chữ, không cảnh báo nhầm
    if re.search(r"[^\w./\-]", s):
        warns.append(WarningItem(
            code="SO_CT_KY_TU_LA",
            message=f"Số chứng từ tại trang {page + 1} có ký tự lạ: “{s}”. Vui lòng đối chiếu với ảnh PDF.",
            level=WarningLevel.EXTRACTION, page_index=page, row_index=row, col=col))
    return s, warns


def normalize_cell(col: Col, raw: str, page: int, row: int):
    if col in (Col.NGAY_HT, Col.NGAY_CT):
        return parse_date(raw, col, page, row)
    if col in (Col.PS_NO, Col.PS_CO):
        return parse_amount(raw, col, page, row)
    if col in (Col.TAI_KHOAN, Col.TK_DOI_UNG):
        return parse_account(raw, col, page, row)
    if col == Col.SO_CT:
        return parse_voucher(raw, col, page, row)
    if col == Col.DIEN_GIAI:
        # Làm sạch tàn dư đường kẻ dọc mép ô dính vào dòng chữ
        cleaned_lines = []
        for line in raw.split("\n"):
            ln = line.strip().strip("|").strip()
            # Bỏ ký tự pipe/I dính ở đầu từ hoa đầu dòng (INhận -> Nhận, IS\n -> "")
            ln = re.sub(r"^[|I1](?=[A-ZÀ-Ỹ])", "", ln).strip()
            if ln:
                cleaned_lines.append(ln)
        return "\n".join(cleaned_lines), []
    return raw.strip(), []
