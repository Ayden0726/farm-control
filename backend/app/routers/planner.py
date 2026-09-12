from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import (
    GCodeFile,
    ProductionRun,
    ProductionRunItem,
    ProductionRunPrinter,
    ProductionRunStatus,
    User,
)
from app.serialize import run_out
from app.services.codes import next_batch_code
from app.services.planner import (
    build_plan,
    commit_plan,
    load_plan,
    plan_payload,
    queue_recommendation,
    recommended_next_jobs,
)
from app.services.schedule_plan import (
    auto_printers_for_gcodes,
    calendar_payload,
    needed_by_iso,
    needed_by_utc,
)

router = APIRouter(prefix="/planner", tags=["planner"])


class PlanLinePatch(BaseModel):
    included: bool | None = None
    printer_id: UUID | None = None
    quantity: int | None = None


class QueueRecIn(BaseModel):
    printer_id: UUID
    part_id: UUID
    quantity: int = 1


class NeededByIn(BaseModel):
    needed_by: str | None = None


class AutoPrintersIn(BaseModel):
    gcode_file_ids: list[UUID] = Field(default_factory=list)
    product_id: UUID | None = None
    product_qty: int = 1
    include_optional: bool = False


class ScheduleItemIn(BaseModel):
    part_id: UUID | None = None
    gcode_file_id: UUID
    required_qty: int = 1


class ScheduleIn(BaseModel):
    needed_by: str
    name: str = ""
    notes: str = ""
    printer_ids: list[UUID] = Field(default_factory=list)
    items: list[ScheduleItemIn] = Field(default_factory=list)
    product_id: UUID | None = None
    product_qty: int = 1
    include_optional: bool = False
    start_immediately: bool = True
    auto_select_printers: bool = True


def _loaded_run():
    return (
        selectinload(ProductionRun.items).selectinload(ProductionRunItem.part),
        selectinload(ProductionRun.items).selectinload(ProductionRunItem.gcode_file),
        selectinload(ProductionRun.printers),
        selectinload(ProductionRun.jobs),
    )


@router.get("/next/jobs")
async def next_jobs(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return await recommended_next_jobs(db)


@router.post("/next/queue")
async def queue_one(
    payload: QueueRecIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_perm("production"))
):
    try:
        run = await queue_recommendation(db, payload.printer_id, payload.part_id, payload.quantity)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return {"production_run_id": str(run.id), "batch_code": run.batch_code}


@router.post("/next/queue-all")
async def queue_all(db: AsyncSession = Depends(get_db), user: User = Depends(require_perm("production"))):
    recs = await recommended_next_jobs(db)
    created = []
    for row in recs:
        rec = row.get("recommendation")
        if not rec:
            continue
        try:
            run = await queue_recommendation(
                db, UUID(row["printer_id"]), UUID(rec["part_id"]), int(rec["quantity"])
            )
            created.append({"printer": row["printer_name"], "run_id": str(run.id), "sku": rec["part_sku"]})
        except ValueError:
            continue
    await db.commit()
    return {"queued": created}


