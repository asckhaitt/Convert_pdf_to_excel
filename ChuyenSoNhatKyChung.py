"""Khởi động ứng dụng đã đóng gói (PyInstaller lấy file này làm điểm vào)."""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# Vô hiệu hóa module pymupdf.layout để tránh lỗi thiếu file ONNX yaml trong PyInstaller bundle
sys.modules["pymupdf.layout"] = None

# Đảm bảo thư mục app có trong sys.path
ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

log_file = ROOT / "nhat_ky_khoi_dong.log"

def log(msg: str):
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

def _cleanup_orphaned_mei():
    try:
        import shutil, tempfile
        cur_mei = getattr(sys, "_MEIPASS", None)
        t_dir = Path(tempfile.gettempdir())
        for p in t_dir.glob("_MEI*"):
            if cur_mei and str(p.resolve()) == str(Path(cur_mei).resolve()):
                continue
            shutil.rmtree(p, ignore_errors=True)
        for p in t_dir.glob("csnkc_ocr_*"):
            shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass

log("=== KHỞI ĐỘNG ỨNG DỤNG ===")
log(f"sys.executable: {sys.executable}")
log(f"frozen: {getattr(sys, 'frozen', False)}")
_cleanup_orphaned_mei()

try:
    from app.main import main
    log("Import app.main thành công. Bắt đầu giao diện...")
    main()
    log("Ứng dụng thoát bình thường.")
except Exception as e:
    err = traceback.format_exc()
    log(f"LỖI CHƯƠNG TRÌNH:\n{err}")
    if "--selftest" not in sys.argv:
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            _app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "Lỗi ứng dụng", f"Ứng dụng gặp lỗi khi khởi động:\n\n{err}")
        except Exception:
            pass
    raise
