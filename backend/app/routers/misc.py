from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import (
    AppSetting,
    FilamentSpool,
    JobStatus,
    MaintenanceLog,
    Notification,
    Part,
    PartBin,
    PrintJob,
    Printer,
    User,
    utcnow,
)
from app.schemas import (
    MaintenanceIn,
    MaintenanceOut,
    NotificationOut,
    SettingsIn,
    SettingsOut,
)
from app.services.qr import render_qr_png
from app.services.woocommerce import woocommerce_configured
from app.services.shopify import normalize_shop, shopify_config, shopify_configured
from app.security import encrypt_secret
from app.services.farm_settings import get_automation, get_mes, upsert_automation, upsert_mes

notify_router = APIRouter(prefix="/notifications-legacy-removed", tags=["notifications"])
maint_router = APIRouter(prefix="/maintenance", tags=["maintenance"])
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])
settings_router = APIRouter(prefix="/settings", tags=["settings"])
qr_router = APIRouter(prefix="/qr", tags=["qr"])
scan_router = APIRouter(prefix="/scan", tags=["qr"])


@notify_router.get("", response_model=list[NotificationOut])
async def list_notifications(
    unread_only: bool = False,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(200)
    if unread_only:
        stmt = select(Notification).where(Notification.is_read.is_(False)).order_by(
            Notification.created_at.desc()
        )
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@notify_router.post("/{notification_id}/read")
async def mark_read(
    notification_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    row = await db.get(Notification, notification_id)
    if not row:
        raise HTTPException(404, "Not found")
    row.is_read = True
    await db.commit()
    return {"ok": True}


@notify_router.post("/read-all")
async def read_all(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(Notification).where(Notification.is_read.is_(False)))).scalars().all()
    for row in rows:
        row.is_read = True
    await db.commit()
    return {"ok": True, "count": len(rows)}


@maint_router.get("", response_model=list[MaintenanceOut])
async def list_maintenance(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(MaintenanceLog)
            .options(selectinload(MaintenanceLog.printer))
            .order_by(MaintenanceLog.performed_at.desc())
        )
    ).scalars().all()
    return [
        MaintenanceOut(
            id=r.id,
            printer_id=r.printer_id,
            printer_name=r.printer.name if r.printer else None,
            performed_at=r.performed_at,
            hours_at_service=r.hours_at_service,
            kind=r.kind,
            notes=r.notes,
        )
        for r in rows
    ]


