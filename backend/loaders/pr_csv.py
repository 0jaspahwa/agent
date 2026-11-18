"""Parse a PR batch CSV (sample format) into typed values. Used by the kit loader and by batch ingestion.

Forgiving by design (D17): a byte-order mark, either line ending, columns in any order, extra columns,
header names in any case with stray spaces, and blank rows are all accepted; every cell is trimmed.
Timestamps may have seconds and a "T" or a space. A blank or unreadable cell becomes None and the
policy's line checks report the line as NOT_PROCESSED; it is never dropped. The whole batch is rejected
only when a required column is missing altogether.
"""
import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

REQUIRED = ["pr_no", "pr_line", "created_at", "plant", "description", "quantity", "need_by_date"]
OPTIONAL = ["requester", "department", "item_code", "uom", "estimated_unit_price", "urgency"]
COLUMNS = REQUIRED[:3] + ["requester", "department", "plant", "item_code", "description", "quantity", "uom",
                          "estimated_unit_price", "need_by_date", "urgency"]  # the sample batch's order


class BatchFormatError(ValueError):
    pass


def _text(value):
    return value or None


def _decimal(value):
    try:
        return Decimal(value) if value else None
    except InvalidOperation:
        return None


def _date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _datetime(value):
    try:
        return datetime.fromisoformat(value) if value else None  # "2026-11-04 12:40", "...T12:40:00"
    except ValueError:
        return None


def parse_pr_csv(csv_text):
    """[(raw row dict, typed field dict)] in file order. Typed fields match engine.inputs.PRLine."""
    # strict: a quoted field that is never closed would otherwise swallow the rest of the file silently
    reader = csv.reader(io.StringIO(csv_text.lstrip("﻿"), newline=""), strict=True)
    try:
        return _rows(reader)
    except csv.Error as exc:
        raise BatchFormatError(f"line {reader.line_num} is not valid CSV ({exc}); check for a quote that is "
                               f"opened and never closed") from exc


def _rows(reader):
    header = [h.strip().lower() for h in next(reader, [])]
    if not any(header):
        raise BatchFormatError("the file is empty")
    index = {}
    for i, name in enumerate(header):
        index.setdefault(name, i)  # a repeated header name: the first column wins
    missing = [c for c in REQUIRED if c not in index]
    if missing:
        raise BatchFormatError(f"the batch is missing required column(s) {missing}; "
                               f"required: {REQUIRED}; optional: {OPTIONAL}")
    rows = []
    for cells in reader:
        cells = [c.strip() for c in cells]
        if not any(cells):
            continue  # blank row
        cell = {name: (cells[i] if i < len(cells) else "") for name, i in index.items()}
        get = lambda c: cell.get(c, "")  # noqa: E731  (an optional column may be absent)
        rows.append((cell, {
            "pr_no": get("pr_no"), "pr_line": get("pr_line"), "created_at": _datetime(get("created_at")),
            "requester": _text(get("requester")), "department": _text(get("department")),
            "plant": get("plant"), "item_code": _text(get("item_code")), "description": get("description"),
            "quantity": _decimal(get("quantity")), "uom": _text(get("uom")),
            "estimated_unit_price": _decimal(get("estimated_unit_price")),
            "need_by_date": _date(get("need_by_date")), "urgency": _text(get("urgency")),
        }))
    if not rows:
        raise BatchFormatError("the file has a header but no lines")
    return rows
