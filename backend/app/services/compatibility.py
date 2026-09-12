from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GCodeFile, GCodePrinterCompat, Printer, PrintJob
from app.services.farm_settings import get_mes


def _materials(printer: Printer) -> list[str]:
    raw = printer.supported_materials or []
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.split(",") if x.strip()]
    return [str(m).strip().upper() for m in raw if str(m).strip()]


def gcode_printer_issues(gcode: GCodeFile | None, printer: Printer) -> list[str]:
    """Return human-readable reasons the G-code cannot run on this printer."""
    if not gcode:
        return ["Job has no G-code file"]
    issues: list[str] = []
    required_nozzle = gcode.required_nozzle_mm or gcode.nozzle_mm
    if required_nozzle and printer.nozzle_diameter_mm:
        if abs(float(required_nozzle) - float(printer.nozzle_diameter_mm)) > 0.051:
            issues.append(
                f"G-code requires {required_nozzle:g} mm nozzle. "
                f"Printer currently configured with {printer.nozzle_diameter_mm:g} mm nozzle"
            )
    material = (gcode.material or "").strip().upper()
    supported = _materials(printer)
    if material and supported and material not in supported:
        issues.append(
            f"G-code requires {gcode.material}. "
            f"Printer supports {', '.join(_materials(printer)) or 'no listed materials'}"
        )
    min_x = gcode.min_bed_x_mm
    min_y = gcode.min_bed_y_mm
    if min_x and printer.build_x_mm and float(min_x) > float(printer.build_x_mm) + 0.5:
        issues.append(
            f"G-code needs at least {min_x:g} mm bed width. "
            f"{printer.name} build volume is {printer.build_x_mm:g} × {printer.build_y_mm or 0:g} mm"
        )
    if min_y and printer.build_y_mm and float(min_y) > float(printer.build_y_mm) + 0.5:
        issues.append(
            f"G-code needs at least {min_y:g} mm bed depth. "
            f"{printer.name} build volume is {printer.build_x_mm or 0:g} × {printer.build_y_mm:g} mm"
        )
    return issues


def format_incompatibility(printer_name: str, issues: list[str]) -> str:
    if not issues:
        return ""
    return f"Job incompatible with {printer_name}. Reason: {'; '.join(issues)}"


async def allowlist_ok(db: AsyncSession, gcode_id: UUID, printer_id: UUID) -> bool:
    rows = (
        await db.execute(select(GCodePrinterCompat).where(GCodePrinterCompat.gcode_id == gcode_id))
    ).scalars().all()
    if not rows:
        return True
    return any(r.printer_id == printer_id for r in rows)


async def job_printer_issues(db: AsyncSession, job: PrintJob, printer: Printer) -> list[str]:
    issues: list[str] = []
    gcode = job.gcode_file
    if gcode is None and job.gcode_file_id:
        gcode = await db.get(GCodeFile, job.gcode_file_id)
    if not await allowlist_ok(db, job.gcode_file_id, printer.id):
        issues.append(f"{printer.name} is not on this G-code's compatible printer list")
    issues.extend(gcode_printer_issues(gcode, printer))
    if not printer.is_enabled:
        issues.append(f"{printer.name} is disabled")
    return issues


def in_unattended_hours(now: datetime, start_hour: int, end_hour: int) -> bool:
    hour = now.astimezone(timezone.utc).hour if now.tzinfo else now.hour
    start = int(start_hour)
    end = int(end_hour)
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


async def unattended_blocks(db: AsyncSession, job: PrintJob, printer: Printer, now: datetime | None = None) -> str | None:
    """Scheduling metadata only — never bypasses printer safety systems."""
    mes = await get_mes(db)
    now = now or datetime.now(timezone.utc)
    overnight = in_unattended_hours(now, mes["overnight_start_hour"], mes["overnight_end_hour"])
    if not overnight:
        return None
    mode = (printer.unattended_mode or "allowed").lower()
    if mode in {"disabled_overnight", "disabled"}:
        return f"{printer.name} is disabled overnight"
    gcode = job.gcode_file
    if gcode is None and job.gcode_file_id:
        gcode = await db.get(GCodeFile, job.gcode_file_id)
    job_ok = bool(getattr(job, "unattended_approved", True))
    gcode_ok = True if gcode is None else bool(getattr(gcode, "unattended_approved", True))
    needs_supervision = (not job_ok) or (not gcode_ok) or mode == "supervision"
    if needs_supervision:
        return "Supervision required — not scheduled during unattended hours"
    return None