@router.get("/calendar")
async def planner_calendar(
    year: int | None = None,
    month: int | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    year = year or now.year
    month = month or now.month
    if month < 1 or month > 12 or year < 2000 or year > 2100:
        raise HTTPException(400, "Invalid calendar month")
    return await calendar_payload(db, year, month)


async def _gcode_ids_from_product(
    db: AsyncSession, product_id: UUID, quantity: int, include_optional: bool
) -> tuple[list[UUID], dict]:
    from app.services.production_expand import run_items_for_product

    expanded = await run_items_for_product(db, product_id, quantity, include_optional)
    if not expanded:
        raise HTTPException(404, "Product not found")
    ids: list[UUID] = []
    for row in expanded["items"]:
        if row.get("gcode_file_id"):
            ids.append(UUID(row["gcode_file_id"]))
    return ids, expanded


@router.post("/auto-printers")
async def auto_printers(
    payload: AutoPrintersIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    gcode_ids = list(payload.gcode_file_ids)
    extra = None
    if payload.product_id:
        product_ids, extra = await _gcode_ids_from_product(
            db, payload.product_id, payload.product_qty, payload.include_optional
        )
        for gid in product_ids:
            if gid not in gcode_ids:
                gcode_ids.append(gid)
    printers = await auto_printers_for_gcodes(db, gcode_ids)
    return {
        "printers": printers,
        "gcode_file_ids": [str(g) for g in gcode_ids],
        "selected_printer_ids": [p["id"] for p in printers if p["selected"]],
        "product": extra,
    }


@router.post("/schedule")
async def schedule_work(
    payload: ScheduleIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_perm("production"))
):
    from app.routers.production import _append_items, _specs_from_product

    due = needed_by_utc(payload.needed_by)
    if due is None:
        raise HTTPException(400, "Pick a needed-by date on the calendar")
    specs: list[tuple[UUID, UUID | None, int]] = []
    extra = None
    gcode_ids: list[UUID] = []
    for row in payload.items:
        gcode = await db.get(GCodeFile, row.gcode_file_id)
        if not gcode or gcode.is_archived:
            raise HTTPException(400, "Unknown or archived G-code file")
        part_id = row.part_id or gcode.part_id
        if not part_id:
            raise HTTPException(400, f"{gcode.filename} is not tagged to a part")
        specs.append((part_id, gcode.id, max(1, row.required_qty)))
        gcode_ids.append(gcode.id)
    if payload.product_id:
        product_specs, extra = await _specs_from_product(
            db, payload.product_id, payload.product_qty, payload.include_optional
        )
        if not specs:
            specs = product_specs
        else:
            specs.extend(product_specs)
        for part_id, gcode_id, _qty in product_specs:
            if gcode_id and gcode_id not in gcode_ids:
                gcode_ids.append(gcode_id)
    if not specs:
        raise HTTPException(400, "Add G-code files or a catalog product to schedule")

    printer_ids = list(payload.printer_ids)
    if payload.auto_select_printers and not printer_ids:
        picks = await auto_printers_for_gcodes(db, gcode_ids)
        printer_ids = [UUID(p["id"]) for p in picks if p["selected"]]

    sku = (extra or {}).get("product_sku") or "PLAN"
    name = payload.name.strip()
    if not name:
        name = f"{sku} due {needed_by_iso(due)}"
    run = ProductionRun(
        name=name,
        notes=payload.notes or f"Scheduled from planner for {needed_by_iso(due)}",
        status=ProductionRunStatus.queued if payload.start_immediately else ProductionRunStatus.draft,
        needed_by=due,
        product_id=payload.product_id,
    )
    db.add(run)
    await db.flush()
    run.batch_code = await next_batch_code(db, sku)
    for pid in printer_ids:
        db.add(ProductionRunPrinter(production_run_id=run.id, printer_id=pid))
    await _append_items(db, run, specs, payload.start_immediately)
    await db.commit()
    loaded = (
        await db.execute(select(ProductionRun).options(*_loaded_run()).where(ProductionRun.id == run.id))
    ).scalar_one()
    return {
        "run": run_out(loaded).model_dump(mode="json"),
        "needed_by": needed_by_iso(due),
        "printer_ids": [str(p) for p in printer_ids],
        "missing_gcode": (extra or {}).get("missing_gcode") or [],
        "optional_skipped": (extra or {}).get("optional_skipped") or [],
        "multi_file_parts": (extra or {}).get("multi_file_parts") or [],
    }


@router.post("/generate")
async def generate_plan(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_perm("production")),
    payload: Annotated[NeededByIn | None, Body()] = None,
):
    due = needed_by_utc(payload.needed_by if payload else None)
    plan = await build_plan(db, actor=user.email, needed_by=due)
    await db.commit()
    loaded = await load_plan(db, plan.id)
    return plan_payload(loaded)


@router.get("/{plan_id}")
async def get_plan(plan_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    plan = await load_plan(db, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    return plan_payload(plan)


@router.patch("/{plan_id}")
async def patch_plan(
    plan_id: UUID,
    payload: NeededByIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_perm("production")),
):
    plan = await load_plan(db, plan_id)
    if not plan or plan.status != "draft":
        raise HTTPException(400, "Plan is not editable")
    plan.needed_by = needed_by_utc(payload.needed_by)
    await db.commit()
    return plan_payload(await load_plan(db, plan.id))


@router.patch("/{plan_id}/lines/{line_id}")
async def patch_line(
    plan_id: UUID,
    line_id: UUID,
    payload: PlanLinePatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_perm("production")),
):
    plan = await load_plan(db, plan_id)
    if not plan or plan.status != "draft":
        raise HTTPException(400, "Plan is not editable")
    line = next((ln for ln in plan.lines if ln.id == line_id), None)
    if not line:
        raise HTTPException(404, "Line not found")
    if payload.included is not None:
        line.included = payload.included
    if payload.quantity is not None:
        line.quantity = max(0, payload.quantity)
    if payload.printer_id is not None:
        line.printer_id = payload.printer_id
    await db.commit()
    return plan_payload(await load_plan(db, plan_id))


@router.post("/{plan_id}/commit")
async def commit(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_perm("production")),
    payload: Annotated[NeededByIn | None, Body()] = None,
):
    plan = await load_plan(db, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    if plan.status != "draft":
        raise HTTPException(400, "Plan already committed")
    due = needed_by_utc(payload.needed_by if payload else None)
    try:
        run = await commit_plan(db, plan, actor=user.email, needed_by=due)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    loaded = (
        await db.execute(select(ProductionRun).options(*_loaded_run()).where(ProductionRun.id == run.id))
    ).scalar_one()
    return {"plan": plan_payload(await load_plan(db, plan.id)), "run": run_out(loaded).model_dump(mode="json")}
