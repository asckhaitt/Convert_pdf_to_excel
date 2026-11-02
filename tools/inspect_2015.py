import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import storage
from app.core.model import Col, RowKind
from app.core.reconcile import reconcile_file

con = storage.open_db("Du_lieu_phien/phien.sqlite")
files = con.execute("SELECT path FROM files WHERE path LIKE '%2015%'").fetchall()
fr = storage.load_file_result(con, files[0][0])
reconcile_file(fr)

print("=== 2015 DISCREPANCIES ===")
diff = fr.total_no() - fr.total_co()
print(f"Total Diff: {diff:,}")

# Find which pages have diff between sum_no and sum_co
for p in fr.pages:
    s_no = sum((r.amount_no or 0) for r in p.entry_rows())
    s_co = sum((r.amount_co or 0) for r in p.entry_rows())
    cin_no = p.carry_in_no or 0
    cin_co = p.carry_in_co or 0
    cout_no = p.carry_out_no or (p.grand_total_no or 0)
    cout_co = p.carry_out_co or (p.grand_total_co or 0)
    
    p_diff = s_no - s_co
    c_diff = (cin_no + s_no - cout_no) if cout_no else 0
    if p_diff != 0 or c_diff != 0:
        print(f"\nPage {p.page_index + 1} (printed: {p.printed_page}):")
        print(f"  Entry: s_no={s_no:,} | s_co={s_co:,} | diff={p_diff:,}")
        print(f"  Carry: in_no={cin_no:,} | out_no={cout_no:,} | in_co={cin_co:,} | out_co={cout_co:,}")
        for r in p.entry_rows():
            if (r.amount_no and r.amount_no > 100_000_000_000) or (r.amount_co and r.amount_co > 100_000_000_000):
                print(f"    BIG ROW: CT={r.cell(Col.SO_CT).value} | No={r.amount_no} | Co={r.amount_co} | Desc={r.cell(Col.DIEN_GIAI).value[:40]}")
