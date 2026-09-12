from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AppSetting,
    DryingStatus,
    FilamentProduct,
    FilamentSpool,
    FilamentTransaction,
    IdSequence,
    PartBin,
    PrintJob,
    Printer,
    PurchaseOrder,
    PurchaseOrderLine,
    StorageLocation,
    Supplier,
    utcnow,
)
from app.services.barcodes import bin_public_code, printer_public_code, product_barcode_id, unique_public_code
from app.services.filament import DEFAULT_SPEND, audit, cost_per_kg, next_po_reference, next_spool_number, spool_code
from app.util import new_qr_token

LOCATIONS = [
    ("Filament Shelf A", "shelf"),
    ("Filament Shelf B", "shelf"),
    ("Black PETG Shelf", "shelf"),
    ("Sealed Stock", "sealed"),
    ("Open Stock", "open"),
    ("Dryer 1", "dryer"),
    ("Dryer 2", "dryer"),
]

SEED_CATALOG = [
    ("Siddament", "PETG", "Black", 3000),
    ("Siddament", "PETG", "Grey", 3000),
    ("Siddament", "PETG", "White", 3000),
    ("Siddament", "PETG", "Electric Blue", 3000),
    ("Sunlu", "PETG", "Black", 1000),
    ("eSun", "PLA", "Grey", 1000),
    ("Polymaker", "PETG", "Orange", 1000),
    ("eSun", "PETG", "White", 1000),
]
SEED_BARCODES = {product_barcode_id(*row) for row in SEED_CATALOG}
SEED_SKUS = {
    "SID-PETG-BLK-3",
    "SID-PETG-GRY-3",
    "SID-PETG-WHT-3",
    "SID-PETG-EBL-3",
    "SUN-PETG-BLK-1",
    "ESUN-PLA-GRY-1",
    "POLY-PETG-ORG-1",
    "ESUN-PETG-WHT-1",
}
SEED_SPOOL_NAMES = {
    "Sunlu PETG Black 1kg",
    "eSun PETG White 1kg",
    "Polymaker PETG Orange 1kg",
    "Sunlu PETG Black 1kg #2",
    "eSun PLA+ Grey 1kg",
}
DEMO_TX_NOTES = {"Demo receiving", "Historical usage from demo farm"}


async def clear_seeded_filament_inventory(db: AsyncSession) -> None:
    """One-time: drop auto-seeded demo rolls/profiles. Keep anything the shop received itself."""
    flag = await db.get(AppSetting, "cleared_seed_filament")
    if flag is not None:
        return

    spools = list(
        (
            await db.execute(select(FilamentSpool).options(selectinload(FilamentSpool.transactions)))
        ).scalars().all()
    )
    demo_ids: list = []
    for spool in spools:
        notes = {(tx.notes or "").strip() for tx in spool.transactions}
        if notes & DEMO_TX_NOTES or spool.name in SEED_SPOOL_NAMES:
            demo_ids.append(spool.id)
            continue
        product = await db.get(FilamentProduct, spool.product_id) if spool.product_id else None
        receive_notes = [(tx.notes or "") for tx in spool.transactions if tx.reason == "receive"]
        if product and (product.barcode_id in SEED_BARCODES or product.supplier_sku in SEED_SKUS):
            if receive_notes and all("Demo" in n or "demo farm" in n.lower() for n in receive_notes):
                demo_ids.append(spool.id)

    if demo_ids:
        printers = (await db.execute(select(Printer).where(Printer.assigned_spool_id.in_(demo_ids)))).scalars().all()
        for printer in printers:
            printer.assigned_spool_id = None
        jobs = (await db.execute(select(PrintJob).where(PrintJob.spool_id.in_(demo_ids)))).scalars().all()
        for job in jobs:
            job.spool_id = None
        await db.flush()
        await db.execute(delete(FilamentTransaction).where(FilamentTransaction.spool_id.in_(demo_ids)))
        await db.execute(delete(FilamentSpool).where(FilamentSpool.id.in_(demo_ids)))
        await db.flush()

    products = list((await db.execute(select(FilamentProduct))).scalars().all())
    leftover = {
        row.product_id
        for row in (await db.execute(select(FilamentSpool.product_id).where(FilamentSpool.product_id.is_not(None)))).all()
    }
    seed_product_ids = [
        p.id
        for p in products
        if (p.barcode_id in SEED_BARCODES or p.supplier_sku in SEED_SKUS) and p.id not in leftover
    ]
    if seed_product_ids:
        po_ids = [
            row[0]
            for row in (
                await db.execute(
                    select(PurchaseOrderLine.purchase_order_id).where(
                        PurchaseOrderLine.product_id.in_(seed_product_ids)
                    )
                )
            ).all()
        ]
        if po_ids:
            await db.execute(delete(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id.in_(po_ids)))
            await db.execute(delete(PurchaseOrder).where(PurchaseOrder.id.in_(po_ids)))
        await db.execute(delete(FilamentProduct).where(FilamentProduct.id.in_(seed_product_ids)))

    demo_pos = (
        await db.execute(select(PurchaseOrder).where(PurchaseOrder.reason.ilike("%Recommended 5 × 3 kg%")))
    ).scalars().all()
    if demo_pos:
        ids = [po.id for po in demo_pos]
        await db.execute(delete(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id.in_(ids)))
        await db.execute(delete(PurchaseOrder).where(PurchaseOrder.id.in_(ids)))

    db.add(AppSetting(key="cleared_seed_filament", value=True))
    await audit(db, "cleared_seed_filament", "filament", "inventory", {"removed_spools": len(demo_ids)})
    await db.flush()


