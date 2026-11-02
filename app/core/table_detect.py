"""Nhận diện khung bảng và ranh giới ô bằng OpenCV."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .model import Rect


@dataclass
class Grid:
    xs: list = field(default_factory=list)      # ranh giới cột (px ảnh)
    ys: list = field(default_factory=list)      # ranh giới dòng (px ảnh)
    table: Rect = None
    skew_deg: float = 0.0
    solid_rows: list = field(default_factory=list)
    debug: dict = field(default_factory=dict)

    @property
    def n_cols(self):
        return max(0, len(self.xs) - 1)

    @property
    def n_rows(self):
        return max(0, len(self.ys) - 1)

    def cell_rect(self, r, c) -> Rect:
        return Rect(self.xs[c], self.ys[r], self.xs[c + 1], self.ys[r + 1])


def to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def estimate_skew(gray: np.ndarray) -> float:
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=120,
                            minLineLength=gray.shape[1] // 3, maxLineGap=8)
    if lines is None:
        return 0.0
    angles = []
    for x0, y0, x1, y1 in lines[:, 0]:
        dx, dy = x1 - x0, y1 - y0
        if abs(dx) < 100:
            continue
        ang = np.degrees(np.arctan2(dy, dx))
        if abs(ang) < 5:
            angles.append(ang)
    if not angles:
        return 0.0
    med = float(np.median(angles))
    return med if abs(med) > 0.05 else 0.0


def rotate(img: np.ndarray, deg: float) -> np.ndarray:
    if abs(deg) < 0.01:
        return img
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def _cluster(vals, gap):
    vals = sorted(vals)
    out = []
    for v in vals:
        if out and v - out[-1][-1] <= gap:
            out[-1].append(v)
        else:
            out.append([v])
    return [float(np.mean(g)) for g in out]


def _prune_close(vals, scores, min_gap):
    """Bỏ ranh giới giả nằm sát ranh giới thật (vết kẻ đôi do scan)."""
    kept = []
    for v in sorted(vals):
        if kept and v - kept[-1] < min_gap:
            if scores.get(v, 0) > scores.get(kept[-1], 0):
                kept[-1] = v
            continue
        kept.append(v)
    return kept


def detect_grid(img: np.ndarray, expect_cols: int = 8, deskew: bool = True,
                fallback_xs: list | None = None) -> Grid:
    gray = to_gray(img)
    skew = estimate_skew(gray) if deskew else 0.0
    if skew:
        gray = rotate(gray, skew)
        img = rotate(img, skew) if img.ndim == 3 else gray

    h, w = gray.shape
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 31, 10)

    # đường kẻ ngang: nối nét đứt rồi giữ cấu trúc dài (k_len >= 350 để loại bỏ triệt để nét chữ, gạch chân hợp đồng)
    closed = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (11, 1)))
    horiz = cv2.morphologyEx(closed, cv2.MORPH_OPEN,
                             cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 7, 350), 1)))
    # đường dọc phải liền nét: không CLOSE dọc vì sẽ nối mép chữ thành kẻ giả
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 40, 30))))

    lines_mask = cv2.bitwise_or(horiz, vert)
    contours, _ = cv2.findContours(lines_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return Grid()
    biggest = max(contours, key=cv2.contourArea)
    tx, ty, tw, th = cv2.boundingRect(biggest)
    if tw < w * 0.35 or th < 120:
        return Grid()

    # ranh giới cột: đường dọc phủ phần lớn chiều cao bảng
    vproj = vert[ty:ty + th, :].sum(axis=0) / 255.0
    hproj = horiz[:, tx:tx + tw].sum(axis=1) / 255.0

    xs, ys = [], []
    best_v = None
    for thr_v in (0.50, 0.45, 0.40, 0.35, 0.30, 0.25, 0.20, 0.18, 0.15, 0.12, 0.10, 0.60, 0.70):
        cand = _cluster([x for x in range(tx, min(tx + tw + 1, len(vproj))) if vproj[x] > th * thr_v], 6)
        cand = _prune_close(cand, {v: vproj[int(v)] for v in cand}, max(tw // 40, 30))
        if best_v is None or abs(len(cand) - (expect_cols + 1)) < abs(len(best_v) - (expect_cols + 1)):
            best_v = cand
        if len(cand) == expect_cols + 1:
            best_v = cand
            break
    xs = best_v or xs

    if len(xs) != expect_cols + 1 and fallback_xs and len(fallback_xs) == expect_cols + 1:
        dx = tx - fallback_xs[0] if abs(tx - fallback_xs[0]) < 100 else 0
        xs = [x + dx for x in fallback_xs]

    min_gap = max(th // 60, 48)
    best_h = None
    for thr_h in (0.35, 0.30, 0.25, 0.20, 0.16, 0.12):
        cand = _cluster([y for y in range(ty, min(ty + th + 1, len(hproj))) if hproj[y] > tw * thr_h], 6)
        cand = _prune_close(cand, {v: hproj[int(v)] for v in cand}, min_gap)
        if len(cand) >= 4 and (best_h is None or len(cand) > len(best_h)):
            best_h = cand
    ys = best_h or ys

    # dòng kẻ chấm mờ: mật độ điểm ảnh đen theo hàng trong vùng bảng
    if len(ys) < 4:
        band = bw[:, tx + 5:tx + tw - 5]
        dens = band.sum(axis=1) / 255.0 / (tw - 10)
        cand = [y for y in range(ty, min(ty + th + 1, len(dens))) if dens[y] > 0.30]
        ys = _cluster(ys + cand, 4)

    if len(xs) < expect_cols + 1 or len(ys) < 3:
        return Grid(xs=xs, ys=ys, table=Rect(tx, ty, tx + tw, ty + th), skew_deg=skew)

    return Grid(xs=xs, ys=ys, table=Rect(tx, ty, tx + tw, ty + th),
                skew_deg=skew, solid_rows=ys,
                debug={"horiz_px": int(horiz.sum() / 255), "vert_px": int(vert.sum() / 255)})


def preprocess_for_ocr(img: np.ndarray) -> np.ndarray:
    """Tăng tương phản nhẹ, giảm nhiễu có kiểm soát; không nhị phân hóa mạnh."""
    gray = to_gray(img)
    den = cv2.fastNlMeansDenoising(gray, None, 6, 7, 21)
    clahe = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8))
    return clahe.apply(den)


def draw_debug(img: np.ndarray, grid: Grid) -> np.ndarray:
    out = img.copy() if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    for x in grid.xs:
        cv2.line(out, (int(x), 0), (int(x), out.shape[0]), (0, 0, 255), 1)
    for y in grid.ys:
        cv2.line(out, (0, int(y)), (out.shape[1], int(y)), (255, 0, 0), 1)
    if grid.table:
        t = grid.table
        cv2.rectangle(out, (int(t.x0), int(t.y0)), (int(t.x1), int(t.y1)), (0, 200, 0), 2)
    return out
