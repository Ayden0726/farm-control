from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AssemblyKit, FilamentProduct, FilamentSpool, HardwareItem, Order, PartBin, PrintJob, Printer, ProductionRun


def slug_part(text: str, max_len: int = 8) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", (text or "").upper())
    return (cleaned[:max_len] or "X").rstrip()


def size_code(weight_g: float) -> str:
    kg = float(weight_g or 0) / 1000.0
    if kg >= 0.95:
        if abs(kg - round(kg)) < 0.05:
            return f"{int(round(kg))}KG"
        return f"{kg:.1f}".replace(".", "P") + "KG"
    grams = int(round(weight_g or 0))
    return f"{grams}G"


def product_barcode_id(manufacturer: str, material: str, color: str, weight_g: float) -> str:
    """FarmOS-owned receiving code, e.g. FILT-SID-PETG-BLACK-3KG."""
    return "-".join(
        [
            "FILT",
            slug_part(manufacturer, 3),
            slug_part(material, 8),
            slug_part(color, 12),
            size_code(weight_g),
        ]
    )


def printer_public_code(name: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9]+", "-", (name or "PRINTER").upper()).strip("-")
    parts = [p for p in compact.split("-") if p][:4]
    return "PRN-" + "-".join(p[:8] for p in parts)[:28]


def bin_public_code(name: str, kind: str = "finished_part") -> str:
    prefix = "PBIN" if kind == "production" else "BIN"
    compact = re.sub(r"[^A-Za-z0-9]+", "-", (name or "BIN").upper()).strip("-")
    return f"{prefix}-{compact[:24]}"


async def unique_product_barcode(
    db: AsyncSession,
    manufacturer: str,
    material: str,
    color: str,
    weight_g: float,
    exclude_id=None,
) -> str:
    base = product_barcode_id(manufacturer, material, color, weight_g)
    code = base
    n = 2
    while True:
        stmt = select(FilamentProduct).where(FilamentProduct.barcode_id == code)
        if exclude_id is not None:
            stmt = stmt.where(FilamentProduct.id != exclude_id)
        exists = (await db.execute(stmt)).scalar_one_or_none()
        if not exists:
            return code
        code = f"{base}-{n}"
        n += 1


async def unique_public_code(db: AsyncSession, model, field: str, base: str) -> str:
    code = base
    n = 2
    while True:
        exists = (await db.execute(select(model).where(getattr(model, field) == code))).scalar_one_or_none()
        if not exists:
            return code
        code = f"{base}-{n}"
        n += 1


def parse_scan_payload(raw: str) -> tuple[str | None, str]:
    """Return (kind, token) from a QR URL, farmos: payload, or Code 128 value."""
    text = (raw or "").strip()
    if not text:
        return None, ""
    if "/scan/" in text:
        path = urlparse(text).path if "://" in text else text
        tail = path.split("/scan/", 1)[-1].strip("/")
        parts = tail.split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
    if text.lower().startswith("farmos:"):
        bits = text.split(":", 2)
        if len(bits) == 3:
            return bits[1], bits[2]
    upper = text.upper()
    if upper.startswith("FILT-"):
        return "product", text
    if upper.startswith("SPOOL-"):
        return "spool", text
    if upper.startswith("PRN-"):
        return "printer", text
    if upper.startswith("PBIN-") or upper.startswith("BIN-"):
        return "bin", text
    if upper.startswith("JOB-"):
        return "job", text
    if upper.startswith("ORDER-"):
        return "order", text
    if upper.startswith("BATCH-"):
        return "batch", text
    if upper.startswith("KIT-"):
        return "kit", text
    if upper.startswith("HW-"):
        return "hardware", text
    return None, text


async def resolve_code(db: AsyncSession, raw: str):
    kind, token = parse_scan_payload(raw)
    if not token:
        return None
    if kind in {None, "product"} or token.upper().startswith("FILT-"):
        product = (
            await db.execute(select(FilamentProduct).where(FilamentProduct.barcode_id == token))
        ).scalar_one_or_none()
        if product:
            return {"kind": "product", "row": product}
    if kind in {None, "spool"} or token.upper().startswith("SPOOL-"):
        spool = (
            await db.execute(
                select(FilamentSpool).where(
                    (FilamentSpool.public_code == token) | (FilamentSpool.qr_token == token)
                )
            )
        ).scalar_one_or_none()
        if spool:
            return {"kind": "spool", "row": spool}
    if kind in {None, "printer"} or token.upper().startswith("PRN-"):
        printer = (
            await db.execute(
                select(Printer).where((Printer.public_code == token) | (Printer.qr_token == token))
            )
        ).scalar_one_or_none()
        if printer:
            return {"kind": "printer", "row": printer}
    if kind in {None, "bin"}:
        bin_row = (
            await db.execute(
                select(PartBin).where((PartBin.public_code == token) | (PartBin.qr_token == token))
            )
        ).scalar_one_or_none()
        if bin_row:
            return {"kind": "bin", "row": bin_row}
    if kind in {None, "job"}:
        job = (
            await db.execute(
                select(PrintJob).where((PrintJob.qr_token == token))
            )
        ).scalar_one_or_none()
        if job:
            return {"kind": "job", "row": job}
    if kind in {None, "order"} or token.upper().startswith("ORDER-"):
        order = (
            await db.execute(select(Order).where((Order.public_code == token) | (Order.reference == token)))
        ).scalar_one_or_none()
        if order:
            return {"kind": "order", "row": order}
    if kind in {None, "batch"} or token.upper().startswith("BATCH-"):
        run = (
            await db.execute(select(ProductionRun).where(ProductionRun.batch_code == token))
        ).scalar_one_or_none()
        if run:
            return {"kind": "batch", "row": run}
    if kind in {None, "kit"} or token.upper().startswith("KIT-"):
        kit = (await db.execute(select(AssemblyKit).where(AssemblyKit.public_code == token))).scalar_one_or_none()
        if kit:
            return {"kind": "kit", "row": kit}
    if kind in {None, "hardware"} or token.upper().startswith("HW-"):
        hw = (
            await db.execute(
                select(HardwareItem).where(
                    (HardwareItem.public_code == token) | (HardwareItem.sku == token) | (HardwareItem.barcode == token)
                )
            )
        ).scalar_one_or_none()
        if hw:
            return {"kind": "hardware", "row": hw}
    return None
