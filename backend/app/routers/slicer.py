"""Production slicer API — packing, profiles, and Redis slice jobs."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import (
    BomItem,
    FilamentSpool,
    FinishedPartStock,
    GCodeFile,
    Part,
    PlateLayout,
    Printer,
    Product,
    ProductionRun,
    ProductionRunItem,
    SliceJob,
    SlicerProfile,
    StlFile,
    User,
)
from app.services.plate_pack import (
    DEFAULT_SPACING_MM,
    MIN_SPACING_MM,
    RELIABLE_SPACING_MM,
    candidate_layouts,
    clamp_spacing,
    max_quantity,
    orientation_from_json,
    pack_copies,
    pick_layout,
    plan_plates,
    spacing_hint,
    validate_plate,
)
from app.services.printer_geometry import keepout_aabbs, usable_bed
from app.services.slice_jobs import (
    copy_profile_on_write,
    enqueue_print_from_slice,
    enqueue_redis,
)
from app.services.slicer_compat import auto_select_printer, compatible_printers, printer_slice_issues
from app.services.slicer_cost import plate_cost, spool_insufficient
from app.services.slicer_estimate import pre_slice_estimate
from app.services.slicer_ini import profile_to_ini_dict

router = APIRouter(prefix="/slicer", tags=["slicer"])


class ProfileIn(BaseModel):
    name: str
    material: str = "PETG"
    nozzle_mm: float = 0.4
    density_g_cm3: float = 1.27
    layer_height_mm: float = 0.2
    first_layer_height_mm: float = 0.2
    perimeters: int = 3
    infill_percent: float = 20
    nozzle_temp_c: float = 250
    bed_temp_c: float = 80
    brim_width_mm: float = 0
    support_enabled: bool = False
    print_speed_mm_s: float = 80
    compatible_printer_ids: list[str] = Field(default_factory=list)
    settings_json: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class ProfilePatch(BaseModel):
    name: str | None = None
    material: str | None = None
    nozzle_mm: float | None = None
    density_g_cm3: float | None = None
    layer_height_mm: float | None = None
    first_layer_height_mm: float | None = None
    perimeters: int | None = None
    infill_percent: float | None = None
    nozzle_temp_c: float | None = None
    bed_temp_c: float | None = None
    brim_width_mm: float | None = None
    support_enabled: bool | None = None
    print_speed_mm_s: float | None = None
    compatible_printer_ids: list[str] | None = None
    settings_json: dict[str, Any] | None = None
    notes: str | None = None
    is_archived: bool | None = None


class PackIn(BaseModel):
    stl_id: UUID
    printer_id: UUID | None = None
    profile_id: UUID | None = None
    quantity: int | None = None
    spacing_mm: float = DEFAULT_SPACING_MM
    fill_plate: bool = False
    optimisation_mode: str = "balanced"
    orientation: dict[str, Any] = Field(default_factory=dict)
    placements: list[dict[str, Any]] | None = None
    mixed_stls: list[dict[str, Any]] = Field(default_factory=list)
    confirm_mixed: bool = False


class SliceIn(PackIn):
    material: str | None = None
    production_run_id: UUID | None = None
    production_run_item_id: UUID | None = None
    order_id: UUID | None = None
    fill_until_complete: bool = False
    needed_qty: int | None = None
    printer_ids: list[UUID] = Field(default_factory=list)
    admin_override: bool = False
    use_layout_id: UUID | None = None


class QueueIn(BaseModel):
    override_filament: bool = False
    printer_id: UUID | None = None


class LayoutIn(BaseModel):
    name: str = ""
    notes: str = ""


def _profile_out(row: SlicerProfile) -> dict:
    return {
        "id": str(row.id),
        "family_id": str(row.family_id),
        "name": row.name,
        "version": row.version,
        "is_archived": row.is_archived,
        "material": row.material,
        "nozzle_mm": row.nozzle_mm,
        "density_g_cm3": row.density_g_cm3,
        "layer_height_mm": row.layer_height_mm,
        "first_layer_height_mm": row.first_layer_height_mm,
        "perimeters": row.perimeters,
        "infill_percent": row.infill_percent,
        "nozzle_temp_c": row.nozzle_temp_c,
        "bed_temp_c": row.bed_temp_c,
        "brim_width_mm": row.brim_width_mm,
        "support_enabled": row.support_enabled,
        "print_speed_mm_s": row.print_speed_mm_s,
        "compatible_printer_ids": list(row.compatible_printer_ids or []),
        "settings_json": dict(row.settings_json or {}),
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _job_out(job: SliceJob, extra: dict | None = None) -> dict:
    payload = {
        "id": str(job.id),
        "status": job.status,
        "stl_file_id": str(job.stl_file_id) if job.stl_file_id else None,
        "printer_id": str(job.printer_id) if job.printer_id else None,
        "profile_id": str(job.profile_id) if job.profile_id else None,
        "profile_version": job.profile_version,
        "part_id": str(job.part_id) if job.part_id else None,
        "production_run_id": str(job.production_run_id) if job.production_run_id else None,
        "gcode_file_id": str(job.gcode_file_id) if job.gcode_file_id else None,
        "quantity": job.quantity,
        "spacing_mm": job.spacing_mm,
        "optimisation_mode": job.optimisation_mode,
        "plate_index": job.plate_index,
        "plate_count": job.plate_count,
        "plate_json": job.plate_json or {},
        "error_message": job.error_message,
        "sliced_time_seconds": job.sliced_time_seconds,
        "filament_length_mm": job.filament_length_mm,
        "filament_volume_cm3": job.filament_volume_cm3,
        "filament_grams": job.filament_grams,
        "material_cost": job.material_cost,
        "material": job.material,
        "density_g_cm3": job.density_g_cm3,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "sliced_print_time_label": "Sliced Print Time" if job.sliced_time_seconds else None,
    }
    if extra:
        payload.update(extra)
    return payload


async def _load_pack_context(db: AsyncSession, payload: PackIn):
    stl = (
        await db.execute(select(StlFile).options(selectinload(StlFile.part)).where(StlFile.id == payload.stl_id))
    ).scalar_one_or_none()
    if not stl:
        raise HTTPException(404, "STL not found")
    if stl.is_archived:
        raise HTTPException(400, "This STL version is archived. Open the current version.")
    printer = await db.get(Printer, payload.printer_id) if payload.printer_id else None
    if payload.printer_id and not printer:
        raise HTTPException(404, "Printer not found")
    if not printer:
        printer = (await db.execute(select(Printer).order_by(Printer.name))).scalars().first()
        if not printer:
            raise HTTPException(400, "Add a printer before packing a plate.")
    profile = await db.get(SlicerProfile, payload.profile_id) if payload.profile_id else None
    if payload.profile_id and not profile:
        raise HTTPException(404, "Slicer profile not found")
    if not stl.bbox_x_mm or not stl.bbox_y_mm:
        raise HTTPException(400, "This STL has no measured bounding box. Re-upload it.")
    return stl, printer, profile


def _pack_one(stl: StlFile, printer: Printer, profile: SlicerProfile | None, payload: PackIn) -> dict:
    bed_x, bed_y, _z = usable_bed(printer)
    keepouts = keepout_aabbs(printer)
    brim = float(profile.brim_width_mm) if profile else 0.0
    rec = float(stl.recommended_spacing_mm or DEFAULT_SPACING_MM)
    gap = clamp_spacing(payload.spacing_mm, 2.0)
    mode = (payload.optimisation_mode or "balanced").lower()
    if payload.fill_plate:
        if mode in {"maximum_reliability", "reliability"}:
            gap = clamp_spacing(max(gap, RELIABLE_SPACING_MM))
        elif mode in {"maximum_parts", "max_parts"}:
            gap = clamp_spacing(min(gap, max(MIN_SPACING_MM, rec - 2)))
    rules = orientation_from_json(payload.orientation or stl.orientation_json)
    max_q = max_quantity(
        float(stl.bbox_x_mm),
        float(stl.bbox_y_mm),
        bed_x,
        bed_y,
        gap,
        brim,
        keepouts,
        rules,
    )
    want = max_q if payload.fill_plate or payload.quantity is None else max(0, int(payload.quantity))
    if payload.placements:
        from app.services.plate_pack import PackResult, PlacedPart

        placed = [
            PlacedPart(
                index=i,
                x=float(p["x"]),
                y=float(p["y"]),
                w=float(p.get("w") or (stl.bbox_y_mm if p.get("rotation_z") in (90, 270) else stl.bbox_x_mm)),
                h=float(p.get("h") or (stl.bbox_x_mm if p.get("rotation_z") in (90, 270) else stl.bbox_y_mm)),
                rotation_z=float(p.get("rotation_z") or 0),
                stl_id=str(stl.id),
            )
            for i, p in enumerate(payload.placements)
        ]
        packed = PackResult(
            placed=placed,
            quantity=len(placed),
            spacing_mm=gap,
            utilisation=sum(p.w * p.h for p in placed) / max(bed_x * bed_y, 1),
            max_quantity=max_q,
            bed_w=bed_x,
            bed_h=bed_y,
            part_w=float(stl.bbox_x_mm),
            part_h=float(stl.bbox_y_mm),
            brim_mm=brim,
            keepouts=keepouts,
        )
    else:
        packed = pack_copies(
            float(stl.bbox_x_mm),
            float(stl.bbox_y_mm),
            bed_x,
            bed_y,
            want,
            gap,
            brim,
            keepouts,
            rules,
            str(stl.id),
        )
    errors = validate_plate(packed)
    estimate = pre_slice_estimate(stl, packed.quantity or 1, profile, profile.material if profile else None)
    return {
        "plate": packed.as_json(),
        "max_quantity": packed.max_quantity,
        "spacing_mm": packed.spacing_mm,
        "spacing_hint": spacing_hint(packed.spacing_mm, rec),
        "recommended_spacing_mm": rec,
        "geometric_errors": errors,
        "pre_slice_estimate": estimate,
        "bed": {"usable_x_mm": bed_x, "usable_y_mm": bed_y, "keepouts": keepouts},
    }


@router.get("/profiles")
async def list_profiles(
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(SlicerProfile).order_by(SlicerProfile.name, SlicerProfile.version.desc())
    if not include_archived:
        stmt = stmt.where(SlicerProfile.is_archived.is_(False))
    rows = (await db.execute(stmt)).scalars().all()
    return [_profile_out(r) for r in rows]


@router.post("/profiles")
async def create_profile(
    payload: ProfileIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_perm("production"))
):
    row = SlicerProfile(**payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _profile_out(row)


@router.post("/profiles/{profile_id}/duplicate")
async def duplicate_profile(
    profile_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(require_perm("production"))
):
    src = await db.get(SlicerProfile, profile_id)
    if not src:
        raise HTTPException(404, "Profile not found")
    copy = SlicerProfile(
        name=f"{src.name} copy",
        material=src.material,
        nozzle_mm=src.nozzle_mm,
        density_g_cm3=src.density_g_cm3,
        layer_height_mm=src.layer_height_mm,
        first_layer_height_mm=src.first_layer_height_mm,
        perimeters=src.perimeters,
        infill_percent=src.infill_percent,
        nozzle_temp_c=src.nozzle_temp_c,
        bed_temp_c=src.bed_temp_c,
        brim_width_mm=src.brim_width_mm,
        support_enabled=src.support_enabled,
        print_speed_mm_s=src.print_speed_mm_s,
        compatible_printer_ids=list(src.compatible_printer_ids or []),
        settings_json=dict(src.settings_json or {}),
        notes=src.notes,
    )
    db.add(copy)
    await db.commit()
    await db.refresh(copy)
    return _profile_out(copy)


@router.patch("/profiles/{profile_id}")
async def update_profile(
    profile_id: UUID,
    payload: ProfilePatch,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm("production")),
):
    row = await db.get(SlicerProfile, profile_id)
    if not row:
        raise HTTPException(404, "Profile not found")
    data = payload.model_dump(exclude_unset=True)
    row = await copy_profile_on_write(db, row, data)
    await db.commit()
    await db.refresh(row)
    return _profile_out(row)


@router.post("/pack")
async def pack_plate(payload: PackIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    stl, printer, profile = await _load_pack_context(db, payload)
    packed = _pack_one(stl, printer, profile, payload)
    issues = printer_slice_issues(printer, stl=stl, profile=profile)
    candidates = candidate_layouts(
        float(stl.bbox_x_mm),
        float(stl.bbox_y_mm),
        packed["bed"]["usable_x_mm"],
        packed["bed"]["usable_y_mm"],
        max(1, payload.needed_qty if hasattr(payload, "needed_qty") else packed["max_quantity"] or 1),
        packed["recommended_spacing_mm"],
        float(profile.brim_width_mm) if profile else 0,
        packed["bed"]["keepouts"],
        orientation_from_json(payload.orientation or stl.orientation_json),
    )
    chosen = pick_layout(candidates, payload.optimisation_mode, packed["max_quantity"] or 1)
    layouts = (
        await db.execute(
            select(PlateLayout).where(
                PlateLayout.part_id == stl.part_id,
                PlateLayout.printer_id == printer.id,
                PlateLayout.is_approved.is_(True),
            )
        )
    ).scalars().all() if stl.part_id else []
    return {
        **packed,
        "compatibility": {
            "issues": issues,
            "can_use": not issues,
            "reason": " ".join(issues) if issues else "",
        },
        "candidates": candidates,
        "picked_candidate": chosen,
        "approved_layouts": [
            {
                "id": str(row.id),
                "name": row.name or f"{row.quantity} copies @ {row.spacing_mm:g} mm",
                "quantity": row.quantity,
                "spacing_mm": row.spacing_mm,
                "completed_count": row.completed_count,
                "success_count": row.success_count,
                "fail_count": row.fail_count,
            }
            for row in layouts
        ],
        "mixed_skipped": bool(payload.mixed_stls) and not payload.confirm_mixed,
    }


@router.post("/validate")
async def validate_request(payload: PackIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    stl, printer, profile = await _load_pack_context(db, payload)
    packed = _pack_one(stl, printer, profile, payload)
    issues = printer_slice_issues(printer, stl=stl, profile=profile)
    geo = packed["geometric_errors"]
    return {
        "ok": not geo and not issues,
        "geometric_errors": geo,
        "warnings": issues,
        "block_slice": bool(geo),
        "admin_override_ok": bool(issues) and not geo,
    }


@router.post("/compatibility")
async def compatibility(payload: PackIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    stl, printer, profile = await _load_pack_context(db, payload)
    issues = printer_slice_issues(printer, stl=stl, profile=profile)
    alts = await compatible_printers(db, stl=stl, profile=profile, material=profile.material if profile else None)
    return {
        "can_use": not issues,
        "reason": " ".join(issues) if issues else "",
        "title": "Cannot Use This Printer" if issues else "Compatible",
        "issues": issues,
        "alternatives": [a for a in alts if a["can_use"] and a["printer_id"] != str(printer.id)][:8],
        "admin_override_ok": all("bounding box" not in i.lower() and "height" not in i.lower() for i in issues),
    }


@router.post("/auto-select-printer")
async def auto_select(payload: PackIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    stl, _printer, profile = await _load_pack_context(db, payload)
    packed = _pack_one(stl, _printer, profile, payload)
    grams = float(packed["pre_slice_estimate"]["filament_grams"])
    return await auto_select_printer(
        db, stl=stl, profile=profile, material=profile.material if profile else None, grams=grams
    )


@router.post("/jobs")
async def create_jobs(
    payload: SliceIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_perm("production"))
):
    stl, printer, profile = await _load_pack_context(db, payload)
    if not profile:
        raise HTTPException(400, "Pick a slicer profile before slicing.")
    if stl.bbox_x_mm is None:
        raise HTTPException(400, "Do not slice an unmeasured STL. Re-upload the model.")
    packed = _pack_one(stl, printer, profile, payload)
    geo = packed["geometric_errors"]
    issues = printer_slice_issues(printer, stl=stl, profile=profile)
    if geo:
        raise HTTPException(400, "Plate is not valid: " + " ".join(geo))
    if issues and not payload.admin_override:
        raise HTTPException(
            400,
            "Cannot Use This Printer. " + " ".join(issues),
        )
    if packed["plate"]["quantity"] <= 0:
        raise HTTPException(400, "Nothing fits on this plate. Change spacing, orientation, or printer.")
    printers: list[Printer] = [printer]
    if payload.printer_ids:
        extra = (
            await db.execute(select(Printer).where(Printer.id.in_(payload.printer_ids)))
        ).scalars().all()
        by_id = {p.id: p for p in extra}
        printers = [by_id[i] for i in payload.printer_ids if i in by_id] or [printer]
    needed = payload.needed_qty or packed["plate"]["quantity"]
    created: list[SliceJob] = []
    if payload.fill_until_complete and needed > packed["max_quantity"]:
        counts = plan_plates(needed, packed["max_quantity"], payload.optimisation_mode)
        for index, count in enumerate(counts, start=1):
            target = printers[(index - 1) % len(printers)]
            one = PackIn(
                stl_id=payload.stl_id,
                printer_id=target.id,
                profile_id=profile.id,
                quantity=count,
                spacing_mm=payload.spacing_mm,
                fill_plate=False,
                optimisation_mode=payload.optimisation_mode,
                orientation=payload.orientation,
            )
            plate = _pack_one(stl, target, profile, one)
            # Each printer gets G-code sliced with its own machine profile — never reused.
            job = SliceJob(
                status="waiting",
                stl_file_id=stl.id,
                printer_id=target.id,
                profile_id=profile.id,
                profile_version=profile.version,
                part_id=stl.part_id,
                production_run_id=payload.production_run_id,
                production_run_item_id=payload.production_run_item_id,
                order_id=payload.order_id,
                quantity=plate["plate"]["quantity"],
                spacing_mm=plate["spacing_mm"],
                optimisation_mode=payload.optimisation_mode,
                plate_index=index,
                plate_count=len(counts),
                plate_json=plate["plate"],
                material=payload.material or profile.material,
                density_g_cm3=profile.density_g_cm3,
                admin_override=payload.admin_override,
                created_by=user.email,
            )
            db.add(job)
            created.append(job)
    else:
        job = SliceJob(
            status="waiting",
            stl_file_id=stl.id,
            printer_id=printer.id,
            profile_id=profile.id,
            profile_version=profile.version,
            part_id=stl.part_id,
            production_run_id=payload.production_run_id,
            production_run_item_id=payload.production_run_item_id,
            order_id=payload.order_id,
            quantity=packed["plate"]["quantity"],
            spacing_mm=packed["spacing_mm"],
            optimisation_mode=payload.optimisation_mode,
            plate_index=1,
            plate_count=1,
            plate_json=packed["plate"],
            material=payload.material or profile.material,
            density_g_cm3=profile.density_g_cm3,
            admin_override=payload.admin_override,
            created_by=user.email,
        )
        db.add(job)
        created.append(job)
    await db.flush()
    for job in created:
        await enqueue_redis(job.id)
    await db.commit()
    return {"jobs": [_job_out(j) for j in created], "count": len(created)}


@router.get("/jobs")
async def list_jobs(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(SliceJob).order_by(SliceJob.created_at.desc()).limit(80))).scalars().all()
    return [_job_out(j) for j in rows]


@router.get("/jobs/{job_id}")
async def get_job(job_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    job = await db.get(SliceJob, job_id)
    if not job:
        raise HTTPException(404, "Slice job not found")
    extra: dict[str, Any] = {}
    if job.status == "completed" and job.gcode_file_id:
        gcode = await db.get(GCodeFile, job.gcode_file_id)
        printer = await db.get(Printer, job.printer_id) if job.printer_id else None
        part = await db.get(Part, job.part_id) if job.part_id else None
        spool = await db.get(FilamentSpool, printer.assigned_spool_id) if printer and printer.assigned_spool_id else None
        profile = await db.get(SlicerProfile, job.profile_id) if job.profile_id else None
        cost = await plate_cost(
            db,
            grams=float(job.filament_grams or 0),
            seconds=int(job.sliced_time_seconds or 0),
            quantity=job.quantity,
            printer=printer,
            spool=spool,
            profile=profile,
            material=job.material,
        )
        extra = {
            "gcode_filename": gcode.filename if gcode else None,
            "printer_name": printer.name if printer else None,
            "part_sku": part.sku if part else None,
            "part_name": part.name if part else None,
            "utilisation": (job.plate_json or {}).get("utilisation"),
            "filament_check": spool_insufficient(spool, float(job.filament_grams or 0)),
            "cost": cost,
            "slicer_version": gcode.slicer if gcode else None,
        }
    return _job_out(job, extra)


@router.post("/jobs/{job_id}/approve-queue")
async def approve_queue(
    job_id: UUID,
    payload: QueueIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm("production")),
):
    job = await db.get(SliceJob, job_id)
    if not job:
        raise HTTPException(404, "Slice job not found")
    result = await enqueue_print_from_slice(
        db, job, override_filament=payload.override_filament, printer_id=payload.printer_id
    )
    if not result.get("ok"):
        if result.get("blocked"):
            raise HTTPException(409, result)
        raise HTTPException(400, result.get("error") or "Could not queue this plate")
    await db.commit()
    return result


@router.post("/jobs/{job_id}/save-gcode")
async def save_gcode_only(
    job_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(require_perm("production"))
):
    job = await db.get(SliceJob, job_id)
    if not job or job.status != "completed" or not job.gcode_file_id:
        raise HTTPException(400, "Slice is not finished.")
    gcode = await db.get(GCodeFile, job.gcode_file_id)
    return {"ok": True, "gcode_file_id": str(gcode.id), "filename": gcode.filename}


@router.post("/jobs/{job_id}/reslice")
async def reslice(
    job_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_perm("production"))
):
    src = await db.get(SliceJob, job_id)
    if not src:
        raise HTTPException(404, "Slice job not found")
    job = SliceJob(
        status="waiting",
        stl_file_id=src.stl_file_id,
        printer_id=src.printer_id,
        profile_id=src.profile_id,
        profile_version=src.profile_version,
        part_id=src.part_id,
        production_run_id=src.production_run_id,
        production_run_item_id=src.production_run_item_id,
        order_id=src.order_id,
        quantity=src.quantity,
        spacing_mm=src.spacing_mm,
        optimisation_mode=src.optimisation_mode,
        plate_index=src.plate_index,
        plate_count=src.plate_count,
        plate_json=src.plate_json,
        material=src.material,
        density_g_cm3=src.density_g_cm3,
        created_by=user.email,
    )
    db.add(job)
    await db.flush()
    await enqueue_redis(job.id)
    await db.commit()
    return _job_out(job)


@router.post("/jobs/{job_id}/approve-layout")
async def approve_layout(
    job_id: UUID,
    payload: LayoutIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm("production")),
):
    job = await db.get(SliceJob, job_id)
    if not job or not job.plate_json:
        raise HTTPException(400, "Nothing to save — slice a plate first.")
    layout = PlateLayout(
        name=payload.name or f"{job.quantity} copies",
        part_id=job.part_id,
        stl_file_id=job.stl_file_id,
        printer_id=job.printer_id,
        profile_id=job.profile_id,
        quantity=job.quantity,
        spacing_mm=job.spacing_mm,
        placements_json=job.plate_json,
        notes=payload.notes,
    )
    db.add(layout)
    await db.commit()
    await db.refresh(layout)
    return {"id": str(layout.id), "name": layout.name}


@router.get("/ini-preview/{profile_id}")
async def ini_preview(
    profile_id: UUID,
    printer_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    profile = await db.get(SlicerProfile, profile_id)
    printer = await db.get(Printer, printer_id)
    if not profile or not printer:
        raise HTTPException(404, "Profile or printer not found")
    return {"ini": profile_to_ini_dict(printer, profile)}


@router.get("/production-suggest")
async def production_suggest(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    run = (
        await db.execute(
            select(ProductionRun)
            .options(selectinload(ProductionRun.items).selectinload(ProductionRunItem.part))
            .where(ProductionRun.id == run_id)
        )
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Production run not found")
    suggestions = []
    for item in run.items:
        need = max(0, int(item.required_qty) - int(item.printed_qty or 0) - int(item.passed_qc or 0))
        stock = await db.get(FinishedPartStock, item.part_id)
        available = (stock.quantity_on_hand - stock.quantity_reserved) if stock else 0
        shortage = max(0, need - max(0, available))
        stl = (
            await db.execute(
                select(StlFile)
                .where(StlFile.part_id == item.part_id, StlFile.is_archived.is_(False))
                .order_by(StlFile.production_approved.desc(), StlFile.version.desc())
            )
        ).scalars().first()
        suggestions.append(
            {
                "part_id": str(item.part_id),
                "part_sku": item.part.sku if item.part else None,
                "required_qty": item.required_qty,
                "shortage_qty": shortage,
                "stl_id": str(stl.id) if stl else None,
                "stl_filename": stl.filename if stl else None,
                "production_approved_stl": bool(stl.production_approved) if stl else False,
                "item_id": str(item.id),
            }
        )
    return {"run_id": str(run.id), "run_name": run.name, "items": suggestions}


@router.get("/planner-suggest")
async def planner_suggest(
    product_id: UUID,
    quantity: int = 1,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    bom = (await db.execute(select(BomItem).where(BomItem.product_id == product.id))).scalars().all()
    items = []
    for line in bom:
        if line.is_optional:
            continue
        part = await db.get(Part, line.part_id)
        need = max(1, int(quantity)) * max(1, int(line.quantity))
        stock = await db.get(FinishedPartStock, line.part_id)
        available = (stock.quantity_on_hand - stock.quantity_reserved) if stock else 0
        shortage = max(0, need - max(0, available))
        stl = (
            await db.execute(
                select(StlFile)
                .where(StlFile.part_id == line.part_id, StlFile.is_archived.is_(False), StlFile.production_approved.is_(True))
                .order_by(StlFile.version.desc())
            )
        ).scalars().first()
        if stl is None:
            stl = (
                await db.execute(
                    select(StlFile)
                    .where(StlFile.part_id == line.part_id, StlFile.is_archived.is_(False))
                    .order_by(StlFile.version.desc())
                )
            ).scalars().first()
        items.append(
            {
                "part_id": str(line.part_id),
                "part_sku": part.sku if part else None,
                "bom_qty": line.quantity,
                "needed": need,
                "shortage_qty": shortage,
                "stl_id": str(stl.id) if stl else None,
                "approved_stl": bool(stl and stl.production_approved),
            }
        )
    return {"product_id": str(product.id), "product_sku": product.sku, "items": items}
