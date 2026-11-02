"""Điều phối xử lý một PDF: trích xuất → đối soát → xuất nháp → kiểm tra lại."""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pymupdf

from . import storage
from .excel_export import export_workbook, verify_workbook
from .extract import extract_page
from .model import FileResult, FileStatus, WarningItem, WarningLevel
from .ocr_engine import OcrEngine
from .reconcile import reconcile_file
from .intelligent_reconcile import auto_reconcile_and_repair

STAGES = ("Đọc trang", "Nhận diện bảng", "Đọc dữ liệu", "Đối soát",
          "Tạo Excel", "Kiểm tra file Excel")


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_pdf(path: str):
    """Trả về (số trang, lỗi). Không thay đổi file gốc."""
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        return 0, f"Không mở được PDF: {e}"
    try:
        if doc.needs_pass:
            return 0, "PDF được bảo vệ bằng mật khẩu."
        n = doc.page_count
        if n == 0:
            return 0, "PDF không có trang nào."
        return n, ""
    finally:
        doc.close()


class Pipeline:
    def __init__(self, session_dir: str, progress_cb=None,
                 stop_event: threading.Event | None = None, engine: OcrEngine | None = None,
                 out_dir: str | None = None):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.session_dir / "phien.sqlite")
        self.con = storage.open_db(self.db_path)
        self.progress_cb = progress_cb or (lambda **kw: None)
        self.stop_event = stop_event or threading.Event()
        self.engine = engine or OcrEngine()
        self.out_dir = Path(out_dir) if out_dir else None

    def _emit(self, **kw):
        self.progress_cb(**kw)

    def process_file(self, pdf_path: str, preview_pages: int | None = None,
                     force_reextract: bool = False) -> FileResult:
        pdf_path = str(Path(pdf_path).resolve())
        n, err = inspect_pdf(pdf_path)
        if err:
            fr = FileResult(path=pdf_path, status=FileStatus.LOI, error=err)
            return fr
        digest = sha256_of(pdf_path)
        fr = storage.load_file_result(self.con, pdf_path)
        if not force_reextract and fr and fr.sha256 == digest and fr.processed_pages and not preview_pages:
            fr.status = FileStatus.DANG_CHUYEN_DOI
        else:
            fr = FileResult(path=pdf_path, sha256=digest, page_count=n,
                            status=FileStatus.DANG_CHUYEN_DOI)
        fr.page_count = n
        fr.error = ""
        fr.stopped = False

        limit = min(preview_pages, n) if preview_pages else n
        file_dir = self.session_dir / digest[:16]
        file_dir.mkdir(parents=True, exist_ok=True)

        total_units = limit + 2
        done = 0
        last_good_xs = None
        for i in range(limit):
            if self.stop_event.is_set():
                fr.stopped = True
                fr.status = FileStatus.DA_DUNG
                storage.save_file_result(self.con, fr)
                return fr
            if not force_reextract and i < len(fr.pages) and fr.pages[i].rows and not preview_pages:
                if getattr(fr.pages[i], "grid_xs", None) and len(fr.pages[i].grid_xs) == 9:
                    last_good_xs = fr.pages[i].grid_xs
                done += 1
                self._emit(file=pdf_path, page=i + 1, pages=limit, stage="Đọc trang",
                           done=done, total=total_units, skipped=True)
                continue
            self._emit(file=pdf_path, page=i + 1, pages=limit, stage="Nhận diện bảng",
                       done=done, total=total_units)
            img_path = str(file_dir / f"page_{i:04d}.png")
            page = extract_page(pdf_path, i, self.engine, image_out=img_path,
                                fallback_xs=last_good_xs, doc_total_pages=fr.page_count)
            if not page.info_page and getattr(page, "grid_xs", None) and len(page.grid_xs) == 9:
                last_good_xs = page.grid_xs
            if i < len(fr.pages):
                fr.pages[i] = page
            else:
                fr.pages.append(page)
            fr.processed_pages = len(fr.pages)
            done += 1
            self._emit(file=pdf_path, page=i + 1, pages=limit, stage="Đối soát",
                       done=done, total=total_units)
            storage.save_file_result(self.con, fr)

        self._emit(file=pdf_path, page=limit, pages=limit, stage="Tự động cân đối",
                   done=done, total=total_units)
        auto_reconcile_and_repair(fr, self.engine, pdf_path)
        reconcile_file(fr)
        self._emit(file=pdf_path, page=limit, pages=limit, stage="Tạo Excel",
                   done=done, total=total_units)
        try:
            export_dir = self.out_dir or file_dir
            export_dir.mkdir(parents=True, exist_ok=True)
            draft = export_workbook(fr, str(export_dir), final=False)
            problems = verify_workbook(fr, draft)
            done += 1
            self._emit(file=pdf_path, page=limit, pages=limit, stage="Kiểm tra file Excel",
                       done=done, total=total_units)
            if problems:
                fr.warnings.append(WarningItem(
                    code="EXCEL_KHONG_KHOP",
                    message="File Excel nháp mở lại không khớp dữ liệu: " + "; ".join(problems[:5]),
                    level=WarningLevel.EXTRACTION))
            done += 1
        except PermissionError as e:
            fr.warnings.append(WarningItem(code="EXCEL_DANG_MO",
                                           message=str(e), level=WarningLevel.EXTRACTION))
        except OSError as e:
            fr.warnings.append(WarningItem(
                code="EXCEL_LOI_GHI",
                message=f"Không ghi được file Excel (file đang mở hoặc thư mục chỉ đọc?): {e}",
                level=WarningLevel.EXTRACTION))
        fr.status = FileStatus.DA_DUNG if fr.stopped else FileStatus.CAN_DOI_CHIEU
        storage.save_file_result(self.con, fr)
        storage.add_history(self.con, pdf_path, "xu_ly",
                            f"processed={fr.processed_pages}/{n} preview={bool(preview_pages)}")
        self._emit(file=pdf_path, page=limit, pages=limit, stage="Hoàn tất",
                   done=total_units, total=total_units)
        return fr
