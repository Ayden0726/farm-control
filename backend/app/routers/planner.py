from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import ProductionPlanLine, User
from app.serialize import run_out
from app.services.planner import (
    build_plan,
    commit_plan,
    load_plan,
    plan_payload,
    queue_recommendation,
    recommended_next_jobs,
)
from sqlalchemy.orm import selectinload
from sqlalchemy import select
from app.models import ProductionRun, ProductionRunItem

router = APIRouter(prefix="/planner", tags=["planner"])


class PlanLinePatch(BaseModel):
    included: bool | None = None
    printer_id: UUID | None = None
    quantity: int | None = None


class QueueRecIn(BaseModel):
    printer_id: UUID
    part_id: UUID
    quantity: int = 1


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


@router.post("/generate")
async def generate_plan(
    db: AsyncSession = Depends(get_db), user: User = Depends(require_perm("production"))
):
    plan = await build_plan(db, actor=user.email)
    await db.commit()
    loaded = await load_plan(db, plan.id)
    return plan_payload(loaded)


@router.get("/{plan_id}")
async def get_plan(plan_id: UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    plan = await load_plan(db, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    return plan_payload(plan)


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
    plan_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_perm("production"))
):
    plan = await load_plan(db, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    if plan.status != "draft":
        raise HTTPException(400, "Plan already committed")
    try:
        run = await commit_plan(db, plan, actor=user.email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    loaded = (
        await db.execute(
            select(ProductionRun)
            .options(
                selectinload(ProductionRun.items).selectinload(ProductionRunItem.part),
                selectinload(ProductionRun.items).selectinload(ProductionRunItem.gcode_file),
                selectinload(ProductionRun.printers),
                selectinload(ProductionRun.jobs),
            )
            .where(ProductionRun.id == run.id)
        )
    ).scalar_one()
    return {"plan": plan_payload(await load_plan(db, plan.id)), "run": run_out(loaded).model_dump(mode="json")}
