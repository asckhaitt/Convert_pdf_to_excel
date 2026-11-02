import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import storage
from app.core.intelligent_reconcile import auto_reconcile_and_repair
from app.core.reconcile import reconcile_file

con = storage.open_db("Du_lieu_phien/phien.sqlite")
files = con.execute("SELECT path FROM files").fetchall()

for (p,) in sorted(files):
    fr = storage.load_file_result(con, p)
    auto_reconcile_and_repair(fr)
    reconcile_file(fr)
    fails = [it for it in fr.reconcile if not it.ok]
    diff = fr.total_no() - fr.total_co()
    print("=" * 80)
    print(f"=== {Path(p).name} ===")
    print(f"Total No: {fr.total_no():,} | Total Co: {fr.total_co():,} | Diff: {diff:,}")
    gt_no = next((p.grand_total_no for p in reversed(fr.pages) if p.grand_total_no is not None), None)
    gt_co = next((p.grand_total_co for p in reversed(fr.pages) if p.grand_total_co is not None), None)
    gt_no_s = f"{gt_no:,}" if gt_no is not None else "None"
    gt_co_s = f"{gt_co:,}" if gt_co is not None else "None"
    print(f"Grand Total No in Doc: {gt_no_s} | Co in Doc: {gt_co_s}")
    print(f"Reconcile fails count: {len(fails)}")
    for f in fails:
        exp_str = f"{f.expected:,}" if f.expected is not None else "None"
        act_str = f"{f.actual:,}" if f.actual is not None else "None"
        diff_str = f"{f.diff:,}" if f.diff is not None else "None"
        print(f"  [FAIL] {f.name}: exp={exp_str} act={act_str} diff={diff_str}")
