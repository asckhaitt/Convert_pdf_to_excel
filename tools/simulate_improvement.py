import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import re
from decimal import Decimal
from app.core import storage
from app.core.model import Col, RowKind
from app.core.normalize import parse_amount as orig_parse_amount
from app.core.reconcile import reconcile_file
from app.core.intelligent_reconcile import auto_reconcile_and_repair

def improved_parse_amount(raw: str, col: Col, page: int, row: int):
    val, warns = orig_parse_amount(raw, col, page, row)
    if val is not None:
        return val, warns
    
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    if not lines:
        return None, warns
    s = lines[0].replace(" ", "").strip(".,:;~_=- \t")
    if s and s[-1] in "()CcOoD":
        s = s[:-1] + "0"
    
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
        
    groups = re.split(r"[,.]", s)
    if len(groups) >= 2 and all(g.isdigit() for g in groups):
        if len(groups) >= 2 and all(len(g) == 3 for g in groups[1:-1]) and len(groups[0]) in (1, 2, 3):
            last_g = groups[-1]
            if len(last_g) in (1, 2) and all(ch == '0' for ch in last_g):
                padded = "".join(groups[:-1]) + last_g.ljust(3, "0")
                val = Decimal(padded)
                if neg:
                    val = -val
                return val, []
    return None, warns

con = storage.open_db("Du_lieu_phien/phien.sqlite")
files = con.execute("SELECT path FROM files").fetchall()

for (p,) in sorted(files):
    fr = storage.load_file_result(con, p)
    for page in fr.pages:
        for r in page.rows:
            if r.kind != RowKind.ENTRY:
                continue
            for c in (Col.PS_NO, Col.PS_CO):
                cell = r.cell(c)
                if cell.value is None and cell.raw and any(ch.isdigit() for ch in cell.raw):
                    new_val, _ = improved_parse_amount(cell.raw, c, page.page_index, r.row_index)
                    if new_val is not None:
                        cell.value = new_val
    
    # Run auto_reconcile_and_repair + reconcile_file
    auto_reconcile_and_repair(fr)
    reconcile_file(fr)
    
    diff = fr.total_no() - fr.total_co()
    recon_fail = [it for it in fr.reconcile if not it.ok]
    print("=" * 70)
    print(f"File: {Path(p).name}")
    print(f"Total No: {fr.total_no():,} | Total Co: {fr.total_co():,} | Diff: {diff:,}")
    print(f"Reconcile failed: {len(recon_fail)} / {len(fr.reconcile)}")
    for it in recon_fail[:6]:
        diff_str = f"{it.diff:,}" if it.diff is not None else "None"
        print(f"  [FAIL] {it.name}: diff={diff_str}")
