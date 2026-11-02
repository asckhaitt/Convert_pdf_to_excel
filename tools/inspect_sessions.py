import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import storage
from app.core.reconcile import can_export_final, reconcile_file

con = storage.open_db("Du_lieu_phien/phien.sqlite")
files = con.execute("SELECT path FROM files").fetchall()

for (p,) in sorted(files):
    fr = storage.load_file_result(con, p)
    reconcile_file(fr)
    print("=" * 70)
    print(f"File: {Path(p).name}")
    print(f"Pages: {fr.processed_pages}/{fr.page_count}")
    print(f"Status: {fr.status.value} | Accounting: {fr.accounting.value}")
    print(f"Entries: {len(list(fr.entry_rows()))}")
    diff = fr.total_no() - fr.total_co()
    print(f"Total No: {fr.total_no():,} | Total Co: {fr.total_co():,} | Diff: {diff:,}")
    recon_fail = [it for it in fr.reconcile if not it.ok]
    print(f"Reconcile checks: {len(fr.reconcile)} | Failed: {len(recon_fail)}")
    for it in recon_fail[:10]:
        print(f"  [FAIL] {it.name}: exp={it.expected:,} act={it.actual:,} diff={it.diff:,}")
    warns = fr.warnings
    warn_ext = sum(1 for w in warns if w.level.value == "canh_bao")
    warn_info = sum(1 for w in warns if w.level.value == "thong_tin")
    print(f"Warnings: total={len(warns)} (canh_bao={warn_ext}, thong_tin={warn_info})")
    
    # Analyze types of warnings
    warn_counts = {}
    for w in warns:
        warn_counts[w.code] = warn_counts.get(w.code, 0) + 1
    for code, cnt in sorted(warn_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  - {code}: {cnt}")
