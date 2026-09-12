"""Calendar due dates, auto printer picks, and queue priority for the planner.

Needed-by is a deadline, not an APS start time. Jobs still enqueue now; earlier
due dates sit ahead of later or undated queued work. Overnight/unattended rules
stay scheduling metadata only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    GCodeFile,
    JobStatus,
    Order,
    OrderStatus,
    PrintJob,
    Printer,
    PrinterStatus,
    ProductionPlan,
    ProductionPlanLine,
    ProductionRun,
    ProductionRunStatus,
)
from app.services.compatibility import gcode_printer_issues


FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)
ACTIVE_RUN = {
    ProductionRunStatus.draft,
    ProductionRunStatus.queued,
    ProductionRunStatus.in_progress,
    ProductionRunStatus.paused,
}
OPEN_ORDER = {
    OrderStatus.new,
    OrderStatus.awaiting_production,
    OrderStatus.in_production,
    OrderStatus.awaiting_qc,
}
QUEUED_JOB = {JobStatus.queued, JobStatus.held, JobStatus.printing, JobStatus.paused}


def needed_by_utc(value: date | datetime | str | None) -> datetime | None:
    """Store a calendar date as timezone-aware UTC midnight. None stays None."""
    if value is None:
        return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        day = date.fromisoformat(raw[:10])
    elif isinstance(value, datetime):
        day = value.date()
    elif isinstance(value, date):
        day = value
    else:
        raise TypeError(f"Unsupported needed_by value: {type(value)!r}")
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def needed_by_iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def due_priority_key(
    needed_by: datetime | None,
    queue_position: int = 0,
    created_at: datetime | None = None,
) -> tuple[datetime, int, datetime]:
    """Earlier needed_by first; undated work sorts last among queued jobs."""
    return (
        needed_by or FAR_FUTURE,
        queue_position,
        created_at or FAR_FUTURE,
    )


def should_yield_to_new(existing_needed_by: datetime | None, new_needed_by: datetime | None) -> bool:
    """True when an existing queued job should move later for a new due date."""
    if new_needed_by is None:
        return False
    if existing_needed_by is None:
        return True
    return existing_needed_by > new_needed_by


def insert_queue_positions(
    existing: list[tuple[int, datetime | None]],
    new_needed_by: datetime | None,
    n: int,
) -> tuple[int, dict[int, int]]:
    """Where to insert n jobs and how to shift current queue_position values.

    existing is ``(queue_position, needed_by)``. Jobs with the same due date keep
    their relative order; only later or undated work is shifted.
    """
    if n <= 0:
        return 0, {}
    if not existing:
        return 1, {}
    if new_needed_by is None:
        return max(pos for pos, _ in existing) + 1, {}
    later = [pos for pos, due in existing if should_yield_to_new(due, new_needed_by)]
    if not later:
        return max(pos for pos, _ in existing) + 1, {}
    insert_at = min(later)
    shifts = {pos: pos + n for pos, _ in existing if pos >= insert_at}
    return insert_at, shifts


def printer_is_idle_capable(printer: Any) -> bool:
    if not getattr(printer, "is_enabled", False):
        return False
    status = getattr(printer, "status", None)
    value = status.value if hasattr(status, "value") else status
    if value == PrinterStatus.error.value or value == PrinterStatus.error:
        return False
    return True


def auto_select_printers(
    printers: Iterable[Any],
    gcodes: Iterable[Any],
    allowlists: dict[UUID, set[UUID]] | None = None,
) -> list[dict]:
    """Pick enabled, compatible, idle-capable printers for the given G-code files.

    A printer is auto-selected when it is enabled, not in error, and compatible
    with at least one file. Compatibility follows farm rules: both sides must
    have values; empty fields are compatible. An empty G-code allowlist is
    compatible; a non-empty list restricts assignment.
    """
    files = list(gcodes)
    allowlists = allowlists or {}
    rows: list[dict] = []
    for printer in printers:
        compatible_ids: list[str] = []
        issue_notes: list[str] = []
        for gcode in files:
            issues = list(gcode_printer_issues(gcode, printer))
            allowed = allowlists.get(gcode.id)
            if allowed and printer.id not in allowed:
                issues.append(f"{printer.name} is not on this G-code's compatible printer list")
            if issues:
                issue_notes.append(f"{getattr(gcode, 'filename', gcode.id)}: {'; '.join(issues)}")
            else:
                compatible_ids.append(str(gcode.id))
        selected = printer_is_idle_capable(printer) and (bool(compatible_ids) if files else False)
        rows.append(
            {
                "id": str(printer.id),
                "name": printer.name,
                "status": printer.status.value if hasattr(printer.status, "value") else str(printer.status),
                "is_enabled": bool(printer.is_enabled),
                "selected": selected,
                "compatible_file_count": len(compatible_ids),
                "file_count": len(files),
                "compatible_gcode_ids": compatible_ids,
                "issues": issue_notes,
            }
        )
    return rows


def _day_bucket() -> dict:
    return {
        "runs": [],
        "orders": [],
        "queued_jobs": 0,
        "printing_jobs": 0,
        "estimated_seconds": 0,
        "plan_lines": 0,
    }


def calendar_month_span(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    start = first - timedelta(days=(first.weekday() + 1) % 7)
    end = last + timedelta(days=6 - ((last.weekday() + 1) % 7))
    return start, end


async def queue_position_for_needed_by(
    db: AsyncSession, needed_by: datetime | None, n: int
) -> int:
    if n <= 0:
        return 0
    rows = (
        await db.execute(
            select(PrintJob)
            .options(selectinload(PrintJob.production_run))
            .where(PrintJob.status.in_({JobStatus.queued, JobStatus.held}))
            .order_by(PrintJob.queue_position.asc())
        )
    ).scalars().all()
    existing = [
        (j.queue_position, j.production_run.needed_by if j.production_run else None) for j in rows
    ]
    insert_at, shifts = insert_queue_positions(existing, needed_by, n)
    if shifts:
        by_pos = {j.queue_position: j for j in rows}
        for old_pos in sorted(shifts, reverse=True):
            job = by_pos.get(old_pos)
            if job:
                job.queue_position = shifts[old_pos]
    return insert_at


async def auto_printers_for_gcodes(db: AsyncSession, gcode_ids: list[UUID]) -> list[dict]:
    if not gcode_ids:
        printers = (await db.execute(select(Printer).order_by(Printer.name))).scalars().all()
        return auto_select_printers(printers, [], {})
    gcodes = (
        await db.execute(
            select(GCodeFile)
            .options(selectinload(GCodeFile.compatible_printers), selectinload(GCodeFile.part))
            .where(GCodeFile.id.in_(gcode_ids), GCodeFile.is_archived.is_(False))
        )
    ).scalars().all()
    printers = (await db.execute(select(Printer).order_by(Printer.name))).scalars().all()
    allowlists: dict[UUID, set[UUID]] = {}
    for gcode in gcodes:
        rows = gcode.compatible_printers or []
        if rows:
            allowlists[gcode.id] = {row.printer_id for row in rows}
    return auto_select_printers(printers, gcodes, allowlists)


def _run_seconds(run: ProductionRun) -> int:
    return sum((j.estimated_time_seconds or 0) for j in (run.jobs or []) if j.status in QUEUED_JOB)


def _run_job_counts(run: ProductionRun) -> tuple[int, int]:
    queued = 0
    printing = 0
    for job in run.jobs or []:
        if job.status in {JobStatus.queued, JobStatus.held, JobStatus.paused}:
            queued += 1
        elif job.status == JobStatus.printing:
            printing += 1
    return queued, printing


async def calendar_payload(db: AsyncSession, year: int, month: int) -> dict:
    start, end = calendar_month_span(year, month)
    start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc)
    days: dict[str, dict] = {}
    cursor = start
    while cursor <= end:
        days[cursor.isoformat()] = _day_bucket()
        cursor += timedelta(days=1)

    runs = (
        await db.execute(
            select(ProductionRun)
            .options(selectinload(ProductionRun.jobs), selectinload(ProductionRun.items))
            .where(
                ProductionRun.needed_by.is_not(None),
                ProductionRun.needed_by >= start_dt,
                ProductionRun.needed_by <= end_dt,
                ProductionRun.status.in_(ACTIVE_RUN),
            )
        )
    ).scalars().all()
    for run in runs:
        key = needed_by_iso(run.needed_by)
        if not key or key not in days:
            continue
        queued, printing = _run_job_counts(run)
        seconds = _run_seconds(run)
        days[key]["runs"].append(
            {
                "id": str(run.id),
                "name": run.name,
                "batch_code": run.batch_code,
                "status": run.status.value if hasattr(run.status, "value") else str(run.status),
                "needed_by": key,
                "queued_jobs": queued,
                "printing_jobs": printing,
                "estimated_seconds": seconds,
                "item_count": len(run.items or []),
            }
        )
        days[key]["queued_jobs"] += queued
        days[key]["printing_jobs"] += printing
        days[key]["estimated_seconds"] += seconds

    orders = (
        await db.execute(
            select(Order).where(
                Order.due_at.is_not(None),
                Order.due_at >= start_dt,
                Order.due_at <= end_dt,
                Order.status.in_(OPEN_ORDER),
            )
        )
    ).scalars().all()
    for order in orders:
        key = needed_by_iso(order.due_at)
        if not key or key not in days:
            continue
        days[key]["orders"].append(
            {
                "id": str(order.id),
                "reference": order.reference,
                "customer_name": order.customer_name,
                "status": order.status.value if hasattr(order.status, "value") else str(order.status),
                "due_at": key,
            }
        )

    plans = (
        await db.execute(
            select(ProductionPlan)
            .options(selectinload(ProductionPlan.lines).selectinload(ProductionPlanLine.gcode_file))
            .where(
                ProductionPlan.needed_by.is_not(None),
                ProductionPlan.needed_by >= start_dt,
                ProductionPlan.needed_by <= end_dt,
                ProductionPlan.status == "draft",
            )
        )
    ).scalars().all()
    for plan in plans:
        key = needed_by_iso(plan.needed_by)
        if not key or key not in days:
            continue
        included = [ln for ln in plan.lines if ln.included]
        days[key]["plan_lines"] += len(included)
        for line in included:
            duration = line.gcode_file.estimated_time_seconds if line.gcode_file else 3600
            days[key]["estimated_seconds"] += int((duration or 3600) * max(1, line.jobs_needed or 1))

    printers = (await db.execute(select(Printer).where(Printer.is_enabled.is_(True)))).scalars().all()
    printer_count = len(printers)
    printer_seconds = printer_count * 24 * 3600

    undated_queued = (
        await db.execute(
            select(PrintJob)
            .outerjoin(ProductionRun, PrintJob.production_run_id == ProductionRun.id)
            .where(
                PrintJob.status.in_({JobStatus.queued, JobStatus.held}),
                (ProductionRun.needed_by.is_(None)) | (PrintJob.production_run_id.is_(None)),
            )
        )
    ).scalars().all()

    out_days = []
    for key in sorted(days):
        row = days[key]
        seconds = row["estimated_seconds"]
        out_days.append(
            {
                "date": key,
                "runs": row["runs"],
                "orders": row["orders"],
                "queued_jobs": row["queued_jobs"],
                "printing_jobs": row["printing_jobs"],
                "estimated_seconds": seconds,
                "plan_lines": row["plan_lines"],
                "printer_seconds": printer_seconds,
                "over_capacity": bool(printer_seconds and seconds > printer_seconds),
            }
        )
    return {
        "year": year,
        "month": month,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "printer_count": printer_count,
        "printer_seconds_per_day": printer_seconds,
        "undated_queued_jobs": len(undated_queued),
        "days": out_days,
    }
