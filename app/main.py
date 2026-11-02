"""Điểm khởi động ứng dụng Chuyển Sổ Nhật Ký Chung."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from .core.paths import data_root, session_root
from .version import APP_NAME, VERSION


def _selftest() -> int:
    """Kiểm tra môi trường chạy (dùng cho bản đóng gói): ghi Du_lieu_phien/selftest.txt."""
    lines = [f"{APP_NAME} {VERSION}",
             f"frozen={bool(getattr(sys, 'frozen', False))}",
             f"python={sys.version.split()[0]}",
             f"executable={sys.executable}",
             f"data_root={data_root()}"]
    ok = True
    for name in ("PySide6", "pymupdf", "cv2", "openpyxl", "numpy"):
        try:
            if name == "pymupdf":
                try:
                    import pymupdf as mod
                except ImportError:
                    import fitz as mod
            else:
                mod = __import__(name)
            lines.append(f"module {name}={getattr(mod, '__version__', 'ok')}")
        except Exception as exc:
            ok = False
            lines.append(f"module {name}=LOI {exc}")
    try:
        from .core.ocr_engine import tesseract_paths
        exe, data = tesseract_paths()
        vie = (data / "vie.traineddata").exists()
        eng = (data / "eng.traineddata").exists()
        lines.append(f"tesseract_exe={exe} exists={exe.exists()}")
        lines.append(f"tessdata={data} vie={vie} eng={eng}")
        ok = ok and exe.exists() and vie and eng
        if exe.exists():
            extra_kw = {}
            if os.name == "nt":
                extra_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            r = subprocess.run([str(exe), "--version"], capture_output=True, text=True,
                               timeout=60, env=dict(os.environ, TESSDATA_PREFIX=str(data)), **extra_kw)
            first = (r.stdout or r.stderr).splitlines()[:1]
            lines.append(f"tesseract_version={first}")
            ok = ok and r.returncode == 0
    except Exception as exc:
        ok = False
        lines.append(f"tesseract=LOI {exc}")
    lines.append("KET_QUA=" + ("DAT" if ok else "KHONG_DAT"))
    session_root().mkdir(parents=True, exist_ok=True)
    out = session_root() / "selftest.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print("\n".join(lines))
    except Exception:
        pass
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("csnkc.app.v1")
        except Exception:
            pass

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    session_root().mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(session_root() / "nhat_ky_ky_thuat.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    # Đặt icon ứng dụng
    icon_candidates = [
        data_root() / "packaging" / "app_icon.ico",
        data_root() / "packaging" / "app_icon.png",
        data_root() / "app_icon.ico",
        data_root() / "app_icon.png",
    ]
    if getattr(sys, "frozen", False):
        icon_candidates.insert(0, Path(sys._MEIPASS) / "app_icon.ico")
        icon_candidates.insert(1, Path(sys._MEIPASS) / "app_icon.png")
    for ic in icon_candidates:
        if ic.exists():
            app.setWindowIcon(QIcon(str(ic)))
            break

    win = MainWindow()
    for ic in icon_candidates:
        if ic.exists():
            win.setWindowIcon(QIcon(str(ic)))
            break
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
