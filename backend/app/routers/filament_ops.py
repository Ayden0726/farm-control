from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import (
    DryingStatus,
    FilamentProduct,
    FilamentSpool,
    FilamentTransaction,
    InventoryAudit,
    Printer,
    StorageLocation,
    Supplier,
    User,
    utcnow,
)
from app.services.barcodes import unique_product_barcode
from app.services.filament import (
    assign_spool_to_printer,
    audit,
    committed_by_product,
    cost_per_kg,
    create_spools_from_receive,
    forecast,
    kg,
    move_spool,
    product_physical_g,
    recommend_rolls,
    record_transaction,
    stock_snapshot,
    usage_stats,
)
from app.services.reorder import spend_controls
from app.util import new_qr_token

router = APIRouter(prefix="/filament", tags=["filament"])


class ProductIn(BaseModel):
    manufacturer: str
    product_name: str = ""
    material: str = "PETG"
    color: str = ""
    spool_size_label: str = "1 kg"
    filament_weight_g: float = 1000
    purchase_cost: float = 0
    preferred_supplier_id: UUID | None = None
    backup_supplier_id: UUID | None = None
    supplier_sku: str = ""
    supplier_url: str = ""
    nozzle_temp_c: float | None = None
    bed_temp_c: float | None = None
    notes: str = ""
    min_stock_g: float = 6000
    target_stock_g: float = 18000
    preferred_spool_weight_g: float | None = None
    normal_price: float = 0
    max_price: float = 0
    max_price_per_kg: float = 0
    min_reorder_qty: int = 1
    reorder_multiple: int = 1
    lead_time_days: int = 7
    reorder_mode: str = "create_purchase_order"
    approval_required: bool = True
    max_po_amount: float = 0
    is_active: bool = True


class LocationIn(BaseModel):
    name: str
    kind: str = "shelf"
    notes: str = ""
    printer_id: UUID | None = None
    is_active: bool = True


class ReceiveIn(BaseModel):
    product_id: UUID | None = None
    barcode: str | None = None
    quantity: int = Field(ge=1, le=500)
    cost_per_spool: float = Field(ge=0)
    supplier_id: UUID | None = None
    purchase_order_id: UUID | None = None
    location_id: UUID | None = None
    date_purchased: datetime | None = None
    notes: str = ""


class AssignIn(BaseModel):
    printer_id: UUID | None = None
    printer_code: str | None = None
    spool_id: UUID | None = None
    spool_code: str | None = None


class MoveIn(BaseModel):
    location_id: UUID


class AdjustIn(BaseModel):
    remaining_weight_g: float = Field(ge=0)
    notes: str = ""


class SpoolPatch(BaseModel):
    notes: str | None = None
    drying_status: str | None = None
    is_sealed: bool | None = None
    is_archived: bool | None = None
    location_id: UUID | None = None
    last_dried_at: datetime | None = None


def _product_out(p: FilamentProduct, extra: dict | None = None) -> dict:
    data = {
        "id": str(p.id),
        "barcode_id": p.barcode_id,
        "manufacturer": p.manufacturer,
        "product_name": p.product_name,
        "material": p.material,
        "color": p.color,
        "spool_size_label": p.spool_size_label,
        "filament_weight_g": p.filament_weight_g,
        "purchase_cost": p.purchase_cost,
        "cost_per_kg": p.cost_per_kg,
        "preferred_supplier_id": str(p.preferred_supplier_id) if p.preferred_supplier_id else None,
        "backup_supplier_id": str(p.backup_supplier_id) if p.backup_supplier_id else None,
        "preferred_supplier_name": p.preferred_supplier.name if p.preferred_supplier else None,
        "backup_supplier_name": p.backup_supplier.name if p.backup_supplier else None,
        "supplier_sku": p.supplier_sku,
        "supplier_url": p.supplier_url,
        "nozzle_temp_c": p.nozzle_temp_c,
        "bed_temp_c": p.bed_temp_c,
        "notes": p.notes,
        "min_stock_g": p.min_stock_g,
        "target_stock_g": p.target_stock_g,
        "preferred_spool_weight_g": p.preferred_spool_weight_g,
        "normal_price": p.normal_price,
        "max_price": p.max_price,
        "max_price_per_kg": p.max_price_per_kg,
        "min_reorder_qty": p.min_reorder_qty,
        "reorder_multiple": p.reorder_multiple,
        "lead_time_days": p.lead_time_days,
        "reorder_mode": p.reorder_mode,
        "approval_required": p.approval_required,
        "max_po_amount": p.max_po_amount,
        "is_active": p.is_active,
    }
    if extra:
        data.update(extra)
    return data


