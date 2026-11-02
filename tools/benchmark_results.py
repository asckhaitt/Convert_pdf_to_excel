import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import storage
from app.core.intelligent_reconcile import auto_reconcile_and_repair
from app.core.reconcile import reconcile_file

con = storage.open_db("Du_lieu_phien/phien.sqlite")
files = con.execute("SELECT path FROM files").fetchall()

print("=" * 80)
print(f"{'FILE':<32} | {'TOTAL NO':<20} | {'TOTAL CO':<20} | {'DIFF (VND)':<18} | {'RECON FAIL'}")
print("=" * 80)

for (p,) in sorted(files):
    fr = storage.load_file_result(con, p)
    auto_reconcile_and_repair(fr)
    reconcile_file(fr)
    
    diff = fr.total_no() - fr.total_co()
    recon_fail = [it for it in fr.reconcile if not it.ok]
    name = Path(p).name
    print(f"{name:<32} | {fr.total_no():>18,} | {fr.total_co():>18,} | {diff:>16,} | {len(recon_fail):>3}/{len(fr.reconcile)}")
    warn_by_code = {}
    for w in fr.warnings:
        warn_by_code[w.code] = warn_by_code.get(w.code, 0) + 1
    unbalanced_ct = warn_by_code.get("CHUNG_TU_KHONG_CAN", 0)
    cong_thuc_lech = warn_by_code.get("CONG_THUC_LECH", 0)
    print(f"   -> CHUNG_TU_KHONG_CAN: {unbalanced_ct} | CONG_THUC_LECH: {cong_thuc_lech}")

print("=" * 80)
