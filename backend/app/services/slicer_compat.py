"""Printer / profile / STL compatibility for the production slicer."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FilamentSpool,
    JobStatus,
    Printer,
    PrinterStatus,
    PrintJob,
    SlicerProfile,
    StlFile,
)
from app.services.printer_geometry import usable_bed


def _materials(printer: Printer) -> list[str]:
    raw = printer.supported_materials or []
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.split(",") if x.strip()]
    return [str(m).strip().upper() for m in raw if str(m).strip()]


def printer_slice_issues(
    printer: Printer,
    *,
    stl: StlFile | None = None,
    profile: SlicerProfile | None = None,
    material: str | None = None,
    nozzle_mm: float | None = None,
) -> list[str]:
    issues: list[str] = []
    if not printer.is_enabled:
        issues.append(f"{printer.name} is disabled.")
    if printer.current_downtime_reason:
        issues.append(
            f"{printer.name} is in maintenance ({printer.current_downtime_reason.replace('_', ' ')})."
        )
    if printer.status == PrinterStatus.error:
        issues.append(f"{printer.name} is in error state.")
    bed_x, bed_y, bed_z = usable_bed(printer)
    if stl and stl.bbox_x_mm and stl.bbox_y_mm:
        if float(stl.bbox_x_mm) > bed_x + 0.5 or float(stl.bbox_y_mm) > bed_y + 0.5:
            issues.append(
                f"STL bounding box {stl.bbox_x_mm:g}×{stl.bbox_y_mm:g} mm does not fit "
                f"{printer.name}'s usable bed {bed_x:g}×{bed_y:g} mm."
            )
        if stl.bbox_z_mm and float(stl.bbox_z_mm) > bed_z + 0.5:
            issues.append(
                f"STL height {stl.bbox_z_mm:g} mm exceeds {printer.name}'s usable Z {bed_z:g} mm."
            )
    want_nozzle = nozzle_mm or (profile.nozzle_mm if profile else None)
    if want_nozzle and printer.nozzle_diameter_mm:
        if abs(float(want_nozzle) - float(printer.nozzle_diameter_mm)) > 0.051:
            issues.append(
                f"Profile is {float(want_nozzle):g} mm nozzle; "
                f"{printer.name} is configured with {printer.nozzle_diameter_mm:g} mm."
            )
    mat = (material or (profile.material if profile else "") or "").strip().upper()
    supported = _materials(printer)
    if mat and supported and mat not in supported:
        issues.append(
            f"Material {mat} is not in {printer.name}'s supported list ({', '.join(supported)})."
        )
    if profile and profile.compatible_printer_ids:
        allowed = {str(x) for x in profile.compatible_printer_ids}
        if allowed and str(printer.id) not in allowed:
            issues.append(f"Profile {profile.name} is not marked compatible with {printer.name}.")
    if profile and printer.max_nozzle_temp_c and profile.nozzle_temp_c:
        if float(profile.nozzle_temp_c) > float(printer.max_nozzle_temp_c) + 1:
            issues.append(
                f"Profile nozzle {profile.nozzle_temp_c:g} °C exceeds "
                f"{printer.name} max {printer.max_nozzle_temp_c:g} °C."
            )
    if profile and printer.max_bed_temp_c and profile.bed_temp_c:
        if float(profile.bed_temp_c) > float(printer.max_bed_temp_c) + 1:
            issues.append(
                f"Profile bed {profile.bed_temp_c:g} °C exceeds "
                f"{printer.name} max {printer.max_bed_temp_c:g} °C."
            )
    return issues


def cannot_use_payload(issues: list[str], printer: Printer) -> dict:
    return {
        "ok": not issues,
        "can_use": not issues,
        "printer_id": str(printer.id),
        "printer_name": printer.name,
        "reason": " ".join(issues) if issues else "",
        "issues": issues,
        "admin_override_ok": all(
            "bounding box" not in i.lower() and "height" not in i.lower() and "overlap" not in i.lower()
            for i in issues
        )
        if issues
        else True,
    }


async def compatible_printers(
    db: AsyncSession,
    *,
    stl: StlFile | None,
    profile: SlicerProfile | None,
    material: str | None,
) -> list[dict]:
    rows = (await db.execute(select(Printer).order_by(Printer.name))).scalars().all()
    out = []
    for printer in rows:
        issues = printer_slice_issues(printer, stl=stl, profile=profile, material=material)
        item = cannot_use_payload(issues, printer)
        item["is_enabled"] = printer.is_enabled
        item["status"] = printer.status.value
        out.append(item)
    return out


async def auto_select_printer(
    db: AsyncSession,
    *,
    stl: StlFile | None,
    profile: SlicerProfile | None,
    material: str | None,
    grams: float = 0,
) -> dict:
    printers = (await db.execute(select(Printer).order_by(Printer.name))).scalars().all()
    scored: list[tuple[float, dict, Printer]] = []
    now = datetime.now(timezone.utc)
    for printer in printers:
        issues = printer_slice_issues(printer, stl=stl, profile=profile, material=material)
        payload = cannot_use_payload(issues, printer)
        if issues:
            continue
        score = 0.0
        if printer.status == PrinterStatus.idle:
            score += 50
        elif printer.status == PrinterStatus.waiting_for_bed_clear:
            score += 20
        elif printer.status == PrinterStatus.printing:
            score += 5
        if printer.is_enabled:
            score += 10
        spool = None
        if printer.assigned_spool_id:
            spool = await db.get(FilamentSpool, printer.assigned_spool_id)
        if spool and material and spool.material.upper() == (material or "").upper():
            score += 25
            if grams and spool.remaining_weight_g >= grams * 1.08:
                score += 15
            elif grams:
                score -= 20
        queued = (
            await db.execute(
                select(PrintJob).where(
                    PrintJob.assigned_printer_id == printer.id,
                    PrintJob.status.in_((JobStatus.queued, JobStatus.held)),
                )
            )
        ).scalars().all()
        score -= len(queued) * 4
        eta = sum(j.estimated_time_seconds or 0 for j in queued)
        if printer.status == PrinterStatus.printing:
            eta += max(0, printer.time_remaining_seconds or 0)
        score -= eta / 3600.0
        payload["queue_len"] = len(queued)
        payload["eta_seconds"] = int(eta)
        payload["spool_remaining_g"] = spool.remaining_weight_g if spool else None
        payload["spool_material"] = spool.material if spool else None
        scored.append((score, payload, printer))
    scored.sort(key=lambda row: row[0], reverse=True)
    if not scored:
        alts = await compatible_printers(db, stl=stl, profile=profile, material=material)
        return {
            "printer": None,
            "reason": "No compatible printer is available.",
            "alternatives": [a for a in alts if a["can_use"]][:8],
            "incompatible": [a for a in alts if not a["can_use"]][:8],
        }
    best_score, best, _printer = scored[0]
    return {
        "printer": best,
        "score": round(best_score, 2),
        "reason": "Selected by capacity, installed material, queue, and availability.",
        "alternatives": [row[1] for row in scored[1:6]],
        "as_of": now.isoformat(),
    }
