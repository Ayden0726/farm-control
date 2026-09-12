from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters import adapter_names, build_adapter
from app.db import get_db
from app.deps import get_current_user
from app.models import (
    FilamentSpool,
    FilamentTransaction,
    GCodePrinterCompat,
    JobStatus,
    MaintenanceLog,
    PrintJob,
    Printer,
    PrinterAdapterType,
    PrinterNotificationPreference,
    PrinterStatus,
    ProductionRunPrinter,
    StorageLocation,
    User,
    utcnow,
)
from app.schemas import PrinterIn, PrinterOut, PrinterUpdate
from app.security import encrypt_secret, decrypt_secret
from app.serialize import printer_out
from app.services.printer_connect import normalize_base_url, probe_adapter, raise_if_offline
from app.util import new_qr_token

router = APIRouter(prefix="/printers", tags=["printers"])


async def _load_printer(db: AsyncSession, printer_id: UUID) -> Printer:
    printer = (
        await db.execute(
            select(Printer)
            .options(selectinload(Printer.assigned_spool), selectinload(Printer.maintenance_logs))
            .where(Printer.id == printer_id)
        )
    ).scalar_one_or_none()
    if not printer:
        raise HTTPException(404, "Printer not found")
    return printer


async def _busy_message(db: AsyncSession, printer: Printer) -> str | None:
    if printer.status in {PrinterStatus.printing, PrinterStatus.paused}:
        return "This printer is still printing. Wait for it to finish, or cancel the job, then try again."
    active = (
        await db.execute(
            select(PrintJob.id).where(
                or_(PrintJob.assigned_printer_id == printer.id, PrintJob.actual_printer_id == printer.id),
                PrintJob.status.in_([JobStatus.printing, JobStatus.paused]),
            )
        )
    ).first()
    if active:
        return "This printer has an active job. Finish or cancel that job first."
    return None


async def _release_queued_jobs(db: AsyncSession, printer: Printer) -> int:
    result = await db.execute(
        update(PrintJob)
        .where(
            PrintJob.assigned_printer_id == printer.id,
            PrintJob.status.in_([JobStatus.queued, JobStatus.held]),
        )
        .values(assigned_printer_id=None)
    )
    return result.rowcount or 0


async def _unassign_spool(db: AsyncSession, printer: Printer) -> None:
    if printer.assigned_spool_id:
        spool = await db.get(FilamentSpool, printer.assigned_spool_id)
        if spool:
            spool.assigned_printer_id = None
        printer.assigned_spool_id = None


async def _retire_printer(db: AsyncSession, printer: Printer) -> None:
    busy = await _busy_message(db, printer)
    if busy:
        raise HTTPException(400, busy)
    printer.is_enabled = False
    printer.current_job_id = None
    extra = dict(printer.extra_config or {})
    extra.setdefault("sim", {})["status"] = "idle"
    printer.extra_config = extra
    if printer.status not in {PrinterStatus.waiting_for_bed_clear, PrinterStatus.error}:
        printer.status = PrinterStatus.offline
    await _release_queued_jobs(db, printer)
    await _unassign_spool(db, printer)


async def _restore_printer(db: AsyncSession, printer: Printer) -> None:
    printer.is_enabled = True
    if printer.status == PrinterStatus.offline:
        printer.last_error = None


@router.get("/adapters")
async def list_adapters(_: User = Depends(get_current_user)) -> dict:
    return {
        "adapters": adapter_names(),
        "notes": {
            "octoprint": "OctoPrint REST API (CR-6 Max and other OctoPrint hosts). Provide URL + API key.",
            "moonraker": "Klipper via Moonraker. Provide the Moonraker base URL.",
            "creality": "Creality K1 Max / K2 Pro. Uses Moonraker (often port 4408) with Creality HTTP fallback.",
            "simulated": "Virtual printer for development and shop-floor demos. No hardware required.",
        },
    }


