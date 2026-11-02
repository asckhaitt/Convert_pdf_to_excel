"""Trích xuất một trang PDF thành các dòng nguồn có tọa độ và cảnh báo."""
from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
import pymupdf

from .classify import EXCLUDE_REASON, classify_row
from .model import (Col, COLUMN_ORDER, COLUMN_TITLES, CellValue, PageResult, Rect,
                    RowKind, SourceRow, WarningItem, WarningLevel)
from .normalize import normalize_cell
from .ocr_engine import (OcrEngine, clean_borders, has_ink, ink_mask, split_lines)
from .table_detect import detect_grid

PRINTED_PAGE_RE = re.compile(r"(\d{1,4})\s*[/\\|lI]\s*(\d{1,4})")


def render_page(pdf_path: str, page_index: int, dpi: int = 300) -> np.ndarray:
    doc = pymupdf.open(pdf_path)
    try:
        page = doc[page_index]
        pix = page.get_pixmap(dpi=dpi)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        elif pix.n == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        return img
    finally:
        doc.close()


def page_has_text_layer(pdf_path: str, page_index: int, min_words: int = 40) -> bool:
    doc = pymupdf.open(pdf_path)
    try:
        return len(doc[page_index].get_text("words")) >= min_words
    finally:
        doc.close()


