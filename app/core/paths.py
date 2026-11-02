"""Thư mục dữ liệu phiên: cạnh file exe khi đóng gói, cạnh dự án khi chạy mã nguồn."""
from __future__ import annotations

import sys
from pathlib import Path


def data_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def session_root() -> Path:
    p = data_root() / "Du_lieu_phien"
    if getattr(sys, "frozen", False) and not (p / "phien.sqlite").exists():
        parent_p = data_root().parent / "Du_lieu_phien"
        if (parent_p / "phien.sqlite").exists():
            return parent_p
    return p