def _spool_detail(s: FilamentSpool) -> dict:
    return {
        "id": str(s.id),
        "public_code": s.public_code,
        "qr_token": s.qr_token,
        "name": s.name,
        "product_id": str(s.product_id) if s.product_id else None,
        "barcode_id": s.product.barcode_id if s.product else None,
        "manufacturer": s.manufacturer,
        "material": s.material,
        "color": s.color,
        "initial_weight_g": s.initial_weight_g,
        "remaining_weight_g": s.remaining_weight_g,
        "consumed_g": s.consumed_g,
        "cost": s.cost,
        "cost_per_kg": s.cost_per_kg or (cost_per_kg(s.cost, s.initial_weight_g) if s.initial_weight_g else 0),
        "purchase_date": s.purchase_date.isoformat() if s.purchase_date else None,
        "date_received": s.date_received.isoformat() if s.date_received else None,
        "date_opened": s.date_opened.isoformat() if s.date_opened else None,
        "last_dried_at": s.last_dried_at.isoformat() if s.last_dried_at else None,
        "is_sealed": s.is_sealed,
        "is_empty": s.is_empty,
        "is_archived": s.is_archived,
        "drying_status": s.drying_status.value,
        "location_id": str(s.location_id) if s.location_id else None,
        "location_name": s.location.name if s.location else None,
        "assigned_printer_id": str(s.assigned_printer_id) if s.assigned_printer_id else None,
        "assigned_printer_name": s.assigned_printer.name if s.assigned_printer else None,
        "purchase_order_id": str(s.purchase_order_id) if s.purchase_order_id else None,
        "notes": s.notes,
        "is_low": s.remaining_weight_g <= s.low_stock_threshold_g,
    }


