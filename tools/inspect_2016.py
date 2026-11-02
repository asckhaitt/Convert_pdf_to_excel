import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import storage
from app.core.model import Col, RowKind

con = storage.open_db("Du_lieu_phien/phien.sqlite")
files = con.execute("SELECT path FROM files WHERE path LIKE '%2016%'").fetchall()
fr = storage.load_file_result(con, files[0][0])

from app.core.reconcile import reconcile_file
reconcile_file(fr)
ct_warns = [w for w in fr.warnings if w.code == "CHUNG_TU_KHONG_CAN"]
print("Total CHUNG_TU_KHONG_CAN:", len(ct_warns))
for w in ct_warns[:20]:
    print("  -", w.message)

