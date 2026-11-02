import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cv2
from app.core import storage
from app.core.model import Col

con = storage.open_db("Du_lieu_phien/phien.sqlite")
files = con.execute("SELECT path FROM files WHERE path LIKE '%2017%'").fetchall()
fr = storage.load_file_result(con, files[0][0])
p30 = fr.pages[29]
print("p30 grid_xs:", p30.grid_xs)

# Check col widths
for i in range(len(p30.grid_xs) - 1):
    w = p30.grid_xs[i+1] - p30.grid_xs[i]
    col_name = list(Col)[i].value
    print(f"Col {i} ({col_name}): x0={p30.grid_xs[i]}, x1={p30.grid_xs[i+1]}, width={w}")