@maint_router.get("/due")
async def maintenance_due(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    printers = (await db.execute(select(Printer))).scalars().all()
    due = []
    for printer in printers:
        hours = printer.total_print_seconds / 3600
        remaining = printer.maintenance_interval_hours - hours
        if remaining <= 20:
            due.append(
                {
                    "printer_id": str(printer.id),
                    "name": printer.name,
                    "print_hours": round(hours, 1),
                    "interval_hours": printer.maintenance_interval_hours,
                    "hours_remaining": round(remaining, 1),
                    "last_maintenance_at": printer.last_maintenance_at.isoformat()
                    if printer.last_maintenance_at
                    else None,
                    "notes": printer.maintenance_notes,
                }
            )
    return due


@maint_router.post("/{printer_id}", response_model=MaintenanceOut)
async def log_maintenance(
    printer_id: UUID,
    payload: MaintenanceIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    printer = await db.get(Printer, printer_id)
    if not printer:
        raise HTTPException(404, "Printer not found")
    hours = payload.hours_at_service if payload.hours_at_service is not None else printer.total_print_seconds / 3600
    log = MaintenanceLog(
        printer_id=printer.id,
        hours_at_service=hours,
        kind=payload.kind,
        notes=payload.notes,
        performed_at=utcnow(),
    )
    db.add(log)
    printer.last_maintenance_at = log.performed_at
    # Reset interval clock by subtracting current hours conceptually: store last service timestamp
    printer.total_print_seconds = 0
    await db.commit()
    await db.refresh(log)
    return MaintenanceOut(
        id=log.id,
        printer_id=log.printer_id,
        printer_name=printer.name,
        performed_at=log.performed_at,
        hours_at_service=log.hours_at_service,
        kind=log.kind,
        notes=log.notes,
    )


@analytics_router.get("")
async def analytics(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    printers = (await db.execute(select(Printer))).scalars().all()
    jobs = (
        await db.execute(
            select(PrintJob).options(selectinload(PrintJob.part), selectinload(PrintJob.gcode_file))
        )
    ).scalars().all()
    completed = [j for j in jobs if j.status == JobStatus.completed]
    failed = [j for j in jobs if j.status == JobStatus.failed]
    now = datetime.now(timezone.utc)

    def in_window(job: PrintJob, days: int) -> bool:
        if not job.completed_at:
            return False
        completed_at = job.completed_at
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)
        return completed_at >= now - timedelta(days=days)

    jobs_by_printer = []
    for printer in printers:
        pjobs = [j for j in jobs if j.actual_printer_id == printer.id or j.assigned_printer_id == printer.id]
        pdone = [j for j in pjobs if j.status == JobStatus.completed]
        pfail = [j for j in pjobs if j.status == JobStatus.failed]
        hours = printer.total_print_seconds / 3600
        jobs_by_printer.append(
            {
                "printer_id": str(printer.id),
                "name": printer.name,
                "jobs": len(pjobs),
                "completed": len(pdone),
                "failed": len(pfail),
                "print_hours": round(hours, 2),
                "utilisation_hint": round(min(100, hours / max(1, 24) * 100), 1),
                "filament_g": round(sum(j.filament_used_grams for j in pdone), 1),
                "filament_cost": round(sum(j.filament_cost for j in pdone), 2),
            }
        )

    cost_by_part: dict[str, dict] = {}
    for job in completed:
        sku = job.part.sku if job.part else (job.gcode_file.filename if job.gcode_file else "unknown")
        entry = cost_by_part.setdefault(sku, {"sku": sku, "jobs": 0, "parts": 0, "filament_g": 0.0, "cost": 0.0, "seconds": 0})
        entry["jobs"] += 1
        entry["parts"] += job.quantity_produced
        entry["filament_g"] += job.filament_used_grams
        entry["cost"] += job.filament_cost
        if job.started_at and job.completed_at:
            entry["seconds"] += int((job.completed_at - job.started_at).total_seconds())

    def bucket(days: int) -> list[dict]:
        buckets: dict[str, int] = {}
        for job in completed:
            if not in_window(job, days if days < 400 else 3650) or not job.completed_at:
                continue
            key = job.completed_at.date().isoformat()
            if days > 40:
                key = job.completed_at.strftime("%Y-%W")
            buckets[key] = buckets.get(key, 0) + job.quantity_produced
        return [{"period": k, "parts": v} for k, v in sorted(buckets.items())]

    return {
        "totals": {
            "jobs": len(jobs),
            "completed": len(completed),
            "failed": len(failed),
            "success_rate": round(100 * len(completed) / max(1, len(completed) + len(failed)), 1),
            "filament_g": round(sum(j.filament_used_grams for j in completed), 1),
            "filament_cost": round(sum(j.filament_cost for j in completed), 2),
            "print_hours": round(sum(p.total_print_seconds for p in printers) / 3600, 2),
        },
        "jobs_per_printer": jobs_by_printer,
        "cost_by_part": list(cost_by_part.values()),
        "output_day": bucket(14),
        "output_week": bucket(90),
        "output_month": bucket(365),
        "completed_today": sum(1 for j in completed if in_window(j, 1)),
        "completed_week": sum(1 for j in completed if in_window(j, 7)),
        "completed_month": sum(1 for j in completed if in_window(j, 30)),
    }


@settings_router.get("", response_model=SettingsOut)
async def get_settings_api(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return await _settings_out(db)


@settings_router.put("", response_model=SettingsOut)
async def put_settings(
    payload: SettingsIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    if payload.company_name is not None:
        row = await db.get(AppSetting, "company_name")
        if row:
            row.value = payload.company_name
        else:
            db.add(AppSetting(key="company_name", value=payload.company_name))
    stored = await db.get(AppSetting, "integrations")
    integrations = dict(stored.value) if stored else {}
    if payload.woocommerce_url is not None:
        integrations["woocommerce_url"] = payload.woocommerce_url
    if payload.woocommerce_key:
        integrations["woocommerce_key_set"] = True
    if payload.woocommerce_secret:
        integrations["woocommerce_secret_set"] = True
    if payload.shopify_shop is not None:
        integrations["shopify_shop"] = normalize_shop(payload.shopify_shop)
    if payload.shopify_access_token:
        integrations["shopify_access_token_enc"] = encrypt_secret(payload.shopify_access_token.strip())
    if payload.shopify_webhook_secret:
        integrations["shopify_webhook_secret_enc"] = encrypt_secret(payload.shopify_webhook_secret.strip())
    if payload.shopify_api_version:
        integrations["shopify_api_version"] = payload.shopify_api_version.strip()
    if payload.notify_webhook_url is not None:
        integrations["notify_webhook_url"] = payload.notify_webhook_url
    if stored:
        stored.value = integrations
    else:
        db.add(AppSetting(key="integrations", value=integrations))
    await upsert_automation(
        db,
        auto_part_ejection=payload.auto_part_ejection,
        pack_bed_x_mm=payload.pack_bed_x_mm,
        pack_bed_y_mm=payload.pack_bed_y_mm,
        pack_gap_mm=payload.pack_gap_mm,
    )
    mes_keys = {
        "auto_requeue_failed_qc",
        "electricity_price_per_kwh",
        "labour_rate_per_hour",
        "enable_electricity_cost",
        "enable_machine_cost",
        "enable_labour_cost",
        "enable_failure_cost",
        "payment_fee_percent",
        "overnight_start_hour",
        "overnight_end_hour",
        "backup_retention_days",
        "backup_include_files",
        "include_camera_in_notifications",
    }
    mes_payload = payload.model_dump(include=mes_keys, exclude_none=True)
    if mes_payload:
        await upsert_mes(db, mes_payload)
    await db.commit()
    return await _settings_out(db)


async def _settings_out(db: AsyncSession) -> SettingsOut:
    settings = get_settings()
    company = await db.get(AppSetting, "company_name")
    automation = await get_automation(db)
    mes = await get_mes(db)
    shopify = await shopify_config(db)
    return SettingsOut(
        company_name=(company.value if company else "Print Farm"),
        woocommerce_url=settings.woocommerce_url,
        woocommerce_configured=woocommerce_configured(),
        shopify_shop=shopify.get("shop") or "",
        shopify_configured=shopify_configured(shopify),
        shopify_api_version=shopify.get("api_version") or "2024-10",
        notify_webhook_configured=bool(settings.notify_webhook_url),
        simulated_time_scale=settings.simulated_time_scale,
        filament_low_grams=settings.filament_low_grams,
        app_version=settings.app_version or "dev",
        update_command="./update.sh",
        auto_part_ejection=automation["auto_part_ejection"],
        pack_bed_x_mm=automation["pack_bed_x_mm"],
        pack_bed_y_mm=automation["pack_bed_y_mm"],
        pack_gap_mm=automation["pack_gap_mm"],
        **{k: mes[k] for k in mes},
    )


@qr_router.get("/{kind}/{token}")
async def qr_image(kind: str, token: str):
    path = render_qr_png(kind, token)
    return FileResponse(path, media_type="image/png")


@scan_router.get("/{kind}/{token}")
async def resolve_scan(kind: str, token: str, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    from app.services.barcodes import resolve_code

    hit = await resolve_code(db, f"farmos:{kind}:{token}")
    if not hit:
        hit = await resolve_code(db, token)
    if not hit:
        raise HTTPException(404, f"Unknown {kind} code")
    row = hit["row"]
    found = hit["kind"]
    if found == "printer":
        return {"kind": "printer", "id": str(row.id), "name": row.name, "public_code": row.public_code, "path": f"/printers/{row.id}"}
    if found == "spool":
        return {
            "kind": "spool",
            "id": str(row.id),
            "name": row.name,
            "public_code": row.public_code,
            "material": row.material,
            "color": row.color,
            "remaining_weight_g": row.remaining_weight_g,
            "path": f"/filament/spools/{row.id}",
        }
    if found == "product":
        return {
            "kind": "product",
            "id": str(row.id),
            "name": f"{row.manufacturer} {row.material} {row.color}",
            "barcode_id": row.barcode_id,
            "path": f"/filament/products/{row.id}?add=1",
        }
    if found == "bin":
        return {"kind": "bin", "id": str(row.id), "name": row.name, "public_code": row.public_code, "path": f"/inventory/bins/{row.id}"}
    if found == "job":
        return {"kind": "job", "id": str(row.id), "path": "/queue"}
    if found == "order":
        return {"kind": "order", "id": str(row.id), "name": row.reference, "public_code": row.public_code, "path": f"/packing/{row.id}"}
    if found == "batch":
        return {"kind": "batch", "id": str(row.id), "name": row.batch_code, "path": f"/production/{row.id}"}
    if found == "kit":
        return {"kind": "kit", "id": str(row.id), "name": row.public_code, "path": f"/kits/{row.id}"}
    if found == "hardware":
        return {"kind": "hardware", "id": str(row.id), "name": row.name, "path": "/hardware"}
    raise HTTPException(404, "Unknown QR kind")
