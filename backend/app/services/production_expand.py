from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import BomItem, GCodeFile, Product


@dataclass(frozen=True)
class BomLine:
    part_id: str
    part_sku: str
    quantity: int
    is_optional: bool


@dataclass(frozen=True)
class TaggedGCode:
    id: str
    part_id: str
    filename: str
    is_archived: bool
    production_approved: bool
    version: int


def expand_product_to_run_items(
    bom: list[BomLine],
    gcodes: list[TaggedGCode],
    product_qty: int,
    include_optional: bool = False,
) -> dict:
    """Turn a catalog BOM into production-run lines.

    Each non-archived G-code tagged to a printed BOM part becomes its own line so
    a part with two plates (different printers/profiles) both land on the run.
    Hardware BOM is a separate table and is never printed. Optional accessories
    are skipped unless include_optional is set.
    """
    qty = max(1, int(product_qty or 1))
    by_part: dict[str, list[TaggedGCode]] = {}
    for gcode in gcodes:
        if gcode.is_archived or not gcode.part_id:
            continue
        by_part.setdefault(gcode.part_id, []).append(gcode)
    for files in by_part.values():
        files.sort(key=lambda row: (not row.production_approved, -row.version, row.filename.lower()))

    items: list[dict] = []
    missing_gcode: list[str] = []
    optional_skipped: list[str] = []
    for line in bom:
        if line.is_optional and not include_optional:
            optional_skipped.append(line.part_sku)
            continue
        required = qty * max(1, int(line.quantity or 1))
        files = by_part.get(line.part_id) or []
        if not files:
            missing_gcode.append(line.part_sku)
            items.append(
                {
                    "part_id": line.part_id,
                    "part_sku": line.part_sku,
                    "gcode_file_id": None,
                    "gcode_filename": None,
                    "required_qty": required,
                    "optional": line.is_optional,
                }
            )
            continue
        for gcode in files:
            items.append(
                {
                    "part_id": line.part_id,
                    "part_sku": line.part_sku,
                    "gcode_file_id": gcode.id,
                    "gcode_filename": gcode.filename,
                    "required_qty": required,
                    "optional": line.is_optional,
                }
            )
    file_counts: dict[str, int] = {}
    for row in items:
        if row["gcode_file_id"]:
            file_counts[row["part_sku"]] = file_counts.get(row["part_sku"], 0) + 1
    return {
        "items": items,
        "missing_gcode": missing_gcode,
        "optional_skipped": optional_skipped,
        "multi_file_parts": [sku for sku, n in file_counts.items() if n > 1],
    }


async def run_items_for_product(
    db: AsyncSession,
    product_id: UUID,
    quantity: int = 1,
    include_optional: bool = False,
) -> dict:
    product = (
        await db.execute(
            select(Product)
            .options(selectinload(Product.bom_items).selectinload(BomItem.part))
            .where(Product.id == product_id)
        )
    ).scalar_one_or_none()
    if not product:
        return {}
    bom = [
        BomLine(
            part_id=str(item.part_id),
            part_sku=item.part.sku if item.part else str(item.part_id),
            quantity=item.quantity,
            is_optional=item.is_optional,
        )
        for item in product.bom_items
    ]
    part_ids = [item.part_id for item in product.bom_items]
    gcodes: list[TaggedGCode] = []
    if part_ids:
        rows = (
            await db.execute(select(GCodeFile).where(GCodeFile.part_id.in_(part_ids)))
        ).scalars().all()
        gcodes = [
            TaggedGCode(
                id=str(row.id),
                part_id=str(row.part_id) if row.part_id else "",
                filename=row.filename,
                is_archived=row.is_archived,
                production_approved=bool(row.production_approved),
                version=int(row.version or 1),
            )
            for row in rows
        ]
    expanded = expand_product_to_run_items(bom, gcodes, quantity, include_optional)
    expanded.update(
        {
            "product_id": str(product.id),
            "product_sku": product.sku,
            "product_name": product.name,
            "quantity": max(1, int(quantity or 1)),
        }
    )
    return expanded