async def ensure_filament_system(db: AsyncSession, *, demo_rich: bool = False) -> None:
    """Idempotent: spend controls, locations, public codes. Does not invent filament stock."""
    await clear_seeded_filament_inventory(db)
    spend = await db.get(AppSetting, "filament_spend")
    if spend is None:
        db.add(AppSetting(key="filament_spend", value=dict(DEFAULT_SPEND)))

    existing_loc = (await db.execute(select(StorageLocation).limit(1))).scalar_one_or_none()
    locations: dict[str, StorageLocation] = {}
    if existing_loc is None:
        for name, kind in LOCATIONS:
            loc = StorageLocation(name=name, kind=kind)
            db.add(loc)
            locations[name] = loc
        await db.flush()
    else:
        for loc in (await db.execute(select(StorageLocation))).scalars().all():
            locations[loc.name] = loc

    printers = (await db.execute(select(Printer))).scalars().all()
    for printer in printers:
        if not printer.public_code:
            printer.public_code = await unique_public_code(
                db, Printer, "public_code", printer_public_code(printer.name)
            )
        loc_name = printer.name
        if loc_name not in locations:
            loc = StorageLocation(name=loc_name, kind="printer", printer_id=printer.id)
            db.add(loc)
            await db.flush()
            locations[loc_name] = loc
        elif locations[loc_name].printer_id is None:
            locations[loc_name].printer_id = printer.id

    bins = (await db.execute(select(PartBin))).scalars().all()
    for bin_row in bins:
        if not bin_row.public_code:
            bin_row.public_code = await unique_public_code(
                db, PartBin, "public_code", bin_public_code(bin_row.name, bin_row.kind or "finished_part")
            )

    suppliers = {s.name: s for s in (await db.execute(select(Supplier))).scalars().all()}

    products = list((await db.execute(select(FilamentProduct))).scalars().all())

    by_key = {(p.manufacturer.lower(), p.material.lower(), p.color.lower(), round(p.filament_weight_g)): p for p in products}

    seq = await db.get(IdSequence, "spool")
    if seq is None:
        seq = IdSequence(name="spool", next_value=1)
        db.add(seq)
        await db.flush()

    spools = (await db.execute(select(FilamentSpool))).scalars().all()
    for spool in spools:
        if not spool.public_code:
            n = await next_spool_number(db)
            spool.public_code = spool_code(n)
        if not spool.product_id:
            key = (spool.manufacturer.lower(), spool.material.lower(), spool.color.lower(), round(spool.initial_weight_g))
            product = by_key.get(key)
            if product is None:
                for p in products:
                    if p.manufacturer.lower() == spool.manufacturer.lower() and p.material.lower() == spool.material.lower() and p.color.lower() == spool.color.lower():
                        product = p
                        break
            if product:
                spool.product_id = product.id
        if spool.cost_per_kg == 0 and spool.initial_weight_g:
            spool.cost_per_kg = cost_per_kg(spool.cost, spool.initial_weight_g)
        if spool.date_received is None:
            spool.date_received = spool.purchase_date or spool.created_at
        if spool.assigned_printer_id and spool.is_sealed:
            spool.is_sealed = False
            spool.date_opened = spool.date_opened or utcnow()
        if spool.consumed_g == 0 and spool.initial_weight_g:
            spool.consumed_g = max(0.0, spool.initial_weight_g - spool.remaining_weight_g)
        if spool.remaining_weight_g <= 0:
            spool.is_empty = True

    if demo_rich:
        await _seed_demo_spools(db, products, locations, printers, suppliers)


