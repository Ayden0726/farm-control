"""Slicer vs actual duration — scheduling calibration only, never rewrites G-code."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GCodeFile, PrintJob, Printer, SlicerDurationStat, SlicerProfile


def _key(printer_id: UUID | None, material: str, nozzle: float | None, family: UUID | None) -> dict:
    return {
        "printer_id": printer_id,
        "material": (material or "").upper(),
        "nozzle_mm": round(float(nozzle), 3) if nozzle else None,
        "profile_family_id": family,
    }


async def record_actual(db: AsyncSession, job: PrintJob, printer: Printer, actual_seconds: int) -> None:
    if actual_seconds < 30 or not job.estimated_time_seconds:
        return
    gcode = job.gcode_file
    if gcode is None and job.gcode_file_id:
        gcode = await db.get(GCodeFile, job.gcode_file_id)
    if not gcode:
        return
    family = None
    if gcode.slicer_profile_id:
        profile = await db.get(SlicerProfile, gcode.slicer_profile_id)
        family = profile.family_id if profile else None
    material = (gcode.material or "").upper()
    nozzle = gcode.nozzle_mm or gcode.required_nozzle_mm or printer.nozzle_diameter_mm
    stmt = select(SlicerDurationStat).where(
        SlicerDurationStat.printer_id == printer.id,
        SlicerDurationStat.material == material,
    )
    rows = (await db.execute(stmt)).scalars().all()
    row = None
    for candidate in rows:
        if (candidate.nozzle_mm or None) == (round(float(nozzle), 3) if nozzle else None) and (
            candidate.profile_family_id == family
        ):
            row = candidate
            break
    if row is None:
        row = SlicerDurationStat(
            printer_id=printer.id,
            material=material,
            nozzle_mm=round(float(nozzle), 3) if nozzle else None,
            profile_family_id=family,
        )
        db.add(row)
    row.sliced_seconds += float(job.estimated_time_seconds)
    row.actual_seconds += float(actual_seconds)
    row.sample_count += 1
    if row.sliced_seconds > 0:
        row.calibration_multiplier = max(0.4, min(2.5, row.actual_seconds / row.sliced_seconds))


async def scheduling_multiplier(
    db: AsyncSession,
    printer: Printer | None,
    material: str | None,
    nozzle_mm: float | None,
    profile: SlicerProfile | None,
) -> float:
    """Apply to planner/queue ETAs only. Never rewrite G-code or sliced metadata."""
    if printer is None:
        return 1.0
    stmt = select(SlicerDurationStat).where(SlicerDurationStat.printer_id == printer.id)
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return 1.0
    material_u = (material or "").upper()
    family = profile.family_id if profile else None
    exact = [
        r
        for r in rows
        if r.material == material_u
        and (not nozzle_mm or r.nozzle_mm is None or abs((r.nozzle_mm or 0) - nozzle_mm) < 0.06)
        and (family is None or r.profile_family_id == family)
        and r.sample_count >= 2
    ]
    if exact:
        return float(exact[0].calibration_multiplier or 1.0)
    by_mat = [r for r in rows if r.material == material_u and r.sample_count >= 3]
    if by_mat:
        return float(by_mat[0].calibration_multiplier or 1.0)
    return 1.0


def live_eta_seconds(
    sliced_seconds: int,
    elapsed_seconds: float,
    progress_percent: float,
    multiplier: float = 1.0,
) -> int:
    sliced = max(1, int(sliced_seconds or 0))
    scale = float(multiplier or 1.0)
    if progress_percent and progress_percent > 1:
        remaining_frac = max(0.0, 1.0 - progress_percent / 100.0)
        return int(max(0, sliced * scale * remaining_frac))
    remaining = sliced * scale - max(0.0, elapsed_seconds)
    return int(max(0, remaining))
