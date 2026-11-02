# -*- mode: python ; coding: utf-8 -*-
"""Đóng gói one-file: nhúng Tesseract + model vie/eng, chạy offline hoàn toàn."""
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "ChuyenSoNhatKyChung.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "packaging" / "tesseract"), "tesseract"),
        (str(ROOT / "packaging" / "app_icon.ico"), "."),
        (str(ROOT / "packaging" / "app_icon.png"), "."),
    ],
    hiddenimports=[
        "app",
        "app.main",
        "app.version",
        "app.core",
        "app.core.classify",
        "app.core.excel_export",
        "app.core.extract",
        "app.core.intelligent_reconcile",
        "app.core.model",
        "app.core.normalize",
        "app.core.ocr_engine",
        "app.core.paths",
        "app.core.pipeline",
        "app.core.reconcile",
        "app.core.storage",
        "app.core.table_detect",
        "app.gui",
        "app.gui.help_dialog",
        "app.gui.image_view",
        "app.gui.main_window",
        "app.gui.review_window",
        "app.gui.worker",
        "openpyxl",
        "openpyxl.styles",
        "openpyxl.utils",
        "pymupdf",
        "fitz",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["paddle", "paddleocr", "tkinter", "matplotlib", "scipy", "IPython", "pytest", "pymupdf.layout"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ChuyenSoNhatKyChung",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "packaging" / "app_icon.ico"),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
