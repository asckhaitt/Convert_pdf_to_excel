import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import storage
from app.core.model import Col

con = storage.open_db("Du_lieu_phien/phien.sqlite")
files = con.execute("SELECT path FROM files WHERE path LIKE '%2015%'").fetchall()
fr = storage.load_file_result(con, files[0][0])
p9 = fr.pages[8] # 0-indexed 8

print("=== 2015 PAGE 9 ROWS ===")
print("Carry In: No=", p9.carry_in_no, "Co=", p9.carry_in_co)
print("Carry Out: No=", p9.carry_out_no, "Co=", p9.carry_out_co)
for r in p9.rows:
    desc = r.cell(Col.DIEN_GIAI).value or ""
    print(f"Row {r.row_index}: kind={r.kind.value} | CT={r.cell(Col.SO_CT).value} | raw_no='{r.cell(Col.PS_NO).raw}' val_no={r.amount_no} | raw_co='{r.cell(Col.PS_CO).raw}' val_co={r.amount_co} | Desc={desc[:35]}")
