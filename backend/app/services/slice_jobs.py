"""Redis-backed slice jobs. The worker process runs PrusaSlicer; uvicorn does not."""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import (
    FilamentSpool,
    GCodeFile,
    GCodePrinterCompat,
    JobStatus,
    Part,
    Printer,
    PrintJob,
    ProductionRun,
    ProductionRunItem,
    ProductionRunStatus,
    SliceJob,
    SlicerProfile,
    StlFile,
    utcnow,
)
from app.services.gcode_meta import parse_gcode_file
from app.services.plate_pack import PackResult, validate_plate
from app.services.printer_geometry import usable_bed
from app.services.queue import next_queue_position
from app.services.slicer_cli import SlicerCliError, run_prusa_slicer
from app.services.slicer_cost import plate_cost, spool_insufficient
from app.services.slicer_estimate import grams_from_slicer_meta
from app.services.slicer_filename import sliced_gcode_filename
from app.services.slicer_ini import build_ini_file
from app.services.stl import assemble_packed_stl
from app.util import new_qr_token

logger = logging.getLogger("farmos.slicer")

QUEUE_KEY_DEFAULT = "farmos:slicer:jobs"


async def enqueue_redis(job_id: UUID) -> None:
    settings = get_settings()
    try:
        from redis.asyncio import Redis

        redis = Redis.from_url(settings.redis_url)
        await redis.rpush(settings.slicer_queue_key, str(job_id))
        await redis.aclose()
    except Exception:
        logger.warning("Redis enqueue failed for slice job %s — worker may pick it up from DB", job_id)


async def copy_profile_on_write(db: AsyncSession, profile: SlicerProfile, updates: dict) -> SlicerProfile:
    """Never mutate a profile row that historical jobs already used."""
    used = (
        await db.execute(select(SliceJob.id).where(SliceJob.profile_id == profile.id).limit(1))
    ).first()
    data = {
        "family_id": profile.family_id,
        "name": profile.name,
        "material": profile.material,
        "nozzle_mm": profile.nozzle_mm,
        "density_g_cm3": profile.density_g_cm3,
        "layer_height_mm": profile.layer_height_mm,
        "first_layer_height_mm": profile.first_layer_height_mm,
        "perimeters": profile.perimeters,
        "infill_percent": profile.infill_percent,
        "nozzle_temp_c": profile.nozzle_temp_c,
        "bed_temp_c": profile.bed_temp_c,
        "brim_width_mm": profile.brim_width_mm,
        "support_enabled": profile.support_enabled,
        "print_speed_mm_s": profile.print_speed_mm_s,
        "compatible_printer_ids": list(profile.compatible_printer_ids or []),
        "settings_json": dict(profile.settings_json or {}),
        "notes": profile.notes,
    }
    data.update(updates)
    if not used:
        for key, value in data.items():
            setattr(profile, key, value)
        return profile
    latest = (
        await db.execute(
            select(SlicerProfile)
            .where(SlicerProfile.family_id == profile.family_id)
            .order_by(SlicerProfile.version.desc())
        )
    ).scalars().first()
    profile.is_archived = True
    nxt = SlicerProfile(
        family_id=profile.family_id,
        version=(latest.version if latest else profile.version) + 1,
        **data,
    )
    db.add(nxt)
    await db.flush()
    return nxt


