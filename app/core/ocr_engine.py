"""OCR tiếng Việt theo vùng ô bằng Tesseract (vie).

PaddleOCR (v5/v6) không có ký tự tiếng Việt trong từ điển nên không dùng được
cho diễn giải; Tesseract với tessdata vie đọc đúng dấu và đóng gói offline gọn.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

WHITELIST = {
    "text": None,
    "date": "0123456789/",
    "money": "0123456789.,()-",
    "code": "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./-",
    "account": "0123456789",
    "account_alt": "0123456789",
}
# psm 6 (khối văn bản đồng nhất) nhận diện tốt văn bản nhiều dòng và mã nhiều dòng
PSM = {"text": 6, "date": 7, "money": 7, "code": 6, "account": 7, "account_alt": 6}
# chữ số có chân (serif) bị model vie đọc thành chữ cái; số chứng từ/ngày/tài khoản/tiền dùng eng
LANG_FOR = {"account": "eng", "account_alt": "eng", "code": "eng", "date": "eng", "money": "eng"}


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def tesseract_paths():
    root = app_root()
    exe = os.environ.get("CSNKC_TESSERACT")
    if exe:
        exe = Path(exe)
        data = Path(os.environ.get("CSNKC_TESSDATA", exe.parent.parent / "share" / "tessdata"))
        return exe, data
    if getattr(sys, "frozen", False):
        return root / "tesseract" / "tesseract.exe", root / "tesseract" / "tessdata"
    return (root / ".runtime" / "tessenv" / "Library" / "bin" / "tesseract.exe",
            root / ".runtime" / "tessenv" / "share" / "tessdata")


def ink_mask(img: np.ndarray) -> np.ndarray:
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                 cv2.THRESH_BINARY_INV, 25, 12)


def clean_borders(cell: np.ndarray) -> np.ndarray:
    """Xóa đường kẻ viền ô (cột/hàng phủ gần hết chiều cao/rộng)."""
    bw = ink_mask(cell)
    h, w = bw.shape
    out = cell.copy()
    colcov = bw.sum(axis=0) / 255.0 / max(h, 1)
    rowcov = bw.sum(axis=1) / 255.0 / max(w, 1)
    edge_x = min(8, w // 4)
    edge_y = min(8, h // 4)
    for x in range(w):
        thr = 0.60 if (x < edge_x or x >= w - edge_x) else 0.88
        if colcov[x] > thr:
            out[:, x] = 255
    for y in range(h):
        thr = 0.60 if (y < edge_y or y >= h - edge_y) else 0.88
        if rowcov[y] > thr:
            out[y, :] = 255
    return out


def split_lines(cell: np.ndarray, min_gap: int = 0, min_h: int = 10,
                pad_x: int = 3, pad_y: int = 2, inset: int = 2):
    """Tách các dòng chữ trong một ô bằng khoảng trống theo chiều dọc."""
    h0, w0 = cell.shape[:2]
    if h0 <= 2 * inset + 4 or w0 <= 2 * inset + 4:
        return []
    cell = clean_borders(cell[inset:h0 - inset, inset:w0 - inset])
    bw = ink_mask(cell)
    h, w = bw.shape
    prof = bw.sum(axis=1) / 255.0
    rows = prof > max(1.0, w * 0.01)
    spans = []
    y = 0
    while y < len(rows):
        if rows[y]:
            y0 = y
            while y < len(rows) and rows[y]:
                y += 1
            spans.append([y0, y])
        else:
            y += 1
    merged = []
    for s in spans:
        if merged and s[0] - merged[-1][1] < min_gap:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    out = []
    for y0, y1 in merged:
        if y1 - y0 < min_h:
            continue
        a = max(0, y0 - pad_y)
        b = min(h, y1 + pad_y)
        strip = bw[a:b, :]
        cols = strip.sum(axis=0) / 255.0
        xs = np.nonzero(cols > 0)[0]
        if len(xs) == 0:
            continue
        while len(xs) > 1 and xs[1] - xs[0] > 15 and (xs[0] <= 4 or cols[xs[0]] <= 2):
            xs = xs[1:]
        while len(xs) > 1 and xs[-1] - xs[-2] > 15 and (xs[-1] >= w - 5 or cols[xs[-1]] <= 2):
            xs = xs[:-1]
        x0 = max(0, int(xs[0]) - pad_x)
        x1 = min(w, int(xs[-1]) + 1 + pad_x)
        out.append(cell[a:b, x0:x1])
    return out


def has_ink(cell: np.ndarray, thresh: float = 0.004, inset: int = 6) -> bool:
    h0, w0 = cell.shape[:2]
    if h0 <= 2 * inset + 4 or w0 <= 2 * inset + 4:
        return False
    bw = ink_mask(clean_borders(cell[inset:h0 - inset, inset:w0 - inset]))
    return bw.mean() / 255.0 > thresh


class OcrEngine:
    """Nhận dạng từng dòng chữ bằng Tesseract vie, một tiến trình cho cả lô."""

    def __init__(self, lang: str = "vie", psm: int = 7, upscale: int = 1):
        self.exe, self.data = tesseract_paths()
        if not self.exe.exists():
            raise FileNotFoundError(f"Không tìm thấy Tesseract: {self.exe}")
        self.lang = lang
        self.psm = psm
        self.upscale = upscale
        self.model_name = f"tesseract-{lang}"

    def recognize(self, line_imgs: list, mode: str = "text") -> list:
        if not line_imgs:
            return []
        env = dict(os.environ, TESSDATA_PREFIX=str(self.data))
        try:
            from .paths import session_root
            td_parent_path = session_root() / "temp"
            td_parent_path.mkdir(parents=True, exist_ok=True)
            td_parent = str(td_parent_path)
        except Exception:
            td_parent = None

        with tempfile.TemporaryDirectory(dir=td_parent, prefix="csnkc_ocr_") as td:
            td = Path(td)
            paths = []
            upscale = 1 if mode in ("text", "code") else self.upscale
            for i, im in enumerate(line_imgs):
                if upscale > 1:
                    im = cv2.resize(im, None, fx=upscale, fy=upscale,
                                    interpolation=cv2.INTER_CUBIC)
                border_val = [255, 255, 255] if im.ndim == 3 else 255
                pad_y = min(6, max(3, im.shape[0] // 4))
                pad_x = min(8, max(4, im.shape[1] // 4))
                im = cv2.copyMakeBorder(im, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_CONSTANT, value=border_val)
                p = td / f"l{i:04d}.png"
                cv2.imwrite(str(p), im)
                paths.append(p)
            lst = td / "list.txt"
            lst.write_text("\n".join(str(p) for p in paths), encoding="utf-8")
            cmd = [str(self.exe), str(lst), str(td / "out"), "-l",
                   LANG_FOR.get(mode, self.lang), "--psm", str(PSM.get(mode, self.psm))]
            wl = WHITELIST.get(mode)
            if wl:
                cmd += ["-c", f"tessedit_char_whitelist={wl}"]
            extra_kw = {}
            if os.name == "nt":
                extra_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                extra_kw["startupinfo"] = startupinfo
            proc = subprocess.run(cmd, env=env, capture_output=True, timeout=600, **extra_kw)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:400])
            raw = (td / "out.txt").read_text(encoding="utf-8", errors="replace")
            pages = raw.split("\f")
            out = []
            for i in range(len(paths)):
                s = pages[i].strip() if i < len(pages) else ""
                out.append((s, 1.0 if s else 0.0))
            return out

    def recognize_cell(self, cell: np.ndarray, mode: str = "text") -> list:
        lines = split_lines(cell)
        if not lines:
            return []
        return self.recognize(lines, mode=mode)
