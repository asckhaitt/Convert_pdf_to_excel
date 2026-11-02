"""Trích xuất và xuất lại Excel toàn bộ 5 sổ với cấu hình OCR mới và dòng Tổng cộng."""
from __future__ import annotations

import sys
import time
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.pipeline import Pipeline
from app.core.reconcile import can_export_final

PDF_DIR = ROOT / "PDF file"
SESSION_DIR = str(ROOT / "Du_lieu_phien")
OUT_DIR = str(ROOT / "Excel file")

BOOKS = [
    "SO NKC 2015 CTY NGOC HA.pdf",
    "SO NKC 2016 CTY NGOC HA.pdf",
    "SO NKC 2017 CTY NGOC HA.pdf",
    "SO NKC 2018 CTY NGOC HA.pdf",
    "SO NKC 2019 CTY NGOC HA.pdf",
]


def on_progress(**kw):
    stage = kw.get("stage", "")
    page = kw.get("page", 0)
    pages = kw.get("pages", 0)
    done = kw.get("done", 0)
    total = kw.get("total", 0)
    pct = (done / total * 100) if total else 0
    print(f"[{pct:5.1f}%] {stage:<18} | Trang {page:>2}/{pages}", flush=True)


def process_book(pipe: Pipeline, filename: str):
    pdf_path = str(PDF_DIR / filename)
    print(f"\n{'='*70}", flush=True)
    print(f"=== BẮT ĐẦU XỬ LÝ: {filename} ===", flush=True)
    print(f"{'='*70}", flush=True)
    t0 = time.time()
    fr = pipe.process_file(pdf_path, preview_pages=None, force_reextract=True)
    elapsed = time.time() - t0
    print(f"\n--- KẾT QUẢ CHO: {filename} ({elapsed:.1f}s) ---", flush=True)
    print(f"  Trạng thái:           {fr.status.value}")
    print(f"  Số trang đã xử lý:    {fr.processed_pages}/{fr.page_count}")
    print(f"  Số dòng bút toán:     {len(list(fr.entry_rows()))}")
    print(f"  Tổng Nợ trích xuất:   {fr.total_no():,}")
    print(f"  Tổng Có trích xuất:   {fr.total_co():,}")
    print(f"  Chênh lệch Nợ - Có:   {(fr.total_no() - fr.total_co()):,}")
    print(f"  File Excel xuất ra:   {fr.draft_excel}")
    return fr


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    pipe = Pipeline(
        session_dir=SESSION_DIR,
        progress_cb=on_progress,
        out_dir=OUT_DIR,
    )
    if target:
        process_book(pipe, target)
    else:
        for book in BOOKS:
            process_book(pipe, book)


if __name__ == "__main__":
    main()