async def _load_product(db: AsyncSession, product_id: UUID) -> FilamentProduct:
    row = (
        await db.execute(
            select(FilamentProduct)
            .options(
                selectinload(FilamentProduct.preferred_supplier),
                selectinload(FilamentProduct.backup_supplier),
            )
            .where(FilamentProduct.id == product_id)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Filament product not found")
    return row


@router.get("/dashboard")
async def filament_dashboard(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    products = (
        await db.execute(
            select(FilamentProduct)
            .options(
                selectinload(FilamentProduct.preferred_supplier),
                selectinload(FilamentProduct.backup_supplier),
            )
            .where(FilamentProduct.is_active.is_(True))
            .order_by(FilamentProduct.material, FilamentProduct.color)
        )
    ).scalars().all()
    committed_map = await committed_by_product(db)
    snaps = [await stock_snapshot(db, p, committed_map) for p in products]
    stats = await usage_stats(db)
    recent = (
        await db.execute(
            select(FilamentTransaction)
            .options(selectinload(FilamentTransaction.spool), selectinload(FilamentTransaction.printer))
            .order_by(FilamentTransaction.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    by_material: dict[str, float] = {}
    by_color: dict[str, float] = {}
    by_mfr: dict[str, float] = {}
    for snap, p in zip(snaps, products):
        by_material[p.material] = by_material.get(p.material, 0) + snap["physical_g"]
        by_color[p.color] = by_color.get(p.color, 0) + snap["physical_g"]
        by_mfr[p.manufacturer] = by_mfr.get(p.manufacturer, 0) + snap["physical_g"]
    sealed = sum(s["sealed_rolls"] for s in snaps)
    opened = sum(s["open_rolls"] for s in snaps)
    installed = sum(s["installed_rolls"] for s in snaps)
    empty = sum(s["empty_rolls"] for s in snaps)
    value = sum(s["inventory_value"] for s in snaps)
    physical = sum(s["physical_g"] for s in snaps)
    spend = await spend_controls(db)
    forecasts = []
    for p, snap in zip(products, snaps):
        st = await usage_stats(db, p.id)
        forecasts.append({"product": _product_out(p), "stock": snap, "forecast": await forecast(db, p, snap, st), "recommend": recommend_rolls(p, snap["available_g"])})
    return {
        "totals": {
            "physical_g": physical,
            "physical_kg": kg(physical),
            "sealed_rolls": sealed,
            "open_rolls": opened,
            "installed_rolls": installed,
            "empty_rolls": empty,
            "inventory_value": round(value, 2),
            "avg_daily_g": stats["avg_daily_g"],
            "low_stock": sum(1 for s in snaps if s["below_minimum"]),
        },
        "by_material": {k: kg(v) for k, v in by_material.items()},
        "by_color": {k: kg(v) for k, v in by_color.items()},
        "by_manufacturer": {k: kg(v) for k, v in by_mfr.items()},
        "products": forecasts,
        "recent_usage": [
            {
                "id": str(t.id),
                "at": t.created_at.isoformat(),
                "spool": t.spool.public_code if t.spool else None,
                "amount_g": t.amount_g,
                "remaining_g": t.remaining_g,
                "reason": t.reason,
                "printer": t.printer.name if t.printer else None,
            }
            for t in recent
        ],
        "spend": spend,
    }


@router.get("/products")
async def list_products(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    products = (
        await db.execute(
            select(FilamentProduct)
            .options(
                selectinload(FilamentProduct.preferred_supplier),
                selectinload(FilamentProduct.backup_supplier),
            )
            .order_by(FilamentProduct.manufacturer, FilamentProduct.color)
        )
    ).scalars().all()
    committed_map = await committed_by_product(db)
    out = []
    for p in products:
        snap = await stock_snapshot(db, p, committed_map)
        rec = recommend_rolls(p, snap["available_g"])
        out.append(_product_out(p, {"stock": snap, "recommend": rec}))
    return out


@router.post("/products")
async def create_product(
    payload: ProductIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    weight = payload.filament_weight_g
    barcode = await unique_product_barcode(
        db, payload.manufacturer, payload.material, payload.color, weight
    )
    product = FilamentProduct(
        barcode_id=barcode,
        manufacturer=payload.manufacturer,
        product_name=payload.product_name or f"{payload.manufacturer} {payload.material}",
        material=payload.material,
        color=payload.color,
        spool_size_label=payload.spool_size_label,
        filament_weight_g=weight,
        purchase_cost=payload.purchase_cost,
        cost_per_kg=cost_per_kg(payload.purchase_cost, weight),
        preferred_supplier_id=payload.preferred_supplier_id,
        backup_supplier_id=payload.backup_supplier_id,
        supplier_sku=payload.supplier_sku,
        supplier_url=payload.supplier_url,
        nozzle_temp_c=payload.nozzle_temp_c,
        bed_temp_c=payload.bed_temp_c,
        notes=payload.notes,
        min_stock_g=payload.min_stock_g,
        target_stock_g=payload.target_stock_g,
        preferred_spool_weight_g=payload.preferred_spool_weight_g or weight,
        normal_price=payload.normal_price or payload.purchase_cost,
        max_price=payload.max_price,
        max_price_per_kg=payload.max_price_per_kg,
        min_reorder_qty=payload.min_reorder_qty,
        reorder_multiple=max(1, payload.reorder_multiple),
        lead_time_days=payload.lead_time_days,
        reorder_mode=payload.reorder_mode,
        approval_required=payload.approval_required,
        max_po_amount=payload.max_po_amount,
        is_active=payload.is_active,
    )
    if product.reorder_mode == "full_auto":
        spend = await spend_controls(db)
        if not spend.get("full_auto_enabled"):
            product.reorder_mode = "create_purchase_order"
    db.add(product)
    await db.flush()
    await audit(db, "product_created", "product", product.barcode_id, {"id": str(product.id)}, actor=user.email)
    await db.commit()
    return _product_out(await _load_product(db, product.id))


@router.get("/products/{product_id}")
async def get_product(product_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    product = await _load_product(db, product_id)
    committed_map = await committed_by_product(db)
    snap = await stock_snapshot(db, product, committed_map)
    st = await usage_stats(db, product.id)
    spools = (
        await db.execute(
            select(FilamentSpool)
            .options(selectinload(FilamentSpool.assigned_printer), selectinload(FilamentSpool.location), selectinload(FilamentSpool.product))
            .where(FilamentSpool.product_id == product.id)
            .order_by(FilamentSpool.public_code)
        )
    ).scalars().all()
    return _product_out(
        product,
        {
            "stock": snap,
            "forecast": await forecast(db, product, snap, st),
            "recommend": recommend_rolls(product, snap["available_g"]),
            "spools": [_spool_detail(s) for s in spools],
        },
    )


@router.patch("/products/{product_id}")
async def update_product(
    product_id: UUID,
    payload: ProductIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    product = await _load_product(db, product_id)
    data = payload.model_dump()
    data["preferred_spool_weight_g"] = payload.preferred_spool_weight_g or payload.filament_weight_g
    data["cost_per_kg"] = cost_per_kg(payload.purchase_cost, payload.filament_weight_g)
    if data.get("reorder_mode") == "full_auto":
        spend = await spend_controls(db)
        if not spend.get("full_auto_enabled"):
            raise HTTPException(400, "Full Auto is disabled in spending controls. Enable it before setting this mode.")
    for k, v in data.items():
        setattr(product, k, v)
    await audit(db, "product_updated", "product", product.barcode_id, actor=user.email)
    await db.commit()
    return await get_product(product_id, db, user)  # type: ignore[arg-type]


@router.get("/locations")
async def list_locations(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(StorageLocation).order_by(StorageLocation.name))).scalars().all()
    counts = dict(
        (
            await db.execute(
                select(FilamentSpool.location_id, func.count())
                .where(FilamentSpool.is_archived.is_(False), FilamentSpool.is_empty.is_(False))
                .group_by(FilamentSpool.location_id)
            )
        ).all()
    )
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "kind": r.kind,
            "notes": r.notes,
            "is_active": r.is_active,
            "printer_id": str(r.printer_id) if r.printer_id else None,
            "spool_count": int(counts.get(r.id, 0)),
        }
        for r in rows
    ]


@router.post("/locations")
async def create_location(payload: LocationIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    row = StorageLocation(**payload.model_dump())
    db.add(row)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(400, f"Could not create location: {exc}") from exc
    await db.refresh(row)
    return {"id": str(row.id), "name": row.name, "kind": row.kind, "notes": row.notes, "printer_id": str(row.printer_id) if row.printer_id else None}


@router.patch("/locations/{location_id}")
async def update_location(
    location_id: UUID, payload: LocationIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    row = await db.get(StorageLocation, location_id)
    if not row:
        raise HTTPException(404, "Location not found")
    for k, v in payload.model_dump().items():
        setattr(row, k, v)
    await db.commit()
    return {"id": str(row.id), "name": row.name, "kind": row.kind}


@router.post("/receive")
async def receive_filament(
    payload: ReceiveIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    product = None
    if payload.product_id:
        product = await db.get(FilamentProduct, payload.product_id)
    elif payload.barcode:
        from app.services.barcodes import resolve_code

        hit = await resolve_code(db, payload.barcode)
        if hit and hit["kind"] == "product":
            product = hit["row"]
    if not product:
        raise HTTPException(400, "Scan a FarmOS receiving barcode or choose a filament product.")
    try:
        spools = await create_spools_from_receive(
            db,
            product,
            payload.quantity,
            payload.cost_per_spool,
            supplier_id=payload.supplier_id,
            purchase_order_id=payload.purchase_order_id,
            location_id=payload.location_id,
            date_purchased=payload.date_purchased,
            notes=payload.notes,
            actor=user.email,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if payload.purchase_order_id:
        from app.models import PurchaseOrder, PurchaseOrderLine

        po = await db.get(PurchaseOrder, payload.purchase_order_id)
        if po:
            lines = (
                await db.execute(
                    select(PurchaseOrderLine).where(
                        PurchaseOrderLine.purchase_order_id == po.id,
                        PurchaseOrderLine.product_id == product.id,
                    )
                )
            ).scalars().all()
            remaining = payload.quantity
            for line in lines:
                space = max(0, line.quantity_ordered - line.quantity_received)
                take = min(space, remaining)
                line.quantity_received += take
                remaining -= take
            received = sum(ln.quantity_received for ln in (await db.execute(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id))).scalars().all())
            ordered = sum(ln.quantity_ordered for ln in (await db.execute(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id))).scalars().all())
            if received >= ordered:
                po.status = "delivered"
                po.closed_at = utcnow()
            elif received > 0:
                po.status = "partially_received"
    await db.commit()
    loaded = (
        await db.execute(
            select(FilamentSpool)
            .options(
                selectinload(FilamentSpool.assigned_printer),
                selectinload(FilamentSpool.location),
                selectinload(FilamentSpool.product),
            )
            .where(FilamentSpool.id.in_([s.id for s in spools]))
            .order_by(FilamentSpool.public_code)
        )
    ).scalars().all()
    return {
        "ok": True,
        "message": f"{len(loaded)} spools added successfully",
        "product": {
            "id": str(product.id),
            "barcode_id": product.barcode_id,
            "manufacturer": product.manufacturer,
            "material": product.material,
            "color": product.color,
            "spool_size_label": product.spool_size_label,
        },
        "spools": [_spool_detail(s) for s in loaded],
        "print_path": "/labels/print?kind=spool&ids=" + ",".join(str(s.id) for s in loaded),
    }


@router.get("/spools/{spool_id}")
async def get_spool_detail(spool_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    spool = (
        await db.execute(
            select(FilamentSpool)
            .options(
                selectinload(FilamentSpool.assigned_printer),
                selectinload(FilamentSpool.location),
                selectinload(FilamentSpool.product),
                selectinload(FilamentSpool.transactions),
            )
            .where(FilamentSpool.id == spool_id)
        )
    ).scalar_one_or_none()
    if not spool:
        raise HTTPException(404, "Spool not found")
    data = _spool_detail(spool)
    data["transactions"] = [
        {
            "id": str(t.id),
            "at": t.created_at.isoformat(),
            "previous_g": t.previous_g,
            "amount_g": t.amount_g,
            "remaining_g": t.remaining_g,
            "reason": t.reason,
            "notes": t.notes,
        }
        for t in sorted(spool.transactions, key=lambda x: x.created_at, reverse=True)
    ]
    return data


@router.patch("/spools/{spool_id}/detail")
async def patch_spool_detail(
    spool_id: UUID, payload: SpoolPatch, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    spool = await db.get(FilamentSpool, spool_id)
    if not spool:
        raise HTTPException(404, "Spool not found")
    data = payload.model_dump(exclude_unset=True)
    if "drying_status" in data and data["drying_status"]:
        spool.drying_status = DryingStatus(data.pop("drying_status"))
        if spool.drying_status == DryingStatus.dry:
            spool.last_dried_at = utcnow()
    for k, v in data.items():
        setattr(spool, k, v)
    await db.commit()
    return await get_spool_detail(spool_id, db, user)  # type: ignore[arg-type]


@router.post("/spools/{spool_id}/move")
async def move_spool_api(
    spool_id: UUID, payload: MoveIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    spool = await db.get(FilamentSpool, spool_id)
    loc = await db.get(StorageLocation, payload.location_id)
    if not spool or not loc:
        raise HTTPException(404, "Spool or location not found")
    await move_spool(db, spool, loc, actor=user.email)
    await db.commit()
    return {"ok": True, "location": loc.name}


@router.post("/spools/{spool_id}/adjust")
async def adjust_spool(
    spool_id: UUID, payload: AdjustIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    spool = await db.get(FilamentSpool, spool_id)
    if not spool:
        raise HTTPException(404, "Spool not found")
    await record_transaction(db, spool, payload.remaining_weight_g, "adjustment", notes=payload.notes or "Manual correction")
    if spool.remaining_weight_g > 0:
        spool.is_empty = False
    await db.commit()
    return {"ok": True, "remaining_weight_g": spool.remaining_weight_g}


@router.post("/assign")
async def assign_scan(
    payload: AssignIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    printer = None
    spool = None
    if payload.printer_id:
        printer = await db.get(Printer, payload.printer_id)
    elif payload.printer_code:
        from app.services.barcodes import resolve_code

        hit = await resolve_code(db, payload.printer_code)
        if hit and hit["kind"] == "printer":
            printer = hit["row"]
    if payload.spool_id:
        spool = await db.get(FilamentSpool, payload.spool_id)
    elif payload.spool_code:
        from app.services.barcodes import resolve_code

        hit = await resolve_code(db, payload.spool_code)
        if hit and hit["kind"] == "spool":
            spool = hit["row"]
    if not printer or not spool:
        raise HTTPException(400, "Scan both a printer QR and a spool QR.")
    await assign_spool_to_printer(db, printer, spool, actor=user.email)
    await db.commit()
    return {
        "ok": True,
        "message": f"Assigned {spool.public_code} to {printer.name}",
        "printer_id": str(printer.id),
        "spool_id": str(spool.id),
        "spool_code": spool.public_code,
        "printer_name": printer.name,
        "remaining_g": spool.remaining_weight_g,
        "material": spool.material,
        "color": spool.color,
        "manufacturer": spool.manufacturer,
    }


@router.get("/audit")
async def list_audit(limit: int = 100, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (
        await db.execute(select(InventoryAudit).order_by(InventoryAudit.created_at.desc()).limit(min(limit, 500)))
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "at": r.created_at.isoformat(),
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "detail": r.detail,
            "actor": r.actor,
        }
        for r in rows
    ]


@router.get("/identify/{code}")
async def identify_code(code: str, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    from app.services.barcodes import resolve_code

    hit = await resolve_code(db, code)
    if not hit:
        raise HTTPException(404, "Unknown FarmOS code")
    kind, row = hit["kind"], hit["row"]
    if kind == "product":
        return {
            "kind": "product",
            "id": str(row.id),
            "barcode_id": row.barcode_id,
            "manufacturer": row.manufacturer,
            "material": row.material,
            "color": row.color,
            "spool_size_label": row.spool_size_label,
            "filament_weight_g": row.filament_weight_g,
            "preferred_supplier_id": str(row.preferred_supplier_id) if row.preferred_supplier_id else None,
            "purchase_cost": row.purchase_cost,
            "path": f"/filament/products/{row.id}",
            "actions": ["receive"],
        }
    if kind == "spool":
        return {
            "kind": "spool",
            "id": str(row.id),
            "public_code": row.public_code,
            "name": row.name,
            "material": row.material,
            "color": row.color,
            "remaining_weight_g": row.remaining_weight_g,
            "path": f"/filament/spools/{row.id}",
            "actions": ["find", "assign", "move"],
        }
    if kind == "printer":
        return {
            "kind": "printer",
            "id": str(row.id),
            "name": row.name,
            "public_code": row.public_code,
            "assigned_spool_id": str(row.assigned_spool_id) if row.assigned_spool_id else None,
            "path": f"/printers/{row.id}",
            "actions": ["assign"],
        }
    if kind == "bin":
        return {
            "kind": "bin",
            "id": str(row.id),
            "name": row.name,
            "public_code": row.public_code,
            "path": "/inventory",
            "actions": ["bin"],
        }
    if kind == "job":
        return {"kind": "job", "id": str(row.id), "path": "/queue", "actions": []}
    raise HTTPException(404, "Unknown FarmOS code")