async def process_slice_job(db: AsyncSession, job_id: UUID) -> SliceJob:
    job = await db.get(SliceJob, job_id)
    if not job:
        raise RuntimeError(f"slice job {job_id} missing")
    if job.status == "completed":
        return job
    if job.status == "slicing" and job.started_at:
        age = (utcnow() - job.started_at).total_seconds()
        if age < 45:
            return job
    job.status = "slicing"
    job.started_at = utcnow()
    job.error_message = ""
    await db.commit()

    stl = await db.get(StlFile, job.stl_file_id) if job.stl_file_id else None
    printer = await db.get(Printer, job.printer_id) if job.printer_id else None
    profile = await db.get(SlicerProfile, job.profile_id) if job.profile_id else None
    if not stl or not printer or not profile:
        job.status = "failed"
        job.error_message = "Slice job is missing the STL, printer, or profile."
        job.completed_at = utcnow()
        await db.commit()
        return job
    if not stl.stored_path or not Path(stl.stored_path).is_file():
        job.status = "failed"
        job.error_message = "The STL file is missing from disk. Re-upload the model."
        job.completed_at = utcnow()
        await db.commit()
        return job

    settings = get_settings()
    settings.slicer_tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f"farmos-slice-{job.id}-", dir=str(settings.slicer_tmp_dir)))
    try:
        source = Path(stl.stored_path).read_bytes()
        packed_stl = tmp / "plate.stl"
        placements = (job.plate_json or {}).get("placed") or []
        if placements and len(placements) > 1:
            assemble_packed_stl(source, placements, packed_stl)
            if packed_stl.stat().st_size < 84:
                packed_stl.write_bytes(source)
        else:
            packed_stl.write_bytes(source)
        ini_path = tmp / "profile.ini"
        build_ini_file(ini_path, printer, profile)
        out_gcode = tmp / "plate.gcode"
        produced = run_prusa_slicer(ini_path, packed_stl, out_gcode)
        raw = produced.read_bytes()
        meta = parse_gcode_file(produced)
        density = float(job.density_g_cm3 or profile.density_g_cm3 or 1.27)
        diameter = float(printer.filament_diameter_mm or 1.75)
        grams, length_mm, volume_cm3 = grams_from_slicer_meta(meta, density, diameter)
        if grams is None:
            job.status = "failed"
            job.error_message = (
                "PrusaSlicer wrote G-code but FarmOS could not read filament usage from the comments."
            )
            job.completed_at = utcnow()
            await db.commit()
            return job
        seconds = int(meta.get("estimated_time_seconds") or 0)
        if seconds <= 0:
            job.status = "failed"
            job.error_message = (
                "PrusaSlicer wrote G-code but FarmOS could not read sliced print time from the comments."
            )
            job.completed_at = utcnow()
            await db.commit()
            return job

        part = await db.get(Part, job.part_id or stl.part_id) if (job.part_id or stl.part_id) else None
        sku = part.sku if part else stl.filename
        name = part.name if part else None
        existing = (
            await db.execute(
                select(GCodeFile)
                .where(GCodeFile.part_id == (part.id if part else None), GCodeFile.sliced_printer_id == printer.id)
                .order_by(GCodeFile.version.desc())
            )
        ).scalars().first()
        version = (existing.version + 1) if existing else 1
        if existing:
            existing.is_archived = True
        filename = sliced_gcode_filename(sku, name, job.quantity, printer.name, version)
        dest = settings.gcode_dir / filename
        n = 2
        while dest.exists():
            dest = settings.gcode_dir / sliced_gcode_filename(sku, name, job.quantity, printer.name, version + n)
            n += 1
        dest.write_bytes(raw)
        spool = None
        if printer.assigned_spool_id:
            spool = await db.get(FilamentSpool, printer.assigned_spool_id)
        cost = await plate_cost(
            db,
            grams=grams,
            seconds=seconds,
            quantity=job.quantity,
            printer=printer,
            spool=spool,
            profile=profile,
            material=job.material or profile.material,
        )
        bed_x, bed_y, _z = usable_bed(printer)
        gcode = GCodeFile(
            filename=filename,
            stored_path=str(dest),
            part_id=part.id if part else stl.part_id,
            quantity_per_file=max(1, job.quantity),
            material=job.material or profile.material,
            estimated_time_seconds=seconds,
            estimated_filament_grams=grams,
            version=version,
            notes=(
                f"Sliced with PrusaSlicer for {printer.name}, profile {profile.name} v{profile.version}, "
                f"{job.quantity} copies, {job.spacing_mm:g} mm spacing."
            ),
            file_size_bytes=len(raw),
            slicer=str(meta.get("slicer") or "PrusaSlicer"),
            slicer_profile=f"{profile.name} v{profile.version}",
            nozzle_mm=profile.nozzle_mm,
            layer_height_mm=profile.layer_height_mm,
            min_bed_x_mm=bed_x,
            min_bed_y_mm=bed_y,
            required_nozzle_mm=profile.nozzle_mm,
            stl_file_id=stl.id,
            slicer_profile_id=profile.id,
            slicer_profile_version=profile.version,
            sliced_printer_id=printer.id,
            plate_json=job.plate_json or {},
            filament_length_mm=length_mm,
            filament_volume_cm3=volume_cm3,
            density_g_cm3=density,
        )
        db.add(gcode)
        await db.flush()
        db.add(GCodePrinterCompat(gcode_id=gcode.id, printer_id=printer.id))
        job.gcode_file_id = gcode.id
        job.sliced_time_seconds = seconds
        job.filament_grams = grams
        job.filament_length_mm = length_mm
        job.filament_volume_cm3 = volume_cm3
        job.material_cost = cost.get("filament_cost")
        job.status = "completed"
        job.completed_at = utcnow()
        await db.commit()
        return job
    except SlicerCliError as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.completed_at = utcnow()
        await db.commit()
        return job
    except Exception:
        logger.exception("slice job %s failed", job.id)
        job.status = "failed"
        job.error_message = "Slicing failed unexpectedly. Check slicer-worker logs."
        job.completed_at = utcnow()
        await db.commit()
        return job
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def waiting_job_ids(db: AsyncSession) -> list[UUID]:
    rows = (
        await db.execute(select(SliceJob.id).where(SliceJob.status == "waiting").order_by(SliceJob.created_at))
    ).scalars().all()
    return list(rows)


