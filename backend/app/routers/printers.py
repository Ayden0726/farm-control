from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters import adapter_names, build_adapter
from app.db import get_db
from app.deps import get_current_user
from app.models import (
    FilamentSpool,
    Printer,
    PrinterAdapterType,
    PrinterStatus,
    PrintJob,
    User,
    utcnow,
)
from app.schemas import PrinterIn, PrinterOut, PrinterUpdate
from app.security import encrypt_secret
from app.serialize import printer_out
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


@router.post("", response_model=PrinterOut)
async def create_printer(
    payload: PrinterIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    printer = Printer(
        name=payload.name,
        model=payload.model,
        adapter_type=PrinterAdapterType(payload.adapter_type),
        base_url=payload.base_url,
        api_key_encrypted=encrypt_secret(payload.api_key) if payload.api_key else None,
        extra_config=payload.extra_config,
        is_enabled=payload.is_enabled,
        assigned_spool_id=payload.assigned_spool_id,
        maintenance_interval_hours=payload.maintenance_interval_hours,
        maintenance_notes=payload.maintenance_notes,
        status=PrinterStatus.idle if payload.adapter_type == "simulated" else PrinterStatus.offline,
        qr_token=new_qr_token(),
        public_code=None,
    )
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
    for key, value in data.items():
        setattr(printer, key, value)
    if adapter_type:
        printer.adapter_type = PrinterAdapterType(adapter_type)
    if api_key:
        printer.api_key_encrypted = encrypt_secret(api_key)
    await db.commit()
    return printer_out(await _load_printer(db, printer.id))


@router.delete("/{printer_id}")
async def delete_printer(
    printer_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    printer = await _load_printer(db, printer_id)
    await db.delete(printer)
    await db.commit()
    return {"ok": True}


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
