import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cv2
from app.core import storage
from app.core.model import Col

con = storage.open_db("Du_lieu_phien/phien.sqlite")
files = con.execute("SELECT path FROM files WHERE path LIKE '%2015%'").fetchall()
fr = storage.load_file_result(con, files[0][0])
p10 = fr.pages[9]
img = cv2.imread(p10.image_path)
r12 = p10.rows[12]
rect = r12.cells[Col.PS_NO].rect
x0, y0, x1, y1 = int(rect.x0), int(rect.y0), int(rect.x1), int(rect.y1)
cell = img[y0:y1, x0:x1]
cv2.imwrite("tools/p10_r12_cell.png", cell)
print("Saved p10_r12_cell.png, shape:", cell.shape)
print("r12 desc:", r12.cell(Col.DIEN_GIAI).raw)
print("r12 raw_no:", r12.cell(Col.PS_NO).raw)