@router.get("", response_model=list[PrinterOut])
async def list_printers(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (
        await db.execute(select(Printer).options(selectinload(Printer.assigned_spool)).order_by(Printer.name))
    ).scalars().all()
    return [printer_out(p) for p in rows]


@router.post("/test")
async def test_printer_connection(payload: PrinterIn, _: User = Depends(get_current_user)) -> dict:
    result = await probe_adapter(
        payload.adapter_type,
        name=payload.name,
        base_url=payload.base_url,
        api_key=payload.api_key,
        extra=payload.extra_config,
    )
    if not result.ok:
        raise_if_offline(result)
    return {
        "ok": True,
        "status": result.status,
        "message": "Connection verified. The printer responded.",
    }


@router.post("", response_model=PrinterOut)
async def create_printer(
    payload: PrinterIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    url = normalize_base_url(payload.base_url)
    result = await probe_adapter(
        payload.adapter_type,
        name=payload.name,
        base_url=url,
        api_key=payload.api_key,
        extra=payload.extra_config,
    )
    raise_if_offline(result)
    snap = result.snapshot
    status = PrinterStatus.idle
    if payload.adapter_type != "simulated":
        if snap and snap.status in PrinterStatus._value2member_map_:
            status = PrinterStatus(snap.status)
        else:
            status = PrinterStatus.idle
    printer = Printer(
        name=payload.name,
        model=payload.model,
        adapter_type=PrinterAdapterType(payload.adapter_type),
        base_url=url,
        api_key_encrypted=encrypt_secret(payload.api_key) if payload.api_key else None,
        extra_config=payload.extra_config,
        is_enabled=payload.is_enabled,
        assigned_spool_id=payload.assigned_spool_id,
        maintenance_interval_hours=payload.maintenance_interval_hours,
        maintenance_notes=payload.maintenance_notes,
        status=status,
        nozzle_temp=snap.nozzle_temp if snap else 0,
        bed_temp=snap.bed_temp if snap else 0,
        target_nozzle=snap.target_nozzle if snap else 0,
        target_bed=snap.target_bed if snap else 0,
        last_seen_at=utcnow() if result.ok else None,
        qr_token=new_qr_token(),
        public_code=None,
        build_x_mm=payload.build_x_mm,
        build_y_mm=payload.build_y_mm,
        build_z_mm=payload.build_z_mm,
        nozzle_diameter_mm=payload.nozzle_diameter_mm,
        nozzle_material=payload.nozzle_material or "",
        supported_materials=payload.supported_materials or [],
        max_nozzle_temp_c=payload.max_nozzle_temp_c,
        max_bed_temp_c=payload.max_bed_temp_c,
        build_plate_type=payload.build_plate_type or "",
        slicer_profile=payload.slicer_profile or "",
        camera_snapshot_url=payload.camera_snapshot_url or "",
        camera_stream_url=payload.camera_stream_url or "",
        unattended_mode=payload.unattended_mode or "allowed",
        avg_power_watts=payload.avg_power_watts or 180,
        machine_rate_per_hour=payload.machine_rate_per_hour or 0,
    )
    if payload.camera_auth:
        printer.camera_auth_encrypted = encrypt_secret(payload.camera_auth)
    db.add(printer)
    await db.flush()
    from app.services.barcodes import printer_public_code, unique_public_code

    printer.public_code = await unique_public_code(db, Printer, "public_code", printer_public_code(printer.name))
    await db.commit()
    printer = await _load_printer(db, printer.id)
    return printer_out(printer)


@router.get("/{printer_id}", response_model=PrinterOut)
async def get_printer(
    printer_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    return printer_out(await _load_printer(db, printer_id))


@router.patch("/{printer_id}", response_model=PrinterOut)
async def update_printer(
    printer_id: UUID,
    payload: PrinterUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    printer = await _load_printer(db, printer_id)
    data = payload.model_dump(exclude_unset=True)
    api_key = data.pop("api_key", None)
    adapter_type = data.pop("adapter_type", None)
    enabled = data.pop("is_enabled", None)
    camera_auth = data.pop("camera_auth", None)
    if "base_url" in data and data["base_url"]:
        data["base_url"] = normalize_base_url(data["base_url"])
    connection_changed = any(k in data for k in ("base_url", "extra_config")) or api_key is not None or adapter_type is not None
    for key, value in data.items():
        setattr(printer, key, value)
    if adapter_type:
        printer.adapter_type = PrinterAdapterType(adapter_type)
    if api_key:
        printer.api_key_encrypted = encrypt_secret(api_key)
    if camera_auth:
        printer.camera_auth_encrypted = encrypt_secret(camera_auth)
    if enabled is False:
        await _retire_printer(db, printer)
    elif enabled is True:
        await _restore_printer(db, printer)
    if connection_changed and printer.adapter_type.value != "simulated":
        key_to_try = api_key if api_key else decrypt_secret(printer.api_key_encrypted)
        result = await probe_adapter(
            printer.adapter_type.value,
            name=printer.name,
            base_url=printer.base_url,
            api_key=key_to_try,
            extra=printer.extra_config,
        )
        raise_if_offline(result)
        snap = result.snapshot
        printer.last_seen_at = utcnow()
        printer.last_error = None
        if snap:
            printer.nozzle_temp = snap.nozzle_temp
            printer.bed_temp = snap.bed_temp
            if printer.status != PrinterStatus.waiting_for_bed_clear and snap.status in PrinterStatus._value2member_map_:
                printer.status = PrinterStatus(snap.status)
    await db.commit()
    return printer_out(await _load_printer(db, printer.id))


@router.post("/{printer_id}/retire", response_model=PrinterOut)
async def retire_printer(
    printer_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    printer = await _load_printer(db, printer_id)
    if not printer.is_enabled:
        return printer_out(printer)
    await _retire_printer(db, printer)
    await db.commit()
    return printer_out(await _load_printer(db, printer.id))


@router.post("/{printer_id}/restore", response_model=PrinterOut)
async def restore_printer(
    printer_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    printer = await _load_printer(db, printer_id)
    await _restore_printer(db, printer)
    await db.commit()
    return printer_out(await _load_printer(db, printer.id))


@router.delete("/{printer_id}")
async def delete_printer(
    printer_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    printer = await _load_printer(db, printer_id)
    busy = await _busy_message(db, printer)
    if busy:
        raise HTTPException(400, busy)
    await _unassign_spool(db, printer)
    await _release_queued_jobs(db, printer)
    jobs = (
        await db.execute(
            select(PrintJob).where(
                or_(PrintJob.assigned_printer_id == printer.id, PrintJob.actual_printer_id == printer.id)
            )
        )
    ).scalars().all()
    for job in jobs:
        if job.assigned_printer_id == printer.id:
            job.assigned_printer_id = None
        if job.actual_printer_id == printer.id:
            job.actual_printer_id = None
    await db.execute(
        update(FilamentSpool).where(FilamentSpool.assigned_printer_id == printer.id).values(assigned_printer_id=None)
    )
    await db.execute(
        update(FilamentTransaction).where(FilamentTransaction.printer_id == printer.id).values(printer_id=None)
    )
    await db.execute(
        update(StorageLocation).where(StorageLocation.printer_id == printer.id).values(printer_id=None)
    )
    await db.execute(delete(ProductionRunPrinter).where(ProductionRunPrinter.printer_id == printer.id))
    await db.execute(delete(GCodePrinterCompat).where(GCodePrinterCompat.printer_id == printer.id))
    await db.execute(delete(MaintenanceLog).where(MaintenanceLog.printer_id == printer.id))
    await db.execute(
        delete(PrinterNotificationPreference).where(PrinterNotificationPreference.printer_id == printer.id)
    )
    printer.current_job_id = None
    await db.flush()
    await db.delete(printer)
    await db.commit()
    return {"ok": True, "deleted": True, "name": printer.name}


@router.post("/{printer_id}/bed-cleared", response_model=PrinterOut)
async def bed_cleared(
    printer_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    printer = await _load_printer(db, printer_id)
    if printer.status != PrinterStatus.waiting_for_bed_clear:
        raise HTTPException(400, "Printer is not waiting for bed clearance")
    printer.status = PrinterStatus.idle
    printer.current_file = None
    printer.progress_percent = 0
    printer.current_job_id = None
    extra = dict(printer.extra_config or {})
    extra.setdefault("sim", {})["status"] = "idle"
    printer.extra_config = extra
    await db.commit()
    return printer_out(await _load_printer(db, printer.id))


@router.post("/{printer_id}/refresh", response_model=PrinterOut)
async def refresh_printer(
    printer_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    printer = await _load_printer(db, printer_id)
    adapter = build_adapter(printer)
    snap = await adapter.get_status()
    printer.last_seen_at = utcnow()
    printer.nozzle_temp = snap.nozzle_temp
    printer.bed_temp = snap.bed_temp
    printer.target_nozzle = snap.target_nozzle
    printer.target_bed = snap.target_bed
    if printer.status != PrinterStatus.waiting_for_bed_clear:
        if not snap.online:
            printer.status = PrinterStatus.offline
        elif snap.status == "error":
            printer.status = PrinterStatus.error
        elif printer.current_job_id:
            pass
        else:
            printer.status = PrinterStatus(snap.status) if snap.status in PrinterStatus._value2member_map_ else printer.status
    printer.last_error = snap.error
    await db.commit()
    return printer_out(await _load_printer(db, printer.id))


@router.post("/{printer_id}/assign-spool", response_model=PrinterOut)
async def assign_spool(
    printer_id: UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from app.services.filament import assign_spool_to_printer

    printer = await _load_printer(db, printer_id)
    spool_id = payload.get("spool_id")
    if spool_id:
        spool = await db.get(FilamentSpool, UUID(str(spool_id)))
        if not spool:
            raise HTTPException(404, "Spool not found")
        await assign_spool_to_printer(db, printer, spool, actor="operator")
    else:
        if printer.assigned_spool_id:
            spool = await db.get(FilamentSpool, printer.assigned_spool_id)
            if spool:
                spool.assigned_printer_id = None
        printer.assigned_spool_id = None
    await db.commit()
    return printer_out(await _load_printer(db, printer.id))


@router.get("/{printer_id}/camera")
async def printer_camera(printer_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    from fastapi.responses import Response

    from app.services.camera import fetch_snapshot, latest_snapshot_path

    printer = await _load_printer(db, printer_id)
    data, status = await fetch_snapshot(printer)
    if data:
        return Response(content=data, media_type="image/jpeg", headers={"X-Camera-Status": status})
    latest = latest_snapshot_path(printer)
    if latest:
        return Response(content=latest.read_bytes(), media_type="image/jpeg", headers={"X-Camera-Status": "stale"})
    raise HTTPException(404, "No camera snapshot available")


@router.post("/{printer_id}/downtime")
async def start_downtime(
    printer_id: UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models import PrinterDowntime
    from app.services.audit import record_audit

    printer = await _load_printer(db, printer_id)
    reason = str(payload.get("reason") or "unknown")
    notes = str(payload.get("notes") or "")
    open_row = (
        await db.execute(
            select(PrinterDowntime).where(
                PrinterDowntime.printer_id == printer.id, PrinterDowntime.ended_at.is_(None)
            )
        )
    ).scalars().first()
    if not open_row:
        db.add(PrinterDowntime(printer_id=printer.id, reason=reason, notes=notes))
    printer.current_downtime_reason = reason
    await record_audit(
        db,
        action="printer_downtime",
        entity_type="printer",
        entity_id=str(printer.id),
        new={"reason": reason, "notes": notes},
        actor=user.email,
    )
    await db.commit()
    return printer_out(await _load_printer(db, printer.id))


@router.post("/{printer_id}/downtime/end", response_model=PrinterOut)
async def end_downtime(
    printer_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    from app.models import PrinterDowntime

    printer = await _load_printer(db, printer_id)
    open_row = (
        await db.execute(
            select(PrinterDowntime).where(
                PrinterDowntime.printer_id == printer.id, PrinterDowntime.ended_at.is_(None)
            )
        )
    ).scalars().first()
    if open_row:
        open_row.ended_at = utcnow()
    printer.current_downtime_reason = None
    await db.commit()
    return printer_out(await _load_printer(db, printer.id))


@router.post("/{printer_id}/redistribute")
async def redistribute(
    printer_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    from app.services.audit import record_audit
    from app.services.planner import redistribute_printer

    result = await redistribute_printer(db, printer_id)
    await record_audit(
        db,
        action="queue_redistribute",
        entity_type="printer",
        entity_id=str(printer_id),
        new={"moved": len(result.get("moved") or []), "skipped": len(result.get("skipped") or [])},
        actor=user.email,
    )
    await db.commit()
    return result
