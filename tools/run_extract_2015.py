"""Chạy bóc tách đầy đủ 36 trang của SO NKC 2015 CTY NGOC HA.pdf.
Cập nhật tiến trình theo từng trang và lưu kết quả vào Du_lieu_phien + Excel file.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Đảm bảo in tiếng Việt trên console Windows không lỗi charmap
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.pipeline import Pipeline
from app.core.reconcile import can_export_final

PDF_PATH = str(ROOT / "PDF file" / "SO NKC 2015 CTY NGOC HA.pdf")
SESSION_DIR = str(ROOT / "Du_lieu_phien")
OUT_DIR = str(ROOT / "Excel file")

def on_progress(**kw):
    stage = kw.get("stage", "")
    page = kw.get("page", 0)
    pages = kw.get("pages", 36)
    done = kw.get("done", 0)
    total = kw.get("total", 38)
    pct = (done / total * 100) if total else 0
    skipped = " (đã có - bỏ qua)" if kw.get("skipped") else ""
    print(f"[{pct:5.1f}%] Giai đoạn: {stage:<18} | Trang {page:>2}/{pages}{skipped}", flush=True)

def main():
    print(f"=== BẮT ĐẦU BÓC TÁCH TOÀN BỘ 36 TRANG SỔ 2015 ===", flush=True)
    t0 = time.time()
    
    pipe = Pipeline(
        session_dir=SESSION_DIR,
        progress_cb=on_progress,
        out_dir=OUT_DIR,
    )
    
    fr = pipe.process_file(PDF_PATH, preview_pages=None)
    
    elapsed = time.time() - t0
    print(f"\n=== HOÀN TẤT BÓC TÁCH ({elapsed:.1f}s) ===", flush=True)
    print(f"Trạng thái đối chiếu: {fr.status.value}")
    print(f"Kiểm tra kế toán:     {fr.accounting.value}")
    print(f"Số trang đã xử lý:    {fr.processed_pages}/{fr.page_count}")
    print(f"Số dòng bút toán:     {len(list(fr.entry_rows()))}")
    print(f"Tổng Nợ trích xuất:   {fr.total_no():,}")
    print(f"Tổng Có trích xuất:   {fr.total_co():,}")
    print(f"Chênh lệch Nợ - Có:   {(fr.total_no() - fr.total_co()):,}")
    print(f"File Excel xuất ra:   {fr.draft_excel}")
    
    final_ok, reasons = can_export_final(fr)
    print(f"Đủ điều kiện chốt ĐÃ ĐỐI CHIẾU: {final_ok}")
    if reasons:
        print("Lý do chưa chốt:")
        for r in reasons:
            print(f"  - {r}")
            
    print("\n--- KIỂM TRA CHUỖI CÔNG THỨC CHUYỂN TRANG (1 -> 36) ---")
    recon_fail = [it for it in fr.reconcile if not it.ok]
    print(f"Tổng số công thức kiểm tra: {len(fr.reconcile)}")
    print(f"Số công thức lệch:          {len(recon_fail)}")
    def fmt(v):
        return f"{v:,}" if v is not None else "N/A"

    for it in recon_fail[:15]:
        print(f"  [LỆCH] {it.name}: kỳ vọng={fmt(it.expected)} | thực tế={fmt(it.actual)} | lệch={fmt(it.diff)}")
    if len(recon_fail) > 15:
        print(f"  ... và {len(recon_fail) - 15} công thức lệch khác.")
        
    print("\n--- TỔNG HỢP CẢNH BÁO ---")
    warn_by_level = {}
    for w in fr.warnings:
        warn_by_level.setdefault(w.level.value, []).append(w)
    for lvl, items in warn_by_level.items():
        print(f"Mức [{lvl}]: {len(items)} cảnh báo")
        for w in items[:10]:
            print(f"  - ({w.code}) {w.message}")
        if len(items) > 10:
            print(f"  ... và {len(items) - 10} cảnh báo khác.")

if __name__ == "__main__":
    main()
