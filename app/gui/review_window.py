"""Màn hình đối soát: ảnh PDF bên trái, lưới 8 cột bên phải, thông tin kế toán phía dưới."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from ..core import storage
from ..core.classify import EXCLUDE_REASON
from ..core.excel_export import export_workbook, verify_workbook
from ..core.model import (Col, COLUMN_ORDER, COLUMN_TITLES, FileStatus,
                          RowKind, SourceRow, WarningLevel)
from ..core.normalize import normalize_cell
from ..core.ocr_engine import ink_mask
from ..core.reconcile import (can_export_final, reconcile_file,
                              refresh_page_totals, voucher_key)
from .image_view import ImageView, ndarray_to_qimage

KIND_LABEL = {
    RowKind.ENTRY: "Bút toán",
    RowKind.CARRY_IN: "Số trang trước chuyển sang",
    RowKind.CARRY_OUT: "Cộng chuyển sang trang sau",
    RowKind.GRAND_TOTAL: "Tổng cộng",
    RowKind.HEADER: "Tiêu đề cột",
    RowKind.INFO: "Thông tin loại khỏi Excel",
    RowKind.EMPTY: "Dòng trống",
    RowKind.UNKNOWN: "Chưa rõ",
}
LEVEL_LABEL = {
    WarningLevel.EXTRACTION: "Cần đối chiếu",
    WarningLevel.ACCOUNTING: "Kiểm tra kế toán",
    WarningLevel.INFO: "Thông tin",
}
FILTERS = ["Tất cả các dòng", "Ô nghi ngờ", "Sai công thức chuyển trang",
           "Chứng từ không cân", "Sai lệch đã xác nhận do PDF gốc",
           "Dòng chưa xác nhận", "Dòng bị loại khỏi Excel"]


def fmt_amount(v) -> str:
    if v is None:
        return ""
    s = format(v, "f")
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    ip, _, dp = s.partition(".")
    ip = f"{int(ip or 0):,}".replace(",", ".")
    return ("-" if neg else "") + ip + ("," + dp if dp else "")


def display_text(col: Col, cv) -> str:
    v = cv.value
    if col in (Col.NGAY_HT, Col.NGAY_CT):
        return v.strftime("%d/%m/%Y") if isinstance(v, date) else cv.raw
    if col in (Col.PS_NO, Col.PS_CO):
        return fmt_amount(v) if isinstance(v, Decimal) else cv.raw
    return cv.raw


class ReviewWindow(QWidget):
    saved = Signal(object)
    closed = Signal(str, int)

    def __init__(self, fr, con, out_dir: str, parent=None):
        super().__init__(parent, Qt.Window)
        self.fr = fr
        self.con = con
        self.out_dir = out_dir
        self.page_idx = 0
        self._rows = []
        self._loading = False
        self._warn_cursor = -1
        self._review_secs = 0
        self._processed_cache = {}
        self.dirty = False
        self.setWindowTitle(f"Đối chiếu – {Path(fr.path).name}")
        self.resize(1500, 900)
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self.load_page(0)
        self.refresh_warnings()

    # ---------------- giao diện ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.btn_prev_page = QPushButton("Trang trước")
        self.btn_next_page = QPushButton("Trang sau")
        self.page_label = QLabel()
        self.spin_printed = QSpinBox()
        self.spin_printed.setRange(0, 9999)
        self.spin_printed.setToolTip("Số trang in trên giấy (0 nếu trang không in số). Sửa khi phần mềm chưa đọc được.")
        self.btn_zoom_in = QPushButton("Phóng to")
        self.btn_zoom_out = QPushButton("Thu nhỏ")
        self.btn_fit = QPushButton("Vừa khung")
        self.chk_processed = QCheckBox("Ảnh đã xử lý")
        for w in (self.btn_prev_page, self.btn_next_page, self.page_label,
                  QLabel("Số trang in:"), self.spin_printed, self.btn_zoom_in,
                  self.btn_zoom_out, self.btn_fit, self.chk_processed):
            bar.addWidget(w)
        bar.addStretch(1)
        self.clock_label = QLabel("Thời gian đối chiếu: 00:00:00")
        bar.addWidget(self.clock_label)
        root.addLayout(bar)

        self.view = ImageView()
        right = QWidget()
        rv = QVBoxLayout(right)
        fbar = QHBoxLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(FILTERS)
        self.btn_prev_warn = QPushButton("Cảnh báo trước")
        self.btn_next_warn = QPushButton("Cảnh báo tiếp theo")
        fbar.addWidget(QLabel("Lọc:"))
        fbar.addWidget(self.filter_combo, 1)
        fbar.addWidget(self.btn_prev_warn)
        fbar.addWidget(self.btn_next_warn)
        rv.addLayout(fbar)
        self.grid = QTableWidget(0, 8)
        self.grid.setHorizontalHeaderLabels([COLUMN_TITLES[c] for c in COLUMN_ORDER])
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.grid.horizontalHeader().setStretchLastSection(True)
        self.grid.setColumnWidth(3, 320)
        self.grid.verticalHeader().setVisible(False)
        self.grid.setWordWrap(True)
        rv.addWidget(self.grid, 1)
        rv.addLayout(self._build_actions())
        top_split = QSplitter(Qt.Horizontal)
        top_split.addWidget(self.view)
        top_split.addWidget(right)
        top_split.setSizes([700, 800])

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_page_tab(), "Đối soát trang")
        self.tabs.addTab(self._build_warn_tab(), "Cảnh báo cần xử lý")
        main_split = QSplitter(Qt.Vertical)
        main_split.addWidget(top_split)
        main_split.addWidget(self.tabs)
        main_split.setSizes([620, 260])
        root.addWidget(main_split, 1)

        self.btn_prev_page.clicked.connect(lambda: self.load_page(self.page_idx - 1))
        self.btn_next_page.clicked.connect(lambda: self.load_page(self.page_idx + 1))
        self.btn_zoom_in.clicked.connect(self.view.zoom_in)
        self.btn_zoom_out.clicked.connect(self.view.zoom_out)
        self.btn_fit.clicked.connect(self.view.fit)
        self.chk_processed.toggled.connect(self._reload_image)
        self.spin_printed.valueChanged.connect(self._printed_changed)
        self.filter_combo.currentIndexChanged.connect(lambda _: self.populate_grid())
        self.btn_prev_warn.clicked.connect(lambda: self.jump_warning(-1))
        self.btn_next_warn.clicked.connect(lambda: self.jump_warning(1))
        self.grid.currentItemChanged.connect(self._selection_changed)
        self.grid.cellChanged.connect(self._cell_changed)

    def _build_actions(self):
        box = QVBoxLayout()
        r1 = QHBoxLayout()
        self.btn_add = QPushButton("Thêm dòng bị sót")
        self.btn_del = QPushButton("Xóa dòng trùng")
        self.btn_split = QPushButton("Tách diễn giải")
        self.btn_merge = QPushButton("Gộp diễn giải")
        self.kind_combo = QComboBox()
        for k in RowKind:
            self.kind_combo.addItem(KIND_LABEL[k], k)
        self.btn_confirm_row = QPushButton("Xác nhận dòng")
        self.btn_confirm_page = QPushButton("Xác nhận trang")
        self.btn_confirm_next = QPushButton("Xác nhận & Sang trang sau (Ctrl+Enter)")
        self.btn_confirm_next.setStyleSheet("font-weight: bold; background-color: #E8F5E9; color: #1B5E20;")
        for w in (self.btn_add, self.btn_del, self.btn_split, self.btn_merge,
                  QLabel("Loại dòng:"), self.kind_combo,
                  self.btn_confirm_row, self.btn_confirm_page, self.btn_confirm_next):
            r1.addWidget(w)
        box.addLayout(r1)
        r2 = QHBoxLayout()
        self.btn_source = QPushButton("Xác nhận sai lệch trên PDF gốc")
        self.btn_save = QPushButton("Lưu đối soát")
        self.btn_draft = QPushButton("Xuất Excel nháp")
        self.btn_final = QPushButton("Xuất Excel đã đối chiếu")
        self.state_label = QLabel("")
        for w in (self.btn_source, self.btn_save, self.btn_draft, self.btn_final):
            r2.addWidget(w)
        r2.addWidget(self.state_label, 1)
        box.addLayout(r2)
        self.btn_add.clicked.connect(self.add_row)
        self.btn_del.clicked.connect(self.delete_row)
        self.btn_split.clicked.connect(self.split_description)
        self.btn_merge.clicked.connect(self.merge_description)
        self.kind_combo.activated.connect(self.reclassify)
        self.btn_confirm_row.clicked.connect(self.confirm_row)
        self.btn_confirm_page.clicked.connect(self.confirm_page)
        self.btn_confirm_next.clicked.connect(self.confirm_and_next_page)
        self.btn_source.clicked.connect(self.confirm_source_warning)
        self.btn_save.clicked.connect(self.save)
        self.btn_draft.clicked.connect(lambda: self.export(False))
        self.btn_final.clicked.connect(lambda: self.export(True))
        return box

    def _build_page_tab(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        form = QGroupBox("Số liệu chuyển trang và cân đối")
        g = QGridLayout(form)
        self.lbl = {}
        names = ["carry_in", "sums", "carry_out", "grand", "diff", "voucher", "book"]
        titles = ["Số trang trước chuyển sang (Nợ / Có)",
                  "Tổng phát sinh trong trang (Nợ / Có)",
                  "Cộng chuyển sang trang sau (Nợ / Có)",
                  "Tổng cộng toàn sổ (Nợ / Có)",
                  "Chênh lệch cần xử lý",
                  "Tổng Nợ / Có chứng từ đang chọn",
                  "Tổng Nợ / Có toàn sổ"]
        for i, (k, t) in enumerate(zip(names, titles)):
            g.addWidget(QLabel(t + ":"), i, 0)
            self.lbl[k] = QLabel("–")
            self.lbl[k].setTextInteractionFlags(Qt.TextSelectableByMouse)
            g.addWidget(self.lbl[k], i, 1)
        lay.addWidget(form)
        self.rec_table = QTableWidget(0, 5)
        self.rec_table.setHorizontalHeaderLabels(
            ["Kiểm tra", "Số trên sổ", "Số tính lại", "Chênh lệch", "Kết quả"])
        self.rec_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.rec_table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.rec_table, 1)
        return w

    def _build_warn_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        # Thanh công cụ duyệt cảnh báo nhanh
        tbar = QHBoxLayout()
        self.warn_filter_combo = QComboBox()
        self.warn_filter_combo.addItems([
            "Tất cả cảnh báo",
            "Chỉ trang hiện tại",
            "Chỉ cảnh báo chưa xử lý",
            "Cảnh báo lệch số tiền (Kế toán)",
        ])
        self.warn_filter_combo.currentIndexChanged.connect(lambda _: self.refresh_warnings())
        self.btn_resolve_selected = QPushButton("✓ Xác nhận đã chọn (Space)")
        self.btn_resolve_page = QPushButton("✓ Xác nhận tất cả cảnh báo trang này")
        self.btn_resolve_balanced = QPushButton("⚡ Tự động duyệt cảnh báo đã cân đối")
        self.btn_resolve_selected.setToolTip("Xác nhận cảnh báo đang chọn là sai lệch nguồn / đã kiểm tra (Phím tắt: Space)")
        self.btn_resolve_page.setToolTip("Xác nhận toàn bộ cảnh báo của trang hiện tại sau khi đã kiểm tra")
        self.btn_resolve_balanced.setToolTip("Tự động duyệt mọi cảnh báo về số chứng từ hoặc thông tin mà số tiền đã cân đối")

        tbar.addWidget(QLabel("Lọc cảnh báo:"))
        tbar.addWidget(self.warn_filter_combo)
        tbar.addWidget(self.btn_resolve_selected)
        tbar.addWidget(self.btn_resolve_page)
        tbar.addWidget(self.btn_resolve_balanced)
        tbar.addStretch(1)
        lay.addLayout(tbar)

        self.warn_table = QTableWidget(0, 5)
        self.warn_table.setHorizontalHeaderLabels(
            ["Trang", "Dòng", "Nội dung", "Mức độ", "Trạng thái"])
        self.warn_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.warn_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.warn_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.warn_table.itemSelectionChanged.connect(self._warn_selected)
        self.warn_table.keyPressEvent = self._warn_key_press
        lay.addWidget(self.warn_table)

        self.btn_resolve_selected.clicked.connect(self.confirm_source_warning)
        self.btn_resolve_page.clicked.connect(self.resolve_page_warnings)
        self.btn_resolve_balanced.clicked.connect(self.resolve_balanced_warnings)
        return w

    # ---------------- nạp trang ----------------
    def load_page(self, idx: int):
        if not self.fr.pages:
            return
        idx = max(0, min(idx, len(self.fr.pages) - 1))
        self.page_idx = idx
        p = self.fr.pages[idx]
        self.page_label.setText(
            f"Trang {idx + 1}/{len(self.fr.pages)} của tệp"
            + (f" (in số {p.printed_page})" if p.printed_page else " (chưa đọc được số in)")
            + (" – đã xác nhận" if p.confirmed else ""))
        self._loading = True
        self.spin_printed.setValue(p.printed_page or 0)
        self._loading = False
        self._reload_image()
        self.populate_grid()
        self.refresh_bottom()

    def _reload_image(self):
        p = self.fr.pages[self.page_idx]
        if not p.image_path or not Path(p.image_path).exists():
            return
        if self.chk_processed.isChecked():
            if self.page_idx not in self._processed_cache:
                img = cv2.imread(p.image_path)
                self._processed_cache[self.page_idx] = ndarray_to_qimage(ink_mask(img))
            self.view.set_image(self._processed_cache[self.page_idx])
        else:
            img = cv2.imread(p.image_path)
            self.view.set_image(ndarray_to_qimage(img))

    def _filter_rows(self):
        p = self.fr.pages[self.page_idx]
        f = self.filter_combo.currentIndex()
        rows = p.rows
        if f == 1:
            rows = [r for r in rows if any(cv.warnings for cv in r.cells.values())]
        elif f == 2:
            bad = any(w.code == "CONG_THUC_LECH" and not w.resolved
                      and w.page_index == self.page_idx for w in self.fr.warnings)
            rows = [r for r in rows if r.kind in (RowKind.CARRY_IN, RowKind.CARRY_OUT,
                                                  RowKind.GRAND_TOTAL)] if bad else []
        elif f == 3:
            idxs = {w.row_index for w in self.fr.warnings
                    if w.code == "CHUNG_TU_KHONG_CAN" and not w.resolved
                    and w.page_index == self.page_idx}
            rows = [r for r in rows if r.row_index in idxs]
        elif f == 4:
            idxs = {w.row_index for w in self.fr.warnings
                    if w.resolved and w.page_index == self.page_idx
                    and w.level in (WarningLevel.ACCOUNTING, WarningLevel.EXTRACTION)}
            rows = [r for r in rows if r.row_index in idxs]
        elif f == 5:
            rows = [r for r in rows if not r.confirmed]
        elif f == 6:
            rows = [r for r in rows if r.kind in EXCLUDE_REASON or r.kind == RowKind.UNKNOWN]
        return rows

    def populate_grid(self):
        self._rows = self._filter_rows()
        self._loading = True
        self.grid.setRowCount(len(self._rows))
        for i, r in enumerate(self._rows):
            row_has_warn = any(w.row_index == r.row_index and w.page_index == self.page_idx and not w.resolved
                               for w in self.fr.warnings)
            for ci, col in enumerate(COLUMN_ORDER):
                cv = r.cell(col)
                item = QTableWidgetItem(display_text(col, cv))
                tip = KIND_LABEL[r.kind]
                if r.excluded_reason:
                    tip += " – " + r.excluded_reason
                if cv.warnings:
                    tip += "\n" + "\n".join(w.message for w in cv.warnings)
                item.setToolTip(tip)
                if r.kind in EXCLUDE_REASON:
                    item.setBackground(QColor(235, 235, 235))
                elif cv.warnings or row_has_warn:
                    item.setBackground(QColor(255, 240, 190))
                elif r.confirmed:
                    item.setBackground(QColor(225, 245, 225))
                self.grid.setItem(i, ci, item)
            self.grid.setRowHeight(i, 46)
        self._loading = False
        self.refresh_bottom()

    # ---------------- sửa dữ liệu ----------------
    def _current_row(self):
        i = self.grid.currentRow()
        return self._rows[i] if 0 <= i < len(self._rows) else None

    def _cell_changed(self, row: int, ci: int):
        if self._loading or row >= len(self._rows):
            return
        r = self._rows[row]
        col = COLUMN_ORDER[ci]
        text = self.grid.item(row, ci).text()
        cv = r.cell(col)
        if cv.raw == text:
            return
        old = cv.value
        value, warns = normalize_cell(col, text, self.page_idx, r.row_index)
        if not cv.edited:
            cv.original_value = old
        cv.raw, cv.value, cv.edited, cv.source = text, value, True, "nguoi_dung"
        cv.warnings = warns
        self.fr.warnings = [w for w in self.fr.warnings
                            if not (w.page_index == self.page_idx
                                    and w.row_index == r.row_index and w.col == col)]
        self.fr.warnings.extend(warns)
        self.fr.pages[self.page_idx].confirmed = False
        self.dirty = True
        storage.add_history(self.con, self.fr.path, "sua_o",
                            f"trang={self.page_idx + 1} dong={r.row_index + 1} "
                            f"cot={col.value} cu={old!r} moi={text!r}")
        self._after_edit()

    def _after_edit(self):
        for p in self.fr.pages:
            refresh_page_totals(p)
        reconcile_file(self.fr)
        self.refresh_bottom()
        self.refresh_warnings()
        self.state_label.setText("Có thay đổi chưa lưu – nhớ bấm Lưu đối soát.")

    def _renumber(self, page):
        mapping = {r.row_index: i for i, r in enumerate(page.rows)}
        for i, r in enumerate(page.rows):
            r.row_index = i
        for w in self.fr.warnings + page.warnings:
            if w.page_index == page.page_index and w.row_index in mapping:
                w.row_index = mapping[w.row_index]
        for r in page.rows:
            for w in r.warnings:
                if w.row_index in mapping:
                    w.row_index = mapping[w.row_index]

    def add_row(self):
        page = self.fr.pages[self.page_idx]
        r = self._current_row()
        pos = page.rows.index(r) + 1 if r else len(page.rows)
        new = SourceRow(page_index=self.page_idx,
                        row_index=max((x.row_index for x in page.rows), default=-1) + 1,
                        kind=RowKind.ENTRY)
        page.rows.insert(pos, new)
        self._renumber(page)
        page.confirmed = False
        self.dirty = True
        storage.add_history(self.con, self.fr.path, "them_dong",
                            f"trang={self.page_idx + 1} dong={new.row_index + 1}")
        self.populate_grid()
        self._after_edit()

    def delete_row(self):
        r = self._current_row()
        if not r:
            return
        page = self.fr.pages[self.page_idx]
        page.rows.remove(r)
        self.fr.warnings = [w for w in self.fr.warnings
                            if not (w.page_index == self.page_idx and w.row_index == r.row_index)]
        page.warnings = [w for w in page.warnings if w.row_index != r.row_index]
        self._renumber(page)
        page.confirmed = False
        self.dirty = True
        storage.add_history(self.con, self.fr.path, "xoa_dong",
                            f"trang={self.page_idx + 1} dong={r.row_index + 1}")
        self.populate_grid()
        self._after_edit()

    def split_description(self):
        r = self._current_row()
        if not r:
            return
        lines = r.cell(Col.DIEN_GIAI).raw.split("\n")
        if len(lines) < 2:
            QMessageBox.information(self, "Tách diễn giải",
                                    "Ô diễn giải đang chọn chỉ có một dòng, không cần tách.")
            return
        page = self.fr.pages[self.page_idx]
        cv = r.cell(Col.DIEN_GIAI)
        cv.raw = "\n".join(lines[:-1])
        cv.value = cv.raw
        new = SourceRow(page_index=self.page_idx,
                        row_index=max(x.row_index for x in page.rows) + 1,
                        kind=RowKind.ENTRY)
        ncv = new.cell(Col.DIEN_GIAI)
        ncv.raw = ncv.value = lines[-1]
        ncv.source = "nguoi_dung"
        page.rows.insert(page.rows.index(r) + 1, new)
        self._renumber(page)
        self.dirty = True
        storage.add_history(self.con, self.fr.path, "tach_dien_giai",
                            f"trang={self.page_idx + 1} dong={r.row_index + 1}")
        self.populate_grid()
        self._after_edit()

    def merge_description(self):
        r = self._current_row()
        page = self.fr.pages[self.page_idx]
        if not r or page.rows.index(r) == 0:
            return
        prev = page.rows[page.rows.index(r) - 1]
        pc = prev.cell(Col.DIEN_GIAI)
        part = r.cell(Col.DIEN_GIAI).raw
        if not part:
            return
        pc.raw = (pc.raw + "\n" + part).strip()
        pc.value = pc.raw
        rc = r.cell(Col.DIEN_GIAI)
        rc.raw = rc.value = ""
        if all(not c.raw.strip() for c in r.cells.values()):
            page.rows.remove(r)
            self._renumber(page)
        self.dirty = True
        storage.add_history(self.con, self.fr.path, "gop_dien_giai",
                            f"trang={self.page_idx + 1} dong={r.row_index + 1}")
        self.populate_grid()
        self._after_edit()

    def reclassify(self):
        r = self._current_row()
        if not r:
            return
        kind = self.kind_combo.currentData()
        r.kind = kind
        r.excluded_reason = EXCLUDE_REASON.get(kind, "")
        self.fr.pages[self.page_idx].confirmed = False
        self.dirty = True
        storage.add_history(self.con, self.fr.path, "doi_loai_dong",
                            f"trang={self.page_idx + 1} dong={r.row_index + 1} loai={kind.value}")
        self.populate_grid()
        self._after_edit()

    def confirm_row(self):
        r = self._current_row()
        if not r:
            return
        r.confirmed = True
        for cv in r.cells.values():
            cv.reviewed = True
        self.dirty = True
        storage.add_history(self.con, self.fr.path, "xac_nhan_dong",
                            f"trang={self.page_idx + 1} dong={r.row_index + 1}")
        self.populate_grid()

    def confirm_page(self):
        p = self.fr.pages[self.page_idx]
        p.confirmed = True
        # Tự động xác nhận các cảnh báo còn lại trên trang này vì kế toán viên đã xác nhận trang
        for w in self.fr.warnings:
            if w.page_index == self.page_idx and not w.resolved:
                w.resolved = True
                w.resolution = "Đã kiểm tra và xác nhận cùng trang."
        self.dirty = True
        storage.add_history(self.con, self.fr.path, "xac_nhan_trang",
                            f"trang={self.page_idx + 1}")
        self.load_page(self.page_idx)
        self.refresh_warnings()
        self.state_label.setText("Đã xác nhận trang – nhớ bấm Lưu đối soát.")

    def confirm_and_next_page(self):
        self.confirm_page()
        if self.page_idx + 1 < len(self.fr.pages):
            self.load_page(self.page_idx + 1)
        else:
            QMessageBox.information(self, "Hoàn tất", "Đã duyệt đến trang cuối cùng của sổ.")

    def resolve_page_warnings(self):
        cnt = 0
        for w in self.fr.warnings:
            if w.page_index == self.page_idx and not w.resolved:
                w.resolved = True
                w.resolution = "Xác nhận hàng loạt theo trang."
                cnt += 1
        if cnt > 0:
            self.dirty = True
            self._after_edit()
            self.state_label.setText(f"Đã xác nhận {cnt} cảnh báo của trang {self.page_idx + 1}.")
        else:
            self.state_label.setText(f"Trang {self.page_idx + 1} không có cảnh báo nào chưa xử lý.")

    def resolve_balanced_warnings(self):
        cnt = 0
        for w in self.fr.warnings:
            if not w.resolved:
                if w.code in ("SO_CT_KHONG_THONG_NHAT", "CHUA_DOC_SO_TRANG_IN", "SO_TRANG_IN_LECH", "TRANG_DAU_CO_CHUYEN_VAO"):
                    w.resolved = True
                    w.resolution = "Tự động duyệt cảnh báo không lệch số liệu."
                    cnt += 1
        if cnt > 0:
            self.dirty = True
            self._after_edit()
            QMessageBox.information(self, "Tự động duyệt", f"Đã giải quyết tự động {cnt} cảnh báo không ảnh hưởng số tiền.")
        else:
            QMessageBox.information(self, "Tự động duyệt", "Không có cảnh báo cân đối nào cần giải quyết.")

    def _warn_key_press(self, event):
        if event.key() == Qt.Key_Space:
            self.confirm_source_warning()
            event.accept()
            return
        QTableWidget.keyPressEvent(self.warn_table, event)

    def keyPressEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.confirm_and_next_page()
                event.accept()
                return
            elif event.key() == Qt.Key_Down:
                self.jump_warning(1)
                event.accept()
                return
            elif event.key() == Qt.Key_Up:
                self.jump_warning(-1)
                event.accept()
                return
            elif event.key() in (Qt.Key_PageDown, Qt.Key_Right):
                if self.page_idx + 1 < len(self.fr.pages):
                    self.load_page(self.page_idx + 1)
                event.accept()
                return
            elif event.key() in (Qt.Key_PageUp, Qt.Key_Left):
                if self.page_idx > 0:
                    self.load_page(self.page_idx - 1)
                event.accept()
                return
        super().keyPressEvent(event)

    def confirm_source_warning(self):
        i = self.warn_table.currentRow()
        disp = getattr(self, "_displayed_warnings", [])
        if i < 0 or i >= len(disp):
            QMessageBox.information(self, "Xác nhận sai lệch nguồn",
                                    "Hãy chọn một cảnh báo ở thẻ “Cảnh báo cần xử lý” trước.")
            return
        orig_i, w = disp[i]
        w.resolved = True
        w.resolution = "Sai lệch trên PDF gốc – kế toán viên xác nhận, giữ nguyên số in."
        self.dirty = True
        storage.add_history(self.con, self.fr.path, "xac_nhan_sai_lech_nguon",
                            f"canh_bao={w.code} trang={w.page_index}")
        self._after_edit()

    def _printed_changed(self, v: int):
        if self._loading:
            return
        self.fr.pages[self.page_idx].printed_page = v or None
        self.dirty = True
        self._after_edit()

    # ---------------- điều hướng ----------------
    def _selection_changed(self, cur, prev):
        if cur is None:
            self.view.highlight(None)
            return
        r = self._rows[cur.row()] if cur.row() < len(self._rows) else None
        if r is None:
            return
        cv = r.cells.get(COLUMN_ORDER[cur.column()])
        self.view.highlight(cv.rect if cv and cv.rect else r.rect, ensure_visible=True)
        self.kind_combo.setCurrentIndex(list(RowKind).index(r.kind))
        self.refresh_bottom()

    def _warn_selected(self):
        i = self.warn_table.currentRow()
        disp = getattr(self, "_displayed_warnings", [])
        if 0 <= i < len(disp):
            orig_i, w = disp[i]
            if w.page_index is not None:
                self.navigate(w.page_index, w.row_index, w.col)

    def navigate(self, page_idx, row_index, col):
        if page_idx != self.page_idx:
            self.load_page(page_idx)
        if row_index is None:
            return
        self.filter_combo.setCurrentIndex(0)
        for i, r in enumerate(self._rows):
            if r.row_index == row_index:
                ci = COLUMN_ORDER.index(col) if col else 3
                self.grid.setCurrentCell(i, ci)
                cv = r.cells.get(col) if col else None
                self.view.highlight(cv.rect if cv and cv.rect else r.rect, center=True)
                break

    def jump_warning(self, step: int):
        open_ws = [i for i, w in enumerate(self.fr.warnings) if not w.resolved]
        if not open_ws:
            QMessageBox.information(self, "Cảnh báo", "Không còn cảnh báo nào chưa xử lý.")
            return
        if self._warn_cursor not in open_ws:
            self._warn_cursor = open_ws[0]
        else:
            k = open_ws.index(self._warn_cursor)
            self._warn_cursor = open_ws[(k + step) % len(open_ws)]
        w = self.fr.warnings[self._warn_cursor]
        self.navigate(w.page_index if w.page_index is not None else self.page_idx,
                      w.row_index, w.col)

    # ---------------- số liệu đối soát ----------------
    def refresh_bottom(self):
        p = self.fr.pages[self.page_idx]
        self.lbl["carry_in"].setText(f"{fmt_amount(p.carry_in_no)}  /  {fmt_amount(p.carry_in_co)}")
        self.lbl["sums"].setText(f"{fmt_amount(p.sum_no())}  /  {fmt_amount(p.sum_co())}")
        self.lbl["carry_out"].setText(f"{fmt_amount(p.carry_out_no)}  /  {fmt_amount(p.carry_out_co)}")
        self.lbl["grand"].setText(f"{fmt_amount(p.grand_total_no)}  /  {fmt_amount(p.grand_total_co)}")
        diffs = [abs(it.diff) for it in self.fr.reconcile
                 if it.diff is not None and not it.ok
                 and (it.name.startswith(f"Trang {self.page_idx + 1}:")
                      or it.name.startswith(f"Chuỗi trang {self.page_idx}→"))]
        self.lbl["diff"].setText(fmt_amount(sum(diffs, Decimal(0))) if diffs else "0")
        r = self._current_row()
        if r is not None and r.cell(Col.SO_CT).value:
            key = voucher_key(r.cell(Col.SO_CT).value)
            no = co = Decimal(0)
            for row in p.entry_rows():
                v = row.cell(Col.SO_CT).value
                if v and voucher_key(v) == key:
                    no += row.amount_no or Decimal(0)
                    co += row.amount_co or Decimal(0)
            self.lbl["voucher"].setText(f"{fmt_amount(no)}  /  {fmt_amount(co)}")
        else:
            self.lbl["voucher"].setText("–")
        self.lbl["book"].setText(f"{fmt_amount(self.fr.total_no())}  /  {fmt_amount(self.fr.total_co())}")
        items = [it for it in self.fr.reconcile
                 if it.name.startswith(f"Trang {self.page_idx + 1}:")
                 or it.name.startswith(f"Chuỗi trang {self.page_idx}→")
                 or it.name.startswith(f"Chuỗi trang {self.page_idx + 1}→")]
        self.rec_table.setRowCount(len(items))
        for i, it in enumerate(items):
            vals = [it.name, fmt_amount(it.expected), fmt_amount(it.actual),
                    fmt_amount(it.diff), "Khớp" if it.ok else "Lệch"]
            for ci, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if not it.ok:
                    item.setBackground(QColor(255, 225, 225))
                self.rec_table.setItem(i, ci, item)

    def refresh_warnings(self):
        f = getattr(self, "warn_filter_combo", None)
        mode = f.currentIndex() if f else 0
        if mode == 1:
            displayed = [(i, w) for i, w in enumerate(self.fr.warnings) if w.page_index == self.page_idx]
        elif mode == 2:
            displayed = [(i, w) for i, w in enumerate(self.fr.warnings) if not w.resolved]
        elif mode == 3:
            displayed = [(i, w) for i, w in enumerate(self.fr.warnings)
                         if w.level == WarningLevel.ACCOUNTING or "chênh lệch" in w.message.lower()]
        else:
            displayed = list(enumerate(self.fr.warnings))
        self._displayed_warnings = displayed

        self.warn_table.setRowCount(len(displayed))
        for row_i, (orig_i, w) in enumerate(displayed):
            vals = [str(w.page_index + 1) if w.page_index is not None else "",
                    str(w.row_index + 1) if w.row_index is not None else "",
                    w.message, LEVEL_LABEL[w.level],
                    "Đã xử lý" if w.resolved else "Chưa xử lý"]
            for ci, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.UserRole, orig_i)
                if not w.resolved and w.level == WarningLevel.EXTRACTION:
                    item.setBackground(QColor(255, 240, 190))
                elif not w.resolved and w.level == WarningLevel.ACCOUNTING:
                    item.setBackground(QColor(255, 225, 225))
                elif w.resolved:
                    item.setBackground(QColor(230, 245, 230))
                self.warn_table.setItem(row_i, ci, item)

    # ---------------- lưu / xuất ----------------
    def save(self):
        for p in self.fr.pages:
            refresh_page_totals(p)
        reconcile_file(self.fr)
        storage.save_file_result(self.con, self.fr)
        storage.add_history(self.con, self.fr.path, "luu_doi_soat",
                            f"trang={len(self.fr.pages)} canh_bao_mo={len(self.fr.open_extraction_warnings())}")
        self.dirty = False
        self.state_label.setText("Đã lưu đối soát.")
        self.refresh_bottom()
        self.refresh_warnings()
        self.saved.emit(self.fr)

    def export(self, final: bool):
        if self.dirty:
            self.save()
        if final:
            ok, reasons = can_export_final(self.fr)
            if not ok:
                QMessageBox.warning(self, "Chưa đủ điều kiện",
                                    "Chưa thể xuất file “Đã đối chiếu khớp PDF”:\n- "
                                    + "\n- ".join(reasons))
                return
        try:
            path = export_workbook(self.fr, self.out_dir, final=final)
            problems = verify_workbook(self.fr, path)
        except PermissionError as e:
            QMessageBox.warning(self, "Không ghi được Excel", str(e))
            return
        if problems:
            QMessageBox.warning(self, "File Excel chưa khớp",
                                "Mở lại file thấy khác dữ liệu:\n- " + "\n- ".join(problems[:6]))
            return
        if final:
            self.fr.status = FileStatus.DA_DOI_CHIEU
        storage.save_file_result(self.con, self.fr)
        storage.add_history(self.con, self.fr.path,
                            "xuat_da_doi_chieu" if final else "xuat_nhap", path)
        self.saved.emit(self.fr)
        QMessageBox.information(self, "Đã xuất Excel", f"Đã lưu và kiểm tra lại:\n{path}")

    # ---------------- thời gian ----------------
    def _tick(self):
        self._review_secs += 1
        h, rem = divmod(self._review_secs, 3600)
        m, s = divmod(rem, 60)
        self.clock_label.setText(f"Thời gian đối chiếu: {h:02d}:{m:02d}:{s:02d}")

    def closeEvent(self, event):
        self._timer.stop()
        if self.dirty:
            ret = QMessageBox.question(self, "Chưa lưu",
                                       "Còn thay đổi chưa lưu. Lưu trước khi đóng?")
            if ret == QMessageBox.Yes:
                self.save()
        key = f"review_seconds::{self.fr.path}"
        total = int(storage.get_meta(self.con, key, "0") or 0) + self._review_secs
        storage.set_meta(self.con, key, str(total))
        storage.add_history(self.con, self.fr.path, "dong_doi_soat",
                            f"giay_doi_chieu={self._review_secs}")
        self.closed.emit(self.fr.path, self._review_secs)
        super().closeEvent(event)