async def _seed_demo_spools(db, products, locations, printers, suppliers) -> None:
    existing = (await db.execute(select(FilamentSpool))).scalars().all()
    if len(existing) >= 12:
        await _ensure_demo_po(db, products, suppliers)
        return
    by_barcode = {p.barcode_id: p for p in products}
    black = by_barcode.get("FILT-SID-PETG-BLACK-3KG")
    grey = by_barcode.get("FILT-SID-PETG-GREY-3KG")
    white = by_barcode.get("FILT-SID-PETG-WHITE-3KG")
    blue = by_barcode.get("FILT-SID-PETG-ELECTRICBLUE-3KG") or by_barcode.get("FILT-SID-PETG-ELECTRICBL-3KG")
    if blue is None:
        for p in products:
            if p.color.lower().startswith("electric") and p.material == "PETG":
                blue = p
                break
    sunlu = next((p for p in products if p.manufacturer == "Sunlu"), None)
    now = utcnow()
    sealed = locations.get("Sealed Stock")
    opened = locations.get("Open Stock")
    shelf_a = locations.get("Filament Shelf A")
    black_shelf = locations.get("Black PETG Shelf")
    dryer = locations.get("Dryer 1")

    def add_spool(product, remaining, sealed_flag, loc, printer=None, days=8, drying=DryingStatus.dry):
        n = None
        return (product, remaining, sealed_flag, loc, printer, days, drying)

    specs = []
    if black:
        # physical ~ several 3kg rolls; some consumed so available can drop below min
        specs += [
            (black, 3000, True, sealed or shelf_a, None, 20, DryingStatus.unknown),
            (black, 3000, True, sealed or shelf_a, None, 18, DryingStatus.unknown),
            (black, 3000, True, black_shelf or shelf_a, None, 14, DryingStatus.unknown),
            (black, 2845, False, opened or shelf_a, printers[0] if printers else None, 12, DryingStatus.dry),
            (black, 2100, False, dryer or opened, None, 9, DryingStatus.drying),
            (black, 640, False, opened, printers[3] if len(printers) > 3 else None, 22, DryingStatus.dry),
        ]
    if grey:
        specs += [
            (grey, 3000, True, sealed, None, 11, DryingStatus.unknown),
            (grey, 1800, False, opened, None, 6, DryingStatus.dry),
        ]
    if white:
        specs += [(white, 3000, True, sealed, None, 10, DryingStatus.unknown)]
    if blue:
        specs += [(blue, 2650, False, opened, None, 7, DryingStatus.dry)]
    if sunlu and printers:
        specs += [(sunlu, 980, False, opened, printers[3] if len(printers) > 3 else None, 15, DryingStatus.drying)]

    created = []
    for product, remaining, sealed_flag, loc, printer, days, drying in specs:
        n = await next_spool_number(db)
        spool = FilamentSpool(
            name=f"{product.manufacturer} {product.material} {product.color} {product.spool_size_label}",
            manufacturer=product.manufacturer,
            material=product.material,
            color=product.color,
            initial_weight_g=product.filament_weight_g,
            remaining_weight_g=remaining,
            cost=product.purchase_cost,
            cost_per_kg=product.cost_per_kg,
            purchase_date=now - timedelta(days=days),
            date_received=now - timedelta(days=days),
            date_opened=None if sealed_flag else now - timedelta(days=max(1, days - 4)),
            assigned_printer_id=printer.id if printer else None,
            product_id=product.id,
            location_id=loc.id if loc else None,
            supplier_id=product.preferred_supplier_id,
            drying_status=drying,
            low_stock_threshold_g=max(150, product.filament_weight_g * 0.05),
            qr_token=new_qr_token(),
            public_code=spool_code(n),
            is_sealed=sealed_flag,
            is_empty=remaining <= 0,
            consumed_g=max(0.0, product.filament_weight_g - remaining),
        )
        db.add(spool)
        created.append(spool)
        if printer:
            printer.assigned_spool_id = spool.id
    await db.flush()
    for spool in created:
        if spool.consumed_g > 0:
            db.add(
                FilamentTransaction(
                    spool_id=spool.id,
                    previous_g=spool.initial_weight_g,
                    amount_g=spool.consumed_g,
                    remaining_g=spool.remaining_weight_g,
                    reason="print_consumed",
                    printer_id=spool.assigned_printer_id,
                    notes="Historical usage from demo farm",
                )
            )
        db.add(
            FilamentTransaction(
                spool_id=spool.id,
                previous_g=0,
                amount_g=spool.initial_weight_g,
                remaining_g=spool.initial_weight_g,
                reason="receive",
                notes="Demo receiving",
            )
        )
    await audit(db, "demo_seed", "filament", "catalog", {"spools": len(created)})
    await _ensure_demo_po(db, products, suppliers)


async def _ensure_demo_po(db, products, suppliers) -> None:
    existing = (await db.execute(select(PurchaseOrder).limit(1))).scalar_one_or_none()
    if existing:
        return
    black = next((p for p in products if p.color == "Black" and p.material == "PETG" and p.filament_weight_g >= 2500), None)
    if not black:
        return
    po = PurchaseOrder(
        reference=await next_po_reference(db),
        status="awaiting_approval",
        supplier_id=black.preferred_supplier_id,
        reason="Available Black PETG is below the 6 kg minimum after committed production. Recommended 5 × 3 kg to reach target.",
        auto_created=True,
        approval_required=True,
        total=round(5 * (black.normal_price or black.purchase_cost), 2),
        expected_delivery=utcnow() + timedelta(days=black.lead_time_days or 7),
    )
    db.add(po)
    await db.flush()
    db.add(
        PurchaseOrderLine(
            purchase_order_id=po.id,
            product_id=black.id,
            quantity_ordered=5,
            quantity_received=0,
            spool_weight_g=black.filament_weight_g,
            unit_price=black.normal_price or black.purchase_cost,
            price_per_kg=black.cost_per_kg,
            supplier_sku=black.supplier_sku,
        )
    )
    await audit(db, "reorder_triggered", "purchase_order", po.reference, {"demo": True})
