"""Khao sat nhanh cau truc PDF mau: text layer, font, kich thuoc, render anh."""
import sys
from pathlib import Path

import pymupdf

pdf_path = Path(sys.argv[1] if len(sys.argv) > 1 else r"D:\Project\Convert_pdf_to_excel\PDF file\SO NKC 2015 CTY NGOC HA.pdf")
out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(r"D:\Project\Convert_pdf_to_excel\.scratch")
out_dir.mkdir(parents=True, exist_ok=True)

doc = pymupdf.open(pdf_path)
print("file:", pdf_path.name)
print("pages:", doc.page_count)
print("metadata:", doc.metadata)

for i in [0, 1, doc.page_count // 2, doc.page_count - 1]:
    page = doc[i]
    text = page.get_text("text")
    words = page.get_text("words")
    imgs = page.get_images(full=True)
    drawings = page.get_drawings()
    print(f"\n--- page index {i} | rect={page.rect} | rotation={page.rotation} ---")
    print("chars:", len(text), "| words:", len(words), "| images:", len(imgs), "| drawings:", len(drawings))
    print("first 1200 chars of text layer:")
    print(text[:1200])
    pix = page.get_pixmap(dpi=150)
    pix.save(out_dir / f"page_{i}.png")
    print("saved:", out_dir / f"page_{i}.png", pix.width, "x", pix.height)

doc.close()
