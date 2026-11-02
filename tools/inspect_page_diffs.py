import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import storage
from app.core.model import Col, RowKind

con = storage.open_db("Du_lieu_phien/phien.sqlite")

def inspect_discrepancies(filename):
    print("=" * 80)
    print(f"ANALYZING: {filename}")
    files = con.execute("SELECT path FROM files WHERE path LIKE ?", (f"%{filename}%",)).fetchall()
    if not files:
        print("Not found!")
        return
    fr = storage.load_file_result(con, files[0][0])
    
    for p in fr.pages:
        # Check carry in / out
        cin_no, cin_co = p.carry_in_no, p.carry_in_co
        cout_no, cout_co = p.carry_out_no, p.carry_out_co
        gt_no, gt_co = p.grand_total_no, p.grand_total_co
        
        sum_no = sum((r.amount_no or 0) for r in p.entry_rows())
        sum_co = sum((r.amount_co or 0) for r in p.entry_rows())
        
        target_out_no = cout_no if cout_no is not None else gt_no
        target_out_co = cout_co if cout_co is not None else gt_co
        
        calc_out_no = (cin_no or 0) + sum_no
        calc_out_co = (cin_co or 0) + sum_co
        
        diff_no = (calc_out_no - target_out_no) if target_out_no is not None else None
        diff_co = (calc_out_co - target_out_co) if target_out_co is not None else None
        
        if (diff_no is not None and diff_no != 0) or (diff_co is not None and diff_co != 0):
            print(f"\n--- Page {p.page_index + 1} (printed: {p.printed_page}) ---")
            print(f"  Carry In:  No={cin_no:,} | Co={cin_co:,}" if cin_no or cin_co else "  Carry In: None")
            print(f"  Sum Entry: No={sum_no:,} | Co={sum_co:,}")
            print(f"  Calc Out:  No={calc_out_no:,} | Co={calc_out_co:,}")
            print(f"  Target Out:No={target_out_no:,} | Co={target_out_co:,}" if target_out_no or target_out_co else "  Target Out: None")
            print(f"  Diff:      No={diff_no} | Co={diff_co}")
            
            # Print carry rows and grand total rows
            for r in p.rows:
                if r.kind in (RowKind.CARRY_IN, RowKind.CARRY_OUT, RowKind.GRAND_TOTAL):
                    print(f"    [{r.kind.value}] raw_no='{r.cell(Col.PS_NO).raw}' val_no={r.amount_no} | raw_co='{r.cell(Col.PS_CO).raw}' val_co={r.amount_co} | raw_text='{r.cell(Col.DIEN_GIAI).raw}'")
            
            # Print entry rows where amount is large or unbalanced
            print("    Entries on this page:")
            for r in p.entry_rows():
                v = r.cell(Col.SO_CT).value
                desc = r.cell(Col.DIEN_GIAI).value
                no = r.amount_no
                co = r.amount_co
                tk = r.cell(Col.TAI_KHOAN).value
                tkdu = r.cell(Col.TK_DOI_UNG).value
                print(f"      Row {r.row_index+1}: CT={v} | TK={tk}->{tkdu} | No={no} (raw='{r.cell(Col.PS_NO).raw}') | Co={co} (raw='{r.cell(Col.PS_CO).raw}') | Desc={desc[:30] if desc else ''}")

if __name__ == "__main__":
    inspect_discrepancies("2017")
    inspect_discrepancies("2018")
    inspect_discrepancies("2015")
