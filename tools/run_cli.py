"""Chạy thử lõi trích xuất + đối soát + xuất Excel từ dòng lệnh."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.pipeline import Pipeline
from app.core.reconcile import can_export_final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pages", type=int, default=None)
    ap.add_argument("--session", default=str(ROOT / ".scratch" / "session"))
    args = ap.parse_args()

    t0 = time.time()
    pipe = Pipeline(args.session, progress_cb=lambda **kw: print(
        f"[{kw.get('stage')}] trang {kw.get('page')}/{kw.get('pages')} "
        f"({kw.get('done')}/{kw.get('total')})", flush=True))
    fr = pipe.process_file(args.pdf, preview_pages=args.pages)
    print(f"\nstatus={fr.status.value} accounting={fr.accounting.value} "
          f"pages={fr.processed_pages}/{fr.page_count} time={time.time()-t0:.1f}s")
    print(f"entries={len(list(fr.entry_rows()))} total_no={fr.total_no():,} total_co={fr.total_co():,}")
    print(f"draft={fr.draft_excel}")
    ok, reasons = can_export_final(fr)
    print("final_ok=", ok, reasons)
    print("\n-- reconcile --")
    for it in fr.reconcile:
        print(f"{'OK ' if it.ok else 'LECH'} {it.name}: expected={it.expected} actual={it.actual} diff={it.diff}")
    print("\n-- warnings --")
    for w in fr.warnings:
        print(f"[{w.level.value}] {w.code}: {w.message}")
    print("\n-- rows page 1 --")
    if fr.pages:
        for r in fr.pages[0].rows:
            print(r.row_index, r.kind.value, "|", r.cell(__import__('app.core.model', fromlist=['Col']).Col.DIEN_GIAI).raw.replace("\n", " / ")[:70])


if __name__ == "__main__":
    main()
