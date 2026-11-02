import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import storage
from app.core.model import Col

con = storage.open_db("Du_lieu_phien/phien.sqlite")
files = con.execute("SELECT path FROM files").fetchall()

for (p,) in sorted(files):
    fr = storage.load_file_result(con, p)
    print("=" * 70)
    print("Book:", Path(p).name)
    for page in fr.pages:
        rows = [r for r in page.entry_rows()]
        for i in range(len(rows) - 1):
            r1, r2 = rows[i], rows[i+1]
            # Check if r1 and r2 form a pair (reverse accounts or same desc)
            tk1, tkdu1 = r1.cell(Col.TAI_KHOAN).value, r1.cell(Col.TK_DOI_UNG).value
            tk2, tkdu2 = r2.cell(Col.TAI_KHOAN).value, r2.cell(Col.TK_DOI_UNG).value
            same_desc = (r1.cell(Col.DIEN_GIAI).value == r2.cell(Col.DIEN_GIAI).value) if r1.cell(Col.DIEN_GIAI).value else False
            rev_tk = bool(tk1 and tk2 and tk1 == tkdu2 and tkdu1 == tk2)
            
            if (rev_tk or same_desc) and (r1.amount_no is not None or r2.amount_co is not None or r1.amount_co is not None or r2.amount_no is not None):
                a1 = r1.amount_no if r1.amount_no is not None else r1.amount_co
                a2 = r2.amount_co if r2.amount_co is not None else r2.amount_no
                if a1 != a2:
                    print(f"  P{page.page_index+1} R{r1.row_index+1}-R{r2.row_index+1}: a1={a1} vs a2={a2} | raw1='{r1.cell(Col.PS_NO).raw or r1.cell(Col.PS_CO).raw}' vs raw2='{r2.cell(Col.PS_CO).raw or r2.cell(Col.PS_NO).raw}' | CT='{r1.cell(Col.SO_CT).value}'/'{r2.cell(Col.SO_CT).value}' | Desc={r1.cell(Col.DIEN_GIAI).value[:25]}")
