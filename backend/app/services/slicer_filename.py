"""Readable G-code names. Metadata still lives in the database."""

from __future__ import annotations

import re
from pathlib import Path


_SAFE = re.compile(r"[^A-Za-z0-9]+")


def slug(value: str, fallback: str = "part", max_len: int = 40) -> str:
    cleaned = _SAFE.sub("-", (value or "").strip()).strip("-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return (cleaned or fallback)[:max_len]


def sanitise_upload_name(filename: str, suffix: str = ".stl") -> str:
    stem = Path(filename or "model").stem
    ext = Path(filename or "").suffix.lower()
    if suffix == ".stl" and ext not in {".stl"}:
        ext = ".stl"
    if suffix == ".gcode" and ext not in {".gcode", ".gco", ".g"}:
        ext = ".gcode"
    if not ext:
        ext = suffix
    return slug(stem, "model", 80) + ext.lower()


def printer_token(name: str | None) -> str:
    """Compact printer token: 'Bay-02 K1 Max' → 'K1Max'."""
    text = (name or "printer").strip()
    text = re.sub(r"^(bay|slot|printer)[-_\s]*\d+\s+", "", text, flags=re.IGNORECASE)
    compact = re.sub(r"[^A-Za-z0-9]+", "", text)
    return (compact or slug(name or "printer", "printer", 24))[:24]


def sliced_gcode_filename(
    sku: str | None,
    part_name: str | None,
    quantity: int,
    printer_name: str | None,
    version: int,
) -> str:
    """e.g. RK-FR5-Handle-x12-K1Max-v3.gcode"""
    head = slug(sku or "", "") or slug(part_name or "", "part")
    printer = printer_token(printer_name)
    qty = max(1, int(quantity or 1))
    ver = max(1, int(version or 1))
    return f"{head}-x{qty}-{printer}-v{ver}.gcode"
