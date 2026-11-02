"""PoC: nhận diện bảng + OCR theo ô (không dò toàn trang), in bảng trích xuất."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
import pymupdf

from app.core.table_detect import detect_grid, draw_debug
from app.core.ocr_engine import OcrEngine, has_ink
from app.core.model import COLUMN_ORDER, Col

LABEL = {
    Col.NGAY_HT: "Ngày HT", Col.NGAY_CT: "Ngày CT", Col.SO_CT: "Số CT",
    Col.DIEN_GIAI: "Diễn giải", Col.TAI_KHOAN: "TK", Col.TK_DOI_UNG: "TKĐƯ",
    Col.PS_NO: "Nợ", Col.PS_CO: "Có",
}


def render_page(pdf_path, page_index, dpi=300):
    doc = pymupdf.open(pdf_path)
    page = doc[page_index]
    pix = page.get_pixmap(dpi=dpi)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    doc.close()
    return img


def main():
    pdf = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "PDF file" / "SO NKC 2015 CTY NGOC HA.pdf")
    page_index = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    t0 = time.time()
    img = render_page(pdf, page_index, dpi=dpi)
    print(f"render {img.shape} in {time.time()-t0:.1f}s")

    t0 = time.time()
    grid = detect_grid(img)
    print(f"grid: cols={grid.n_cols} rows={grid.n_rows} skew={grid.skew_deg:.2f} in {time.time()-t0:.1f}s")
    if grid.n_cols != 8:
        print("xs:", [round(x) for x in grid.xs])
        print("ys:", [round(y) for y in grid.ys])
        return

    t0 = time.time()
    eng = OcrEngine()
    print(f"engine ready in {time.time()-t0:.1f}s")

    t0 = time.time()
    table = []
    n_cells = 0
    for r in range(grid.n_rows):
        row = []
        for c in range(grid.n_cols):
            rect = grid.cell_rect(r, c)
            cell = img[int(rect.y0):int(rect.y1), int(rect.x0):int(rect.x1)]
            if not has_ink(cell):
                row.append("")
                continue
            n_cells += 1
            lines = eng.recognize_cell(cell)
            row.append("\n".join(t for t, _ in lines))
        table.append(row)
    print(f"ocr {n_cells} cells in {time.time()-t0:.1f}s")
    print()
    for r, row in enumerate(table):
        print(f"r{r:02d} | " + " | ".join(v.replace("\n", " / ") for v in row))

    dbg = draw_debug(img, grid)
    out = ROOT / ".scratch" / f"grid_p{page_index}.png"
    cv2.imwrite(str(out), dbg)
    print("debug:", out)


if __name__ == "__main__":
    main()