def extract_page(pdf_path: str, page_index: int, engine: OcrEngine,
                 image_out: str | None = None, dpi: int = 300,
                 fallback_xs: list | None = None,
                 doc_total_pages: int | None = None) -> PageResult:
    img = render_page(pdf_path, page_index, dpi)
    pr = PageResult(page_index=page_index)
    if image_out:
        Path(image_out).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(image_out, img)
        pr.image_path = image_out

    grid = detect_grid(img, fallback_xs=fallback_xs)
    pr.grid_xs = list(grid.xs)
    if grid.n_cols != 8 or grid.n_rows < 2:
        pr.info_page = True
        pr.printed_page = _read_printed_page(img, grid, engine, doc_total_pages=doc_total_pages)
        pr.warnings.append(WarningItem(
            code="TRANG_KHONG_CO_BANG",
            message=f"Trang {page_index + 1}: không có bảng số liệu (trang ký, ghi chú hoặc trang lót). Trang này không đưa vào sheet nghiệp vụ; hãy xem ảnh và xác nhận.",
            level=WarningLevel.INFO, page_index=page_index))
        return pr

    # gom mọi dòng chữ của trang, OCR theo nhóm loại ô (một lần cho mỗi nhóm)
    mode_for = {Col.NGAY_HT: "date", Col.NGAY_CT: "date", Col.SO_CT: "code",
                Col.TAI_KHOAN: "account", Col.TK_DOI_UNG: "account",
                Col.PS_NO: "money", Col.PS_CO: "money", Col.DIEN_GIAI: "text"}
    cell_lines = {}
    by_mode = {}
    acct_cells = {}
    for r in range(grid.n_rows):
        for c in range(grid.n_cols):
            rect = grid.cell_rect(r, c)
            col_type = COLUMN_ORDER[c]
            # Cột số tiền căn phải: không lấn sang biên trái kẻ bảng tránh dính nét viền thành số 1
            if col_type in (Col.PS_NO, Col.PS_CO):
                x0 = max(0, int(rect.x0) + 1)
                x1 = min(img.shape[1], int(rect.x1))
            elif col_type in (Col.TAI_KHOAN, Col.TK_DOI_UNG):
                # Cột tài khoản: giữ đúng biên ô, tránh dính viền thành số 1 (1335 vs 335, 1911 vs 911)
                x0 = max(0, int(rect.x0))
                x1 = min(img.shape[1], int(rect.x1))
            else:
                x0 = max(0, int(rect.x0))
                x1 = min(img.shape[1], int(rect.x1) + 2)
            cell = img[int(rect.y0):int(rect.y1), x0:x1]
            if COLUMN_ORDER[c] in (Col.TAI_KHOAN, Col.TK_DOI_UNG):
                acct_cells[(r, c)] = cell
            if not has_ink(cell):
                cell_lines[(r, c)] = []
                continue
            col_type = COLUMN_ORDER[c]
            if col_type == Col.DIEN_GIAI:
                # Ô diễn giải: xử lý nguyên ô sạch viền, chừa lề 4px để không dính nét kẻ bảng dọc
                h0, w0 = cell.shape[:2]
                x_inset = min(4, max(0, (w0 - 10) // 2))
                cell_clean = clean_borders(cell[2:h0 - 2, x_inset:w0 - x_inset])
                lines = [cell_clean]
            else:
                lines = split_lines(cell)
            cell_lines[(r, c)] = lines
            by_mode.setdefault(mode_for[COLUMN_ORDER[c]], []).append(((r, c), lines))
    texts = {}
    for mode, groups in by_mode.items():
        flat = [im for _, lines in groups for im in lines]
        res = engine.recognize(flat, mode=mode)
        k = 0
        for key, lines in groups:
            texts[key] = res[k:k + len(lines)]
            k += len(lines)

    def cell_text(r, c):
        return "\n".join(t for t, _ in texts.get((r, c), []) if t)

    def left_label(r):
        """Nhãn “Tổng cộng” có thể in tràn sang các cột trái của ô diễn giải."""
        cell = img[int(grid.ys[r]):int(grid.ys[r + 1]),
                   int(grid.xs[0]):min(img.shape[1], int(grid.xs[4]) + 6)]
        if not has_ink(cell):
            return ""
        h0, w0 = cell.shape[:2]
        cell_clean = clean_borders(cell[2:h0 - 2, 2:w0 - 2])
        return "\n".join(t for t, _ in engine.recognize([cell_clean], mode="text") if t)

    def cell_conf(r, c):
        vals = [s for _, s in texts.get((r, c), []) if s]
        return min(vals) if vals else None

    # cột tài khoản đọc thêm một lần bằng cấu hình khác; hai lần khác nhau
    # nghĩa là chưa chắc chắn -> nêu cảnh báo để người soát đối chiếu ảnh
    alt_account = {}
    if acct_cells:
        keys = list(acct_cells)
        imgs = []
        for k in keys:
            c0 = acct_cells[k]
            imgs.append(clean_borders(c0))
        res = engine.recognize(imgs, mode="account_alt")
        alt_account = {k: (t or "") for k, (t, _) in zip(keys, res)}

    def pick_account(r, ci, col, base):
        b = "".join(base.split())
        a = "".join(alt_account.get((r, ci), "").split())
        ok_b = b.isdigit() and 2 <= len(b) <= 6
        ok_a = a.isdigit() and 2 <= len(a) <= 6
        if b == a or (not b and not a):
            return base
        if not b and ok_a:
            return a
        if not a and ok_b:
            return base
        if not ok_a and not ok_b:
            return base
        # Ưu tiên tài khoản chuẩn >= 3 chữ số thay vì mã bị xén mất chữ số đầu còn 2 chữ số (15 vs 515)
        if ok_a and ok_b:
            if len(a) >= 3 and len(b) == 2:
                return a
            if len(b) >= 3 and len(a) == 2:
                return base
        chosen = base if (b and (ok_b or not ok_a)) else a
        pr.warnings.append(WarningItem(
            code="TAI_KHOAN_CHUA_RO",
            message=(f"Trang {page_index + 1}, dòng {r + 1}, cột {COLUMN_TITLES[col]}: "
                     f"OCR đọc hai dạng “{b or 'trống'}” và “{a or 'trống'}”. "
                     f"Vui lòng đối chiếu ảnh PDF và chọn mã đúng."),
            level=WarningLevel.EXTRACTION, page_index=page_index, row_index=r, col=col))
        return chosen

    rows = []
    for r in range(grid.n_rows):
        raw_map = {col: cell_text(r, ci) for ci, col in enumerate(COLUMN_ORDER)}
        for ci, col in enumerate(COLUMN_ORDER):
            if col in (Col.TAI_KHOAN, Col.TK_DOI_UNG):
                raw_map[col] = pick_account(r, ci, col, raw_map[col])
        left_empty = not any(raw_map[c].strip() for c in
                             (Col.NGAY_HT, Col.NGAY_CT, Col.SO_CT, Col.DIEN_GIAI))
        has_money = raw_map[Col.PS_NO].strip() or raw_map[Col.PS_CO].strip()
        no_account = not raw_map[Col.TAI_KHOAN].strip() and not raw_map[Col.TK_DOI_UNG].strip()
        if has_money and (left_empty or no_account):
            lbl = left_label(r)
            if lbl:
                from .classify import fold, is_total_label
                flbl = fold(lbl)
                if is_total_label(lbl) or "chuyen sang trang sau" in flbl or "trang truoc chuyen sang" in flbl:
                    raw_map[Col.DIEN_GIAI] = lbl
                    raw_map[Col.NGAY_HT] = ""
                    raw_map[Col.NGAY_CT] = ""
                    raw_map[Col.SO_CT] = ""
                    raw_map[Col.TAI_KHOAN] = ""
                    raw_map[Col.TK_DOI_UNG] = ""
                elif left_empty:
                    raw_map[Col.DIEN_GIAI] = lbl
                    raw_map["__left_label__"] = True
        kind = classify_row(raw_map)
        rect = Rect(grid.xs[0], grid.ys[r], grid.xs[-1], grid.ys[r + 1])
        row = SourceRow(page_index=page_index, row_index=r, kind=kind, rect=rect)
        for ci, col in enumerate(COLUMN_ORDER):
            cv_ = CellValue(col=col, raw=raw_map[col], rect=grid.cell_rect(r, ci),
                            confidence=cell_conf(r, ci), source="ocr")
            if kind in (RowKind.ENTRY, RowKind.UNKNOWN, RowKind.CARRY_IN,
                        RowKind.CARRY_OUT, RowKind.GRAND_TOTAL):
                value, warns = normalize_cell(col, raw_map[col], page_index, r)
                cv_.value = value
                cv_.warnings = warns
                pr.warnings.extend(warns)
            row.cells[col] = cv_
        if kind == RowKind.ENTRY:
            for col in (Col.TAI_KHOAN, Col.TK_DOI_UNG):
                if not row.cell(col).raw.strip():
                    pr.warnings.append(WarningItem(
                        code="THIEU_TAI_KHOAN",
                        message=(f"Trang {page_index + 1}, dòng {r + 1}: không đọc được mã "
                                 f"cột {COLUMN_TITLES[col]}. Vui lòng đối chiếu ảnh PDF."),
                        level=WarningLevel.EXTRACTION, page_index=page_index,
                        row_index=r, col=col))
        if kind in EXCLUDE_REASON:
            row.excluded_reason = EXCLUDE_REASON[kind]
        rows.append(row)

    # ghép dòng chỉ-có-diễn-giải vào ô diễn giải của dòng liền trước
    merged_rows = []
    for row in rows:
        if (row.kind == RowKind.UNKNOWN and merged_rows
                and merged_rows[-1].kind == RowKind.ENTRY
                and not row.cell(Col.PS_NO).raw and not row.cell(Col.PS_CO).raw
                and not row.cell(Col.TAI_KHOAN).raw and not row.cell(Col.NGAY_HT).raw
                and not row.cell(Col.SO_CT).raw
                and row.cell(Col.DIEN_GIAI).raw):
            prev = merged_rows[-1]
            pc = prev.cell(Col.DIEN_GIAI)
            pc.raw = (pc.raw + "\n" + row.cell(Col.DIEN_GIAI).raw).strip()
            pc.value = pc.raw
            prev.merged_from.append(row.row_index)
            prev.warnings.append(WarningItem(
                code="GOP_DONG_DIEN_GIAI",
                message=f"Trang {page_index + 1}: đã ghép dòng chữ nối vào diễn giải dòng {prev.row_index + 1}. Vui lòng xác nhận khi đối soát.",
                level=WarningLevel.INFO, page_index=page_index, row_index=prev.row_index))
            continue
        if row.kind == RowKind.UNKNOWN:
            pr.warnings.append(WarningItem(
                code="DONG_CHUA_RO",
                message=f"Trang {page_index + 1}, dòng {row.row_index + 1}: chưa phân loại được. Vui lòng đối chiếu với ảnh PDF.",
                level=WarningLevel.EXTRACTION, page_index=page_index, row_index=row.row_index))
        merged_rows.append(row)
    pr.rows = merged_rows

    for row in merged_rows:
        if row.kind == RowKind.CARRY_IN:
            pr.has_carry_in_row = True
            pr.carry_in_no = row.amount_no
            pr.carry_in_co = row.amount_co
        elif row.kind == RowKind.CARRY_OUT:
            pr.has_carry_out_row = True
            pr.carry_out_no = row.amount_no
            pr.carry_out_co = row.amount_co
        elif row.kind == RowKind.GRAND_TOTAL:
            pr.has_grand_total_row = True
            pr.grand_total_no = row.amount_no
            pr.grand_total_co = row.amount_co

    _read_footer_totals(img, grid, engine, pr, page_index)
    pr.printed_page = _read_printed_page(img, grid, engine, doc_total_pages=doc_total_pages)
    if pr.printed_page is None:
        pr.warnings.append(WarningItem(
            code="CHUA_DOC_SO_TRANG_IN",
            message=f"Trang {page_index + 1}: chưa đọc được số trang in ở chân trang. Vui lòng nhìn ảnh PDF và nhập số trang in khi đối soát.",
            level=WarningLevel.INFO, page_index=page_index))
    return pr


def _read_footer_totals(img, grid, engine, pr: PageResult, page_index: int):
    """Dòng chuyển trang / tổng cộng có thể nằm NGOÀI khung bảng (chân trang)."""
    from .classify import fold
    h, w = img.shape[:2]
    y0 = int(grid.table.y1) + 2
    y1 = min(h, y0 + max(160, int(h * 0.06)))
    if y1 - y0 < 20:
        return
    xs = grid.xs
    # bám theo dải chữ của nhãn để cắt ô số tiền đúng dòng, không cắt mất chữ số cuối
    dg_region = img[y0:y1, int(xs[3]):int(xs[4])]
    bw = ink_mask(dg_region)
    prof = bw.sum(axis=1) / 255.0
    ys = np.nonzero(prof > max(1.0, dg_region.shape[1] * 0.01))[0]
    if len(ys) == 0:
        return
    a = max(0, int(ys[0]) - 6)
    b = min(dg_region.shape[0], int(ys[-1]) + 7)
    regions = {
        Col.DIEN_GIAI: (int(xs[3]), int(xs[4])),
        Col.PS_NO: (int(xs[6]), int(xs[7])),
        Col.PS_CO: (int(xs[7]), min(w, int(xs[8]) + 6)),
    }
    crops, keys, modes = [], [], []
    for col, (ca, cb) in regions.items():
        crop = img[y0 + a:y0 + b, ca:cb]
        if has_ink(crop, inset=2):
            crops.append(crop)
            keys.append(col)
            modes.append("text" if col == Col.DIEN_GIAI else "money")
    if not crops:
        return
    got = {}
    for mode in ("text", "money"):
        idx = [i for i, m in enumerate(modes) if m == mode]
        if not idx:
            continue
        res = engine.recognize([crops[i] for i in idx], mode=mode)
        for i, (t, _) in zip(idx, res):
            got[keys[i]] = t
    label = fold(got.get(Col.DIEN_GIAI, ""))
    if "chuyen sang trang sau" in label:
        kind = RowKind.CARRY_OUT
    elif label.startswith("tong cong"):
        kind = RowKind.GRAND_TOTAL
    else:
        return
    if kind == RowKind.CARRY_OUT and pr.has_carry_out_row:
        return
    if kind == RowKind.GRAND_TOTAL and pr.has_grand_total_row:
        return
    row = SourceRow(page_index=page_index, row_index=len(pr.rows), kind=kind,
                    rect=Rect(xs[0], y0 + a, xs[-1], y0 + b),
                    excluded_reason=EXCLUDE_REASON[kind])
    for col in COLUMN_ORDER:
        raw = got.get(col, "")
        cv_ = CellValue(col=col, raw=raw, source="ocr",
                        rect=Rect(regions[col][0], y0 + a, regions[col][1], y0 + b) if col in regions else None)
        value, warns = normalize_cell(col, raw, page_index, row.row_index)
        cv_.value = value
        cv_.warnings = warns
        pr.warnings.extend(warns)
        row.cells[col] = cv_
    pr.rows.append(row)
    if kind == RowKind.CARRY_OUT:
        pr.has_carry_out_row = True
        pr.carry_out_no = row.amount_no
        pr.carry_out_co = row.amount_co
    else:
        pr.has_grand_total_row = True
        pr.grand_total_no = row.amount_no
        pr.grand_total_co = row.amount_co


def _read_printed_page(img: np.ndarray, grid, engine: OcrEngine, doc_total_pages: int | None = None):
    """Số trang in ở góc phải chân trang (dạng 12/36); chỉ lấy số trang hiện tại."""
    h, w = img.shape[:2]
    if grid and getattr(grid, "table", None) and getattr(grid.table, "y1", 0) > 0:
        y0 = int(grid.table.y1) + 2
    else:
        y0 = h - max(160, int(h * 0.05))

    strip = img[y0:h, int(w * 0.65):w]
    lines = split_lines(strip, inset=2)
    if not lines:
        strip = img[max(0, h - max(120, int(h * 0.04))):h, int(w * 0.7):w]
        lines = split_lines(strip, inset=1)
    if not lines and has_ink(strip):
        lines = [strip]
    if not lines:
        return None

    padded = [cv2.copyMakeBorder(im, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)
              for im in lines]
    res = engine.recognize(padded, mode="code")
    # Duyệt từ dòng thấp nhất lên (chân trang nằm ở dòng cuối cùng)
    for text, _ in reversed(res):
        cleaned = text.strip().replace(" ", "")
        m = PRINTED_PAGE_RE.search(cleaned)
        if m:
            cur, tot = int(m.group(1)), int(m.group(2))
            if 1 <= cur <= tot:
                if doc_total_pages is None or abs(tot - doc_total_pages) <= 2:
                    return cur
                if 1 <= cur <= 500:
                    return cur
        # Trường hợp OCR đọc nhầm dấu / thành chữ số 1 hoặc ký tự khác
        if doc_total_pages:
            tot_str = str(doc_total_pages)
            if cleaned.endswith(tot_str) and len(cleaned) > len(tot_str):
                cur_str = cleaned[:-len(tot_str)].rstrip("/|lI1\\")
                if cur_str.isdigit():
                    cur = int(cur_str)
                    if 1 <= cur <= doc_total_pages:
                        return cur
    return None
