"""Luồng xử lý nền: chỉ gửi tín hiệu tiến trình/kết quả, không đụng giao diện."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QThread, Signal

from ..core.model import FileResult, FileStatus
from ..core.ocr_engine import OcrEngine
from ..core.pipeline import Pipeline, inspect_pdf

log = logging.getLogger("csnkc.worker")


class ConvertWorker(QThread):
    progress = Signal(dict)
    file_done = Signal(str, object)
    batch_done = Signal()

    def __init__(self, paths: list, out_dir: str, session_dir: str, preview_pages: int | None):
        super().__init__()
        self.paths = list(paths)
        self.out_dir = out_dir
        self.session_dir = session_dir
        self.preview_pages = preview_pages
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        limits = []
        for p in self.paths:
            n, err = inspect_pdf(p)
            limits.append(min(self.preview_pages, n) if self.preview_pages and not err else n)
        batch_total = sum(n + 2 for n in limits)
        offset = 0
        try:
            engine = OcrEngine()
        except Exception as e:
            log.exception("Không khởi động được bộ đọc chữ")
            for p in self.paths:
                fr = FileResult(path=p, status=FileStatus.LOI,
                                error=f"Không khởi động được bộ đọc chữ: {e}")
                self.file_done.emit(p, fr)
            self.batch_done.emit()
            return
        pipe = Pipeline(self.session_dir, progress_cb=self._on_progress,
                        stop_event=self.stop_event, engine=engine, out_dir=self.out_dir)
        self._offset = offset
        self._batch_total = batch_total
        for p, limit in zip(self.paths, limits):
            if self.stop_event.is_set():
                break
            try:
                fr = pipe.process_file(p, self.preview_pages, force_reextract=True)
            except Exception as e:
                log.exception("Lỗi xử lý %s", p)
                fr = FileResult(path=p, status=FileStatus.LOI, error=str(e))
            self.file_done.emit(p, fr)
            self._offset = offset = offset + limit + 2
        self.batch_done.emit()

    def _on_progress(self, **kw):
        kw["bdone"] = self._offset + kw.get("done", 0)
        kw["btotal"] = self._batch_total
        self.progress.emit(kw)