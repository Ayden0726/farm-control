from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AppSetting,
    DryingStatus,
    FilamentProduct,
    FilamentSpool,
    FilamentTransaction,
    IdSequence,
    PartBin,
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


async def ensure_filament_system(db: AsyncSession, *, demo_rich: bool = False) -> None:
    """Idempotent: catalog, locations, public codes, spend controls."""
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
    if not suppliers:
        for name, site, adapter in [
            ("Siddament", "https://siddament.com.au", "url"),
            ("Sunlu", "https://www.sunlu.com", "url"),
            ("eSun", "https://www.esun3d.com", "url"),
            ("Polymaker", "https://polymaker.com", "url"),
        ]:
            s = Supplier(name=name, website=site, adapter_type=adapter, capabilities=["product_url", "stored_price"])
            db.add(s)
            suppliers[name] = s
        await db.flush()

    products = list((await db.execute(select(FilamentProduct))).scalars().all())
    if not products:
        catalog = [
            ("Siddament", "Siddament PETG", "PETG", "Black", "3 kg", 3000, 57.0, "Siddament", 6000, 18000, "SID-PETG-BLK-3"),
            ("Siddament", "Siddament PETG", "PETG", "Grey", "3 kg", 3000, 57.0, "Siddament", 3000, 9000, "SID-PETG-GRY-3"),
            ("Siddament", "Siddament PETG", "PETG", "White", "3 kg", 3000, 57.0, "Siddament", 3000, 9000, "SID-PETG-WHT-3"),
            ("Siddament", "Siddament PETG", "PETG", "Electric Blue", "3 kg", 3000, 62.0, "Siddament", 3000, 6000, "SID-PETG-EBL-3"),
            ("Sunlu", "Sunlu PETG", "PETG", "Black", "1 kg", 1000, 22.5, "Sunlu", 2000, 6000, "SUN-PETG-BLK-1"),
            ("eSun", "eSun PLA+", "PLA", "Grey", "1 kg", 1000, 19.0, "eSun", 1000, 3000, "ESUN-PLA-GRY-1"),
            ("Polymaker", "PolyLite PETG", "PETG", "Orange", "1 kg", 1000, 28.0, "Polymaker", 1000, 3000, "POLY-PETG-ORG-1"),
            ("eSun", "eSun PETG", "PETG", "White", "1 kg", 1000, 24.0, "eSun", 2000, 4000, "ESUN-PETG-WHT-1"),
        ]
        for mfr, pname, mat, color, size, weight, cost, supplier_name, mn, tgt, sku in catalog:
            p = FilamentProduct(
                barcode_id=product_barcode_id(mfr, mat, color, weight),
                manufacturer=mfr,
                product_name=pname,
                material=mat,
                color=color,
                spool_size_label=size,
                filament_weight_g=weight,
                purchase_cost=cost,
                cost_per_kg=cost_per_kg(cost, weight),
                preferred_supplier_id=suppliers[supplier_name].id,
                supplier_sku=sku,
                supplier_url=suppliers[supplier_name].website,
                nozzle_temp_c=250 if mat == "PETG" else 210,
                bed_temp_c=80 if mat == "PETG" else 60,
                min_stock_g=mn,
                target_stock_g=tgt,
                preferred_spool_weight_g=weight,
                normal_price=cost,
                max_price=cost * 1.25,
                max_price_per_kg=cost_per_kg(cost * 1.25, weight),
                min_reorder_qty=1,
                reorder_multiple=1,
                lead_time_days=7 if mfr == "Siddament" else 10,
                reorder_mode="create_purchase_order",
                approval_required=True,
            )
            db.add(p)
            products.append(p)
        await db.flush()
        demo_rich = True

    by_key = {(p.manufacturer.lower(), p.material.lower(), p.color.lower(), round(p.filament_weight_g)): p for p in products}

    seq = await db.get(IdSequence, "spool")
    if seq is None:
        seq = IdSequence(name="spool", next_value=141)
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
