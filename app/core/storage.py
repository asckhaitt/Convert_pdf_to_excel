"""Lưu phiên xử lý bằng SQLite: dữ liệu trang, cảnh báo, lịch sử thao tác."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .model import (AccountingCheck, Col, CellValue, FileResult, FileStatus,
                    PageResult, Rect, RowKind, SourceRow, WarningItem, WarningLevel)

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  path TEXT PRIMARY KEY, sha256 TEXT, page_count INTEGER, status TEXT,
  accounting TEXT, processed_pages INTEGER, draft_excel TEXT, final_excel TEXT,
  updated_at TEXT);
CREATE TABLE IF NOT EXISTS pages(
  path TEXT, page_index INTEGER, data TEXT, PRIMARY KEY(path, page_index));
CREATE TABLE IF NOT EXISTS warnings(
  id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, code TEXT, message TEXT,
  level TEXT, page_index INTEGER, row_index INTEGER, col TEXT,
  resolved INTEGER, resolution TEXT);
CREATE TABLE IF NOT EXISTS history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, ts TEXT, action TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def _enc(o):
    if isinstance(o, Decimal):
        return {"__dec__": str(o)}
    if isinstance(o, date):
        return {"__date__": o.isoformat()}
    if isinstance(o, Rect):
        return {"__rect__": list(o.as_tuple())}
    if isinstance(o, Col):
        return {"__col__": o.value}
    if isinstance(o, RowKind):
        return {"__kind__": o.value}
    if isinstance(o, WarningLevel):
        return {"__level__": o.value}
    if isinstance(o, WarningItem):
        return {"__warn__": {
            "code": o.code, "message": o.message, "level": _enc(o.level),
            "page_index": o.page_index, "row_index": o.row_index,
            "col": _enc(o.col) if o.col else None,
            "resolved": o.resolved, "resolution": o.resolution, "wid": o.wid}}
    raise TypeError(type(o))


def _dec(d):
    if "__dec__" in d:
        return Decimal(d["__dec__"])
    if "__date__" in d:
        return date.fromisoformat(d["__date__"])
    if "__rect__" in d:
        return Rect(*d["__rect__"])
    if "__col__" in d:
        return Col(d["__col__"])
    if "__kind__" in d:
        return RowKind(d["__kind__"])
    if "__level__" in d:
        return WarningLevel(d["__level__"])
    if "__warn__" in d:
        w = d["__warn__"]
        return WarningItem(code=w["code"], message=w["message"], level=w["level"],
                           page_index=w["page_index"], row_index=w["row_index"],
                           col=w["col"], resolved=w["resolved"],
                           resolution=w["resolution"], wid=w["wid"])
    return d


def open_db(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    return con


def _page_to_json(p: PageResult) -> str:
    rows = []
    for r in p.rows:
        rows.append({
            "page_index": r.page_index, "row_index": r.row_index,
            "kind": r.kind, "rect": r.rect, "printed_page": r.printed_page,
            "merged_from": r.merged_from, "excluded_reason": r.excluded_reason,
            "confirmed": r.confirmed, "warnings": r.warnings,
            "cells": {c.value: {
                "raw": cv.raw, "value": cv.value, "rect": cv.rect,
                "confidence": cv.confidence, "source": cv.source,
                "reviewed": cv.reviewed, "confirmed": cv.confirmed,
                "edited": cv.edited, "original_value": cv.original_value,
                "warnings": cv.warnings} for c, cv in r.cells.items()},
        })
    return json.dumps({
        "page_index": p.page_index, "printed_page": p.printed_page,
        "carry_in_no": p.carry_in_no, "carry_in_co": p.carry_in_co,
        "carry_out_no": p.carry_out_no, "carry_out_co": p.carry_out_co,
        "grand_total_no": p.grand_total_no, "grand_total_co": p.grand_total_co,
        "has_carry_in_row": p.has_carry_in_row, "has_carry_out_row": p.has_carry_out_row,
        "has_grand_total_row": p.has_grand_total_row, "confirmed": p.confirmed,
        "info_page": p.info_page,
        "image_path": p.image_path, "warnings": p.warnings, "rows": rows,
    }, default=_enc, ensure_ascii=False)


def _page_from_json(s: str) -> PageResult:
    d = json.loads(s, object_hook=_dec)
    p = PageResult(page_index=d["page_index"], printed_page=d["printed_page"])
    for k in ("carry_in_no", "carry_in_co", "carry_out_no", "carry_out_co",
              "grand_total_no", "grand_total_co", "has_carry_in_row",
              "has_carry_out_row", "has_grand_total_row", "confirmed", "image_path"):
        setattr(p, k, d[k])
    p.info_page = bool(d.get("info_page", False))
    p.warnings = d["warnings"]
    for rd in d["rows"]:
        r = SourceRow(page_index=rd["page_index"], row_index=rd["row_index"],
                      kind=rd["kind"], rect=rd["rect"], printed_page=rd["printed_page"],
                      merged_from=rd["merged_from"], excluded_reason=rd["excluded_reason"],
                      confirmed=rd["confirmed"], warnings=rd["warnings"])
        for cval, cd in rd["cells"].items():
            col = Col(cval)
            r.cells[col] = CellValue(col=col, raw=cd["raw"], value=cd["value"],
                                     rect=cd["rect"], confidence=cd["confidence"],
                                     source=cd["source"], reviewed=cd["reviewed"],
                                     confirmed=cd["confirmed"], edited=cd["edited"],
                                     original_value=cd["original_value"],
                                     warnings=cd["warnings"])
        p.rows.append(r)
    return p


def save_file_result(con, fr: FileResult):
    con.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?,?,?)",
                (fr.path, fr.sha256, fr.page_count, fr.status.value, fr.accounting.value,
                 fr.processed_pages, fr.draft_excel, fr.final_excel,
                 datetime.now().isoformat(timespec="seconds")))
    for p in fr.pages:
        con.execute("INSERT OR REPLACE INTO pages VALUES(?,?,?)",
                    (fr.path, p.page_index, _page_to_json(p)))
    con.execute("DELETE FROM warnings WHERE path=?", (fr.path,))
    for w in fr.warnings:
        con.execute("INSERT INTO warnings(path,code,message,level,page_index,row_index,col,resolved,resolution) VALUES(?,?,?,?,?,?,?,?,?)",
                    (fr.path, w.code, w.message, w.level.value, w.page_index, w.row_index,
                     w.col.value if w.col else None, int(w.resolved), w.resolution))
    con.commit()


def load_file_result(con, path: str):
    row = con.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()
    if not row:
        return None
    fr = FileResult(path=row[0], sha256=row[1], page_count=row[2],
                    status=FileStatus(row[3]), accounting=AccountingCheck(row[4]),
                    processed_pages=row[5], draft_excel=row[6] or "", final_excel=row[7] or "")
    fr.pages = [_page_from_json(r[2]) for r in con.execute(
        "SELECT * FROM pages WHERE path=? ORDER BY page_index", (path,))]
    fr.warnings = [WarningItem(code=r[2], message=r[3], level=WarningLevel(r[4]),
                               page_index=r[5], row_index=r[6],
                               col=Col(r[7]) if r[7] else None,
                               resolved=bool(r[8]), resolution=r[9] or "", wid=r[0])
                   for r in con.execute("SELECT * FROM warnings WHERE path=? ORDER BY id", (path,))]
    return fr


def add_history(con, path: str, action: str, detail: str):
    con.execute("INSERT INTO history(path,ts,action,detail) VALUES(?,?,?,?)",
                (path, datetime.now().isoformat(timespec="seconds"), action, detail))
    con.commit()


def list_files(con):
    return [r[0] for r in con.execute("SELECT path FROM files ORDER BY updated_at")]


def get_meta(con, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(con, key: str, value: str):
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, value))
    con.commit()