async def enqueue_print_from_slice(
    db: AsyncSession,
    job: SliceJob,
    *,
    override_filament: bool = False,
    printer_id: UUID | None = None,
) -> dict:
    if job.status != "completed" or not job.gcode_file_id:
        return {"ok": False, "error": "Slice is not finished. Wait for PrusaSlicer to complete."}
    gcode = (
        await db.execute(
            select(GCodeFile).options(selectinload(GCodeFile.part)).where(GCodeFile.id == job.gcode_file_id)
        )
    ).scalar_one_or_none()
    if not gcode:
        return {"ok": False, "error": "Sliced G-code is missing from the library."}
    printer = await db.get(Printer, printer_id or job.printer_id)
    if not printer:
        return {"ok": False, "error": "Printer not found."}
    spool = await db.get(FilamentSpool, printer.assigned_spool_id) if printer.assigned_spool_id else None
    check = spool_insufficient(spool, float(job.filament_grams or gcode.estimated_filament_grams or 0))
    if not check["ok"] and not override_filament:
        check["ok"] = False
        check["blocked"] = True
        return check
    item = None
    if job.production_run_item_id:
        item = await db.get(ProductionRunItem, job.production_run_item_id)
    pos = await next_queue_position(db)
    print_job = PrintJob(
        production_run_id=job.production_run_id,
        production_run_item_id=job.production_run_item_id,
        gcode_file_id=gcode.id,
        part_id=job.part_id or gcode.part_id,
        assigned_printer_id=printer.id,
        status=JobStatus.queued,
        queue_position=pos,
        quantity_produced=gcode.quantity_per_file,
        estimated_filament_grams=gcode.estimated_filament_grams,
        estimated_time_seconds=gcode.estimated_time_seconds,
        filament_required_g=gcode.estimated_filament_grams,
        filament_available_g=float(spool.remaining_weight_g) if spool else 0,
        filament_override=bool(override_filament),
        spool_id=spool.id if spool else None,
        slice_job_id=job.id,
        qr_token=new_qr_token(),
    )
    db.add(print_job)
    if item:
        run = await db.get(ProductionRun, item.production_run_id) if item.production_run_id else None
        if run and run.status == ProductionRunStatus.draft:
            run.status = ProductionRunStatus.queued
    await db.flush()
    return {
        "ok": True,
        "print_job_id": str(print_job.id),
        "gcode_file_id": str(gcode.id),
        "filename": gcode.filename,
        "filament": check,
    }


def pack_result_from_json(data: dict) -> PackResult:
    from app.services.plate_pack import PlacedPart

    placed = [
        PlacedPart(
            index=int(p.get("index") or i),
            x=float(p.get("x") or 0),
            y=float(p.get("y") or 0),
            w=float(p.get("w") or 0),
            h=float(p.get("h") or 0),
            rotation_z=float(p.get("rotation_z") or 0),
            stl_id=p.get("stl_id"),
        )
        for i, p in enumerate(data.get("placed") or [])
    ]
    return PackResult(
        placed=placed,
        quantity=int(data.get("quantity") or len(placed)),
        spacing_mm=float(data.get("spacing_mm") or 6),
        utilisation=float(data.get("utilisation") or 0),
        max_quantity=int(data.get("max_quantity") or len(placed)),
        bed_w=float(data.get("bed_w") or 0),
        bed_h=float(data.get("bed_h") or 0),
        part_w=float(data.get("part_w") or 0),
        part_h=float(data.get("part_h") or 0),
        brim_mm=float(data.get("brim_mm") or 0),
        warnings=list(data.get("warnings") or []),
        keepouts=list(data.get("keepouts") or []),
    )


def geometric_errors(plate_json: dict) -> list[str]:
    if not plate_json:
        return ["Plate has no packed parts."]
    return validate_plate(pack_result_from_json(plate_json))
