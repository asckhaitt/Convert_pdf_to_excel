"""Màn hình chính: chọn dữ liệu – chọn nơi lưu – xử lý, tiến trình realtime, bảng kết quả."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGridLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import storage
from ..core.model import FileStatus
from ..core.paths import session_root
from ..core.pipeline import inspect_pdf
from ..core.reconcile import reconcile_file
from .help_dialog import HelpDialog
from .review_window import ReviewWindow, fmt_amount
from .worker import ConvertWorker

RESULT_COLS = ["Tên PDF", "Trang đã xử lý", "Số dòng hạch toán", "Tổng Nợ", "Tổng Có",
               "Chênh lệch Nợ–Có", "Cảnh báo chưa xử lý", "Trạng thái đối chiếu",
               "Kiểm tra kế toán", "Thời gian xử lý", "Thao tác"]


def hms(secs: int) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chuyển Sổ Nhật Ký Chung sang Excel")
        self.resize(1400, 860)
        self.session_dir = session_root()
        self.con = storage.open_db(str(self.session_dir / "phien.sqlite"))
        self.results = {}
        self.page_counts = {}
        self._file_start = {}
        self._file_secs = {}
        self._batch_start = None
        self._worker = None
        self._reviews = {}
        self._build_ui()
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick)
        self._clock.start(1000)
        for path in storage.list_files(self.con):
            fr = storage.load_file_result(self.con, path)
            if fr:
                self.results[path] = fr
                self.page_counts[path] = fr.page_count
                self._add_result_row(path)
        self._refresh_time_labels()

    # ---------------- giao diện ----------------
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        self.setCentralWidget(central)

        g1 = QGroupBox("1. Chọn dữ liệu sổ nhật ký chung (PDF)")
        l1 = QVBoxLayout(g1)
        b1 = QHBoxLayout()
        self.btn_files = QPushButton("Chọn tệp PDF…")
        self.btn_folder = QPushButton("Chọn thư mục chứa PDF…")
        self.btn_remove = QPushButton("Bỏ file đã chọn")
        self.sel_label = QLabel("Chưa chọn file nào.")
        for w in (self.btn_files, self.btn_folder, self.btn_remove):
            b1.addWidget(w)
        b1.addWidget(self.sel_label, 1)
        l1.addLayout(b1)
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(110)
        l1.addWidget(self.file_list)
        root.addWidget(g1)

        g2 = QGroupBox("2. Chọn nơi lưu Excel")
        l2 = QHBoxLayout(g2)
        self.out_edit = QLineEdit()
        self.btn_out = QPushButton("Đổi thư mục…")
        self.btn_open_out = QPushButton("Mở thư mục kết quả")
        l2.addWidget(self.out_edit, 1)
        l2.addWidget(self.btn_out)
        l2.addWidget(self.btn_open_out)
        root.addWidget(g2)

        g3 = QGroupBox("3. Chuyển đổi và đối chiếu")
        l3 = QHBoxLayout(g3)
        self.chk_preview = QCheckBox("Xem trước 2 trang")
        self.btn_start = QPushButton("Bắt đầu chuyển đổi")
        self.btn_stop = QPushButton("Dừng xử lý")
        self.btn_check = QPushButton("Kiểm tra dữ liệu")
        self.btn_excel = QPushButton("Mở Excel")
        self.btn_clear = QPushButton("Xóa lịch sử")
        self.btn_help = QPushButton("Hướng dẫn sử dụng")
        self.btn_stop.setEnabled(False)
        for w in (self.chk_preview, self.btn_start, self.btn_stop, self.btn_check,
                  self.btn_excel, self.btn_clear, self.btn_help):
            l3.addWidget(w)
        l3.addStretch(1)
        root.addWidget(g3)

        gp = QGroupBox("Tiến trình")
        lp = QGridLayout(gp)
        self.clock_label = QLabel("Đã chạy: 00:00:00")
        self.review_label = QLabel("Thời gian đối chiếu thủ công: 00:00:00")
        self.file_label = QLabel("File đang xử lý: –")
        self.page_label = QLabel("Trang: –")
        self.stage_label = QLabel("Công đoạn: –")
        self.warn_label = QLabel("Cảnh báo cần xử lý: 0")
        self.bar_all = QProgressBar()
        self.bar_page = QProgressBar()
        lp.addWidget(self.clock_label, 0, 0)
        lp.addWidget(self.review_label, 0, 1)
        lp.addWidget(self.file_label, 1, 0)
        lp.addWidget(self.page_label, 1, 1)
        lp.addWidget(self.stage_label, 2, 0)
        lp.addWidget(self.warn_label, 2, 1)
        lp.addWidget(QLabel("Tổng toàn bộ danh sách:"), 3, 0)
        lp.addWidget(self.bar_all, 3, 1)
        lp.addWidget(QLabel("File hiện tại:"), 4, 0)
        lp.addWidget(self.bar_page, 4, 1)
        root.addWidget(gp)

        self.table = QTableWidget(0, len(RESULT_COLS))
        self.table.setHorizontalHeaderLabels(RESULT_COLS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(7, 170)
        self.table.setColumnWidth(8, 160)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        root.addWidget(self.table, 1)

        self.btn_files.clicked.connect(self.choose_files)
        self.btn_folder.clicked.connect(self.choose_folder)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_out.clicked.connect(self.choose_out)
        self.btn_open_out.clicked.connect(self.open_out)
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_check.clicked.connect(self.check_data)
        self.btn_excel.clicked.connect(self.open_excel)
        self.btn_clear.clicked.connect(self.clear_history)
        self.btn_help.clicked.connect(lambda: HelpDialog(self).exec())

    def _clean_temp_files(self):
        """Dọn dẹp các tệp ảnh và thư mục tạm thời để giải phóng dung lượng đĩa."""
        import shutil, tempfile
        try:
            s_temp = self.session_dir / "temp"
            if s_temp.exists():
                shutil.rmtree(s_temp, ignore_errors=True)
                s_temp.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        try:
            cur_mei = getattr(sys, "_MEIPASS", None)
            t_dir = Path(tempfile.gettempdir())
            for p in t_dir.glob("_MEI*"):
                if cur_mei and str(p.resolve()) == str(Path(cur_mei).resolve()):
                    continue
                shutil.rmtree(p, ignore_errors=True)
            for p in t_dir.glob("csnkc_ocr_*"):
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            if self._worker and self._worker.isRunning():
                self._worker.stop()
                self._worker.wait(3000)
            self._clean_temp_files()
            if self.con:
                self.con.close()
        except Exception:
            pass
        event.accept()

    def clear_history(self):
        res = QMessageBox.question(
            self, "Xác nhận xóa lịch sử",
            "Bạn có chắc muốn xóa toàn bộ lịch sử các lần chuyển đổi trước và dọn sạch các tệp đệm tạm không?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if res != QMessageBox.Yes:
            return
        try:
            self.con.close()
            import shutil
            # Xóa sạch các thư mục ảnh tạm và cache trong Du_lieu_phien
            if self.session_dir.exists():
                for item in self.session_dir.iterdir():
                    try:
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                        elif item.name.startswith("phien.sqlite"):
                            item.unlink(missing_ok=True)
                    except Exception:
                        pass

            self._clean_temp_files()
            db_file = self.session_dir / "phien.sqlite"
            self.con = storage.open_db(str(db_file))
            self.results.clear()
            self.page_counts.clear()
            self.table.setRowCount(0)
            self.clock_label.setText("Đã chạy: 00:00:00")
            self.review_label.setText("Thời gian đối chiếu thủ công: 00:00:00")
            self.bar_all.setValue(0)
            self.bar_page.setValue(0)
            self.file_label.setText("File đang xử lý: –")
            self.page_label.setText("Trang: –")
            self.stage_label.setText("Công đoạn: –")
            self.warn_label.setText("Cảnh báo cần xử lý: 0")
            self.statusBar().showMessage("Đã xóa toàn bộ lịch sử phiên và dọn sạch các tệp đệm tạm.")
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"Không thể xóa lịch sử: {e}")

    # ---------------- chọn dữ liệu ----------------
    def _add_paths(self, paths):
        have = {self.file_list.item(i).text() for i in range(self.file_list.count())}
        for p in paths:
            p = str(Path(p).resolve())
            if p in have:
                continue
            n, err = inspect_pdf(p)
            if err:
                QMessageBox.warning(self, "Không đọc được PDF", f"{Path(p).name}: {err}")
                continue
            self.page_counts[p] = n
            self.file_list.addItem(p)
            have.add(p)
        if not self.out_edit.text() and self.file_list.count():
            first = Path(self.file_list.item(0).text())
            self.out_edit.setText(str(first.parent / "Excel_da_chuyen_doi"))
        self._update_sel_label()

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Chọn tệp PDF sổ nhật ký chung",
                                                "", "PDF (*.pdf)")
        self._add_paths(paths)

    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa PDF")
        if d:
            self._add_paths(sorted(str(p) for p in Path(d).glob("*.pdf")))

    def remove_selected(self):
        for item in self.file_list.selectedItems():
            self.page_counts.pop(item.text(), None)
            self.file_list.takeItem(self.file_list.row(item))
        self._update_sel_label()

    def _update_sel_label(self):
        n = self.file_list.count()
        pages = sum(self.page_counts.get(self.file_list.item(i).text(), 0) for i in range(n))
        self.sel_label.setText(f"Đã chọn {n} file / {pages} trang.")

    def choose_out(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu Excel",
                                             self.out_edit.text() or "")
        if d:
            self.out_edit.setText(d)

    def open_out(self):
        d = self.out_edit.text()
        if d:
            Path(d).mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    # ---------------- xử lý ----------------
    def start(self):
        paths = [self.file_list.item(i).text() for i in range(self.file_list.count())]
        if not paths:
            QMessageBox.information(self, "Chưa chọn dữ liệu",
                                    "Hãy chọn ít nhất một tệp PDF sổ nhật ký chung.")
            return
        out_dir = self.out_edit.text().strip()
        if not out_dir:
            QMessageBox.information(self, "Chưa chọn nơi lưu", "Hãy chọn thư mục lưu Excel.")
            return
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        for p in paths:
            if p not in self.results:
                self._add_result_row(p)
            self._file_start.pop(p, None)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._batch_start = time.monotonic()
        self._worker = ConvertWorker(paths, out_dir, str(self.session_dir),
                                     2 if self.chk_preview.isChecked() else None)
        self._worker.progress.connect(self.on_progress)
        self._worker.file_done.connect(self.on_file_done)
        self._worker.batch_done.connect(self.on_batch_done)
        self._worker.start()
        self.statusBar().showMessage("Đang chuyển đổi…")

    def stop(self):
        if self._worker:
            self._worker.stop()
            self.statusBar().showMessage("Sẽ dừng sau trang đang xử lý; các trang đã xong được giữ lại.")

    def on_progress(self, kw: dict):
        path = kw.get("file", "")
        self._file_start.setdefault(path, time.monotonic())
        self.file_label.setText(f"File đang xử lý: {Path(path).name}")
        self.page_label.setText(f"Trang: {kw.get('page', 0)}/{kw.get('pages', 0)}")
        self.stage_label.setText(f"Công đoạn: {kw.get('stage', '')}")
        total = kw.get("total") or 1
        self.bar_page.setValue(int(100 * kw.get("done", 0) / total))
        btotal = kw.get("btotal") or 1
        self.bar_all.setValue(int(100 * kw.get("bdone", 0) / btotal))

    def on_file_done(self, path: str, fr):
        self.results[path] = fr
        if path in self._file_start:
            self._file_secs[path] = time.monotonic() - self._file_start.pop(path)
        self._update_row(path)
        self.warn_label.setText(
            f"Cảnh báo cần xử lý: {len(fr.open_extraction_warnings())}")
        if fr.status == FileStatus.LOI:
            self.statusBar().showMessage(f"{Path(path).name}: {fr.error}")

    def on_batch_done(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if self._batch_start is not None:
            elapsed = int(time.monotonic() - self._batch_start)
            prev = int(storage.get_meta(self.con, "convert_seconds", "0") or 0)
            storage.set_meta(self.con, "convert_seconds", str(prev + elapsed))
            self._batch_start = None
        self.bar_all.setValue(100)
        self.stage_label.setText("Công đoạn: Hoàn tất chuyển đổi tự động – còn bước đối chiếu của kế toán viên.")
        self.statusBar().showMessage(
            "Chuyển đổi tự động xong. File nháp ở trạng thái “Cần đối chiếu” cho tới khi được xác nhận khớp PDF.")
        self._refresh_time_labels()
        self._clean_temp_files()
        self._worker = None

    def _tick(self):
        if self._batch_start is not None:
            self.clock_label.setText(f"Đã chạy: {hms(time.monotonic() - self._batch_start)}")

    def _refresh_time_labels(self):
        prev = int(storage.get_meta(self.con, "convert_seconds", "0") or 0)
        self.clock_label.setText(f"Đã chạy: {hms(prev)}")
        review = 0
        for p in self.results:
            review += int(storage.get_meta(self.con, f"review_seconds::{p}", "0") or 0)
        self.review_label.setText(f"Thời gian đối chiếu thủ công: {hms(review)}")

    # ---------------- bảng kết quả ----------------
    def _add_result_row(self, path: str):
        r = self.table.rowCount()
        self.table.insertRow(r)
        item = QTableWidgetItem(Path(path).name)
        item.setData(Qt.UserRole, path)
        item.setToolTip(path)
        self.table.setItem(r, 0, item)
        for ci in range(1, len(RESULT_COLS) - 1):
            self.table.setItem(r, ci, QTableWidgetItem("–"))
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(2, 2, 2, 2)
        b_review = QPushButton("Đối soát")
        b_excel = QPushButton("Excel")
        b_review.clicked.connect(lambda _=False, p=path: self.open_review(p))
        b_excel.clicked.connect(lambda _=False, p=path: self.open_excel_path(p))
        lay.addWidget(b_review)
        lay.addWidget(b_excel)
        self.table.setCellWidget(r, len(RESULT_COLS) - 1, box)
        self._update_row(path)

    def _row_of(self, path: str):
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == path:
                return r
        return -1

    def _update_row(self, path: str):
        r = self._row_of(path)
        if r < 0:
            return
        fr = self.results.get(path)
        if fr is None:
            return
        tn, tc = fr.total_no(), fr.total_co()
        vals = [f"{fr.processed_pages}/{fr.page_count}",
                str(sum(1 for _ in fr.entry_rows())),
                fmt_amount(tn), fmt_amount(tc), fmt_amount(tn - tc),
                str(len(fr.open_extraction_warnings())),
                fr.status.value, fr.accounting.value,
                hms(self._file_secs.get(path, 0))]
        for ci, v in enumerate(vals, start=1):
            self.table.setItem(r, ci, QTableWidgetItem(v))

    def _selected_path(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        return self.table.item(r, 0).data(Qt.UserRole)

    # ---------------- đối soát / kiểm tra ----------------
    def open_review(self, path: str):
        fr = storage.load_file_result(self.con, path) or self.results.get(path)
        if fr is None or not fr.pages:
            QMessageBox.information(self, "Chưa có dữ liệu",
                                    "File này chưa được chuyển đổi, chưa có gì để đối soát.")
            return
        reconcile_file(fr)
        win = self._reviews.get(path)
        if win is None:
            win = ReviewWindow(fr, self.con, self.out_edit.text() or str(Path(path).parent), self)
            win.saved.connect(self._on_review_saved)
            win.closed.connect(self._on_review_closed)
            self._reviews[path] = win
        win.show()
        win.raise_()
        win.activateWindow()

    def _on_review_saved(self, fr):
        self.results[fr.path] = fr
        self._update_row(fr.path)

    def _on_review_closed(self, path: str, secs: int):
        self._reviews.pop(path, None)
        self._refresh_time_labels()

    def check_data(self):
        path = self._selected_path()
        if not path:
            QMessageBox.information(self, "Kiểm tra dữ liệu", "Hãy chọn một file ở bảng kết quả.")
            return
        fr = storage.load_file_result(self.con, path) or self.results.get(path)
        if fr is None:
            return
        reconcile_file(fr)
        tn, tc = fr.total_no(), fr.total_co()
        msg = (f"Số dòng hạch toán: {sum(1 for _ in fr.entry_rows())}\n"
               f"Tổng Nợ: {fmt_amount(tn)}\nTổng Có: {fmt_amount(tc)}\n"
               f"Chênh lệch Nợ–Có: {fmt_amount(tn - tc)}\n"
               f"Cảnh báo trích xuất chưa xử lý: {len(fr.open_extraction_warnings())}\n"
               f"Trạng thái đối chiếu: {fr.status.value}\n"
               f"Kiểm tra kế toán: {fr.accounting.value}")
        QMessageBox.information(self, "Kiểm tra dữ liệu", msg)

    def open_excel(self):
        path = self._selected_path()
        if path:
            self.open_excel_path(path)

    def open_excel_path(self, path: str):
        fr = self.results.get(path)
        target = (fr.final_excel or fr.draft_excel) if fr else ""
        if not target or not Path(target).exists():
            QMessageBox.information(self, "Chưa có file Excel",
                                    "File này chưa được xuất Excel.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))