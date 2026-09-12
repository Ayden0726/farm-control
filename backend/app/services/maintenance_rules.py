from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    MaintenanceLog,
    MaintenanceRule,
    MaintenanceTask,
    NotificationType,
    Printer,
    utcnow,
)
from app.services.notifications import NotifyContext, notify, recently_notified

DEFAULT_RULES = [
    {"name": "Clean build plate", "kind": "clean_plate", "interval_print_hours": 50},
    {"name": "Lubricate rails", "kind": "lubricate", "interval_print_hours": 250},
    {"name": "Inspect belts", "kind": "inspect_belts", "interval_print_hours": 500},
    {"name": "Replace nozzle", "kind": "replace_nozzle", "interval_print_hours": 800},
]


async def ensure_default_rules(db: AsyncSession) -> None:
    existing = (await db.execute(select(MaintenanceRule))).scalars().first()
    if existing:
        return
    for row in DEFAULT_RULES:
        db.add(MaintenanceRule(**row, is_active=True, notify=True))
    await db.flush()


def _task_status(due_at, now) -> str:
    if due_at is None:
        return "due"
    delta = (due_at - now).total_seconds()
    if delta < 0:
        return "overdue"
    if delta < 48 * 3600:
        return "due_soon"
    return "scheduled"


async def evaluate_maintenance(db: AsyncSession) -> list[MaintenanceTask]:
    await ensure_default_rules(db)
    printers = (await db.execute(select(Printer).where(Printer.is_enabled.is_(True)))).scalars().all()
    rules = (await db.execute(select(MaintenanceRule).where(MaintenanceRule.is_active.is_(True)))).scalars().all()
    created: list[MaintenanceTask] = []
    now = utcnow()
    for printer in printers:
        hours = (printer.total_print_seconds or 0) / 3600.0
        prints = printer.total_jobs or 0
        last_service = printer.last_maintenance_at
        for rule in rules:
            if rule.printer_id and rule.printer_id != printer.id:
                continue
            due = False
            due_at = now
            if rule.interval_print_hours:
                due = hours >= float(rule.interval_print_hours)
                # next due based on remainder
                remaining_h = float(rule.interval_print_hours) - (
                    hours % float(rule.interval_print_hours) if hours else 0
                )
                due_at = now + timedelta(hours=max(0, remaining_h))
                if hours >= float(rule.interval_print_hours):
                    due_at = now
            if rule.interval_prints:
                due = due or prints >= int(rule.interval_prints)
            if rule.interval_days:
                start = last_service or printer.created_at or now
                age = now - start
                due = due or age.days >= int(rule.interval_days)
                if not rule.interval_print_hours:
                    due_at = start + timedelta(days=int(rule.interval_days))
            open_task = (
                await db.execute(
                    select(MaintenanceTask).where(
                        MaintenanceTask.printer_id == printer.id,
                        MaintenanceTask.kind == rule.kind,
                        MaintenanceTask.status.in_(["due", "due_soon", "overdue", "scheduled"]),
                    )
                )
            ).scalars().first()
            if open_task:
                open_task.status = _task_status(open_task.due_at, now)
                continue
            if not due and rule.interval_print_hours and hours < float(rule.interval_print_hours) * 0.9:
                continue
            status = _task_status(due_at, now)
            if status == "scheduled" and not due:
                continue
            task = MaintenanceTask(
                rule_id=rule.id,
                printer_id=printer.id,
                name=f"{rule.name} — {printer.name}",
                kind=rule.kind,
                status=status,
                due_at=due_at,
            )
            db.add(task)
            created.append(task)
            if rule.notify and status in {"due", "overdue", "due_soon"}:
                if not await recently_notified(db, NotificationType.maintenance_due.value, printer.id, hours=24):
                    await notify(
                        db,
                        NotificationType.maintenance_due,
                        f"{printer.name} — {rule.name}",
                        f"{rule.name} is {status.replace('_', ' ')} on {printer.name} ({hours:.0f} print hours).",
                        severity="warning" if status != "overdue" else "error",
                        entity_type="printer",
                        entity_id=printer.id,
                        ctx=NotifyContext(printer_id=printer.id, printer_name=printer.name),
                    )
    await db.flush()
    return created
