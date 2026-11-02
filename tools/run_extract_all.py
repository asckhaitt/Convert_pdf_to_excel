"""Chạy bóc tách và đối soát toàn bộ 5 sổ Nhật ký chung (2015 -> 2019).
Cập nhật tiến trình từng file, từng trang và lưu kết quả vào Du_lieu_phien + Excel file.
"""
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
    skipped = " (đã có - bỏ qua)" if kw.get("skipped") else ""
    print(f"[{pct:5.1f}%] {stage:<18} | Trang {page:>2}/{pages}{skipped}", flush=True)


def process_book(pipe: Pipeline, filename: str, force: bool = False):
    pdf_path = str(PDF_DIR / filename)
    print(f"\n{'='*70}", flush=True)
    print(f"=== BẮT ĐẦU XỬ LÝ: {filename} (force={force}) ===", flush=True)
    print(f"{'='*70}", flush=True)
    t0 = time.time()
    fr = pipe.process_file(pdf_path, preview_pages=None, force_reextract=force)
    elapsed = time.time() - t0
    print(f"\n--- KẾT QUẢ CHO: {filename} ({elapsed:.1f}s) ---", flush=True)
    print(f"  Trạng thái đối chiếu: {fr.status.value}")
    print(f"  Kiểm tra kế toán:     {fr.accounting.value}")
    print(f"  Số trang đã xử lý:    {fr.processed_pages}/{fr.page_count}")
    print(f"  Số dòng bút toán:     {len(list(fr.entry_rows()))}")
    print(f"  Tổng Nợ trích xuất:   {fr.total_no():,}")
    print(f"  Tổng Có trích xuất:   {fr.total_co():,}")
    print(f"  Chênh lệch Nợ - Có:   {(fr.total_no() - fr.total_co()):,}")
    print(f"  File Excel xuất ra:   {fr.draft_excel}")
    
    final_ok, reasons = can_export_final(fr)
    print(f"  Đủ điều kiện chốt ĐÃ ĐỐI CHIẾU: {final_ok}")
    
    recon_fail = [it for it in fr.reconcile if not it.ok]
    print(f"  Số công thức chuyển trang kiểm tra: {len(fr.reconcile)} (lệch: {len(recon_fail)})")
    
    warn_by_level = {}
    for w in fr.warnings:
        warn_by_level.setdefault(w.level.value, []).append(w)
    warn_summary = ", ".join(f"{lvl}={len(items)}" for lvl, items in warn_by_level.items())
    print(f"  Cảnh báo: {warn_summary}")
    return fr


def main():
    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--force"]
    target = args[0] if args else None
    pipe = Pipeline(
        session_dir=SESSION_DIR,
        progress_cb=on_progress,
        out_dir=OUT_DIR,
    )
    if target:
        process_book(pipe, target, force=force)
    else:
        for book in BOOKS:
            process_book(pipe, book, force=force)


if __name__ == "__main__":
    main()
