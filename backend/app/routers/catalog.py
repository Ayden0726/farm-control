from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import GCodeFile, GCodePrinterCompat, Part, StlFile, User
from app.schemas import GCodeOut, GCodeUpdate, PartIn, PartOut, StlOut
from app.serialize import gcode_out
from app.services.farm_settings import get_automation
from app.services.inventory import get_or_create_stock
from app.services.stl import bounding_box, copies_on_plate
from app.util import parse_gcode_metadata, parse_quantity_from_filename

parts_router = APIRouter(prefix="/parts", tags=["parts"])
gcode_router = APIRouter(prefix="/gcode", tags=["gcode"])
stl_router = APIRouter(prefix="/stl", tags=["stl"])


async def _part_out(db: AsyncSession, part: Part) -> PartOut:
    stock = await get_or_create_stock(db, part.id)
    return PartOut(
        id=part.id,
        sku=part.sku,
        name=part.name,
        description=part.description,
        is_active=part.is_active,
        quantity_on_hand=stock.quantity_on_hand,
        quantity_reserved=stock.quantity_reserved,
        quantity_available=stock.quantity_available,
        min_stock=getattr(part, "min_stock", 0) or 0,
        target_stock=getattr(part, "target_stock", 0) or 0,
    )


@parts_router.get("", response_model=list[PartOut])
async def list_parts(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(Part).order_by(Part.sku))).scalars().all()
    return [await _part_out(db, p) for p in rows]


@parts_router.post("", response_model=PartOut)
async def create_part(payload: PartIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    existing = (await db.execute(select(Part).where(Part.sku == payload.sku))).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "SKU already exists")
    part = Part(**payload.model_dump())
    db.add(part)
    await db.flush()
    await get_or_create_stock(db, part.id)
    await db.commit()
    await db.refresh(part)
    return await _part_out(db, part)


@parts_router.patch("/{part_id}", response_model=PartOut)
async def update_part(
    part_id: UUID, payload: PartIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
):
    part = await db.get(Part, part_id)
    if not part:
        raise HTTPException(404, "Part not found")
    for k, v in payload.model_dump().items():
        setattr(part, k, v)
    await db.commit()
    await db.refresh(part)
    return await _part_out(db, part)


@gcode_router.get("", response_model=list[GCodeOut])
async def list_gcode(
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(GCodeFile).options(selectinload(GCodeFile.part), selectinload(GCodeFile.compatible_printers))
    if not include_archived:
        stmt = stmt.where(GCodeFile.is_archived.is_(False))
    stmt = stmt.order_by(GCodeFile.filename, GCodeFile.version.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [gcode_out(g) for g in rows]


@gcode_router.post("/upload", response_model=GCodeOut)
async def upload_gcode(
    file: UploadFile = File(...),
    part_id: UUID | None = Form(None),
    material: str = Form("PETG"),
    notes: str = Form(""),
    compatible_printer_ids: str = Form(""),
    quantity_per_file: int | None = Form(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    settings = get_settings()
    filename = file.filename or "upload.gcode"
    content = await file.read()
    dest = settings.gcode_dir / filename
    dest.write_bytes(content)
    text = ""
    try:
        text = content.decode("utf-8", errors="ignore")[:80_000]
    except Exception:
        text = ""
    meta = parse_gcode_metadata(text)
    parsed = parse_quantity_from_filename(filename)
    if quantity_per_file is not None:
        qty = max(1, min(int(quantity_per_file), 999))
    else:
        qty = parsed
    version = 1
    existing = (
        await db.execute(
            select(GCodeFile)
            .where(GCodeFile.filename == filename)
            .order_by(GCodeFile.version.desc())
        )
    ).scalars().first()
    if existing:
        existing.is_archived = True
        version = existing.version + 1
    gcode = GCodeFile(
        filename=filename,
        stored_path=str(dest),
        part_id=part_id,
        quantity_per_file=qty,
        material=material,
        estimated_time_seconds=int(meta.get("estimated_time_seconds") or 3600),
        estimated_filament_grams=float(meta.get("estimated_filament_grams") or 20),
        version=version,
        notes=notes,
        file_size_bytes=len(content),
    )
    db.add(gcode)
    await db.flush()
    for raw in [x.strip() for x in compatible_printer_ids.split(",") if x.strip()]:
        db.add(GCodePrinterCompat(gcode_id=gcode.id, printer_id=UUID(raw)))
    await db.commit()
    gcode = (
        await db.execute(
            select(GCodeFile)
            .options(selectinload(GCodeFile.part), selectinload(GCodeFile.compatible_printers))
            .where(GCodeFile.id == gcode.id)
        )
    ).scalar_one()
    return gcode_out(gcode)


@gcode_router.patch("/{gcode_id}", response_model=GCodeOut)
async def update_gcode(
    gcode_id: UUID,
    payload: GCodeUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    gcode = await db.get(GCodeFile, gcode_id)
    if not gcode:
        raise HTTPException(404, "G-code not found")
    data = payload.model_dump(exclude_unset=True)
    compat = data.pop("compatible_printer_ids", None)
    for k, v in data.items():
        setattr(gcode, k, v)
    if compat is not None:
        current = (
            await db.execute(select(GCodePrinterCompat).where(GCodePrinterCompat.gcode_id == gcode.id))
        ).scalars().all()
        for row in current:
            await db.delete(row)
        for pid in compat:
            db.add(GCodePrinterCompat(gcode_id=gcode.id, printer_id=pid))
    if data.get("production_approved") and gcode.part_id:
        siblings = (
            await db.execute(select(GCodeFile).where(GCodeFile.part_id == gcode.part_id, GCodeFile.id != gcode.id))
        ).scalars().all()
        for sibling in siblings:
            sibling.production_approved = False
    await db.commit()
    gcode = (
        await db.execute(
            select(GCodeFile)
            .options(selectinload(GCodeFile.part), selectinload(GCodeFile.compatible_printers))
            .where(GCodeFile.id == gcode.id)
        )
    ).scalar_one()
    return gcode_out(gcode)


def _apply_stl_bounds(stl: StlFile, content: bytes | None = None) -> None:
    if stl.bbox_x_mm is not None:
        return
    data = content
    if data is None:
        path = Path(stl.stored_path)
        if path.is_file():
            data = path.read_bytes()
    if not data:
        return
    box = bounding_box(data)
    if not box:
        return
    stl.bbox_x_mm = box.x_mm
    stl.bbox_y_mm = box.y_mm
    stl.bbox_z_mm = box.z_mm
    stl.triangle_count = box.triangle_count


def _stl_out(stl: StlFile, automation: dict) -> StlOut:
    copies = cols = rows = None
    rotated = False
    if stl.bbox_x_mm is not None and stl.bbox_y_mm is not None:
        pack = copies_on_plate(
            float(stl.bbox_x_mm),
            float(stl.bbox_y_mm),
            float(automation["pack_bed_x_mm"]),
            float(automation["pack_bed_y_mm"]),
            float(automation["pack_gap_mm"]),
        )
        copies = pack.copies
        rotated = pack.rotated
        cols = pack.cols
        rows = pack.rows
    return StlOut(
        id=stl.id,
        filename=stl.filename,
        part_id=stl.part_id,
        part_sku=stl.part.sku if stl.part else None,
        notes=stl.notes,
        file_size_bytes=stl.file_size_bytes,
        created_at=stl.created_at,
        bbox_x_mm=stl.bbox_x_mm,
        bbox_y_mm=stl.bbox_y_mm,
        bbox_z_mm=stl.bbox_z_mm,
        triangle_count=stl.triangle_count,
        copies_per_plate=copies,
        pack_rotated=rotated,
        pack_cols=cols,
        pack_rows=rows,
        pack_bed_x_mm=automation["pack_bed_x_mm"],
        pack_bed_y_mm=automation["pack_bed_y_mm"],
        pack_gap_mm=automation["pack_gap_mm"],
    )


@stl_router.get("", response_model=list[StlOut])
async def list_stl(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(StlFile).options(selectinload(StlFile.part)).order_by(StlFile.created_at.desc())
        )
    ).scalars().all()
    automation = await get_automation(db)
    dirty = False
    out: list[StlOut] = []
    for stl in rows:
        if stl.bbox_x_mm is None:
            _apply_stl_bounds(stl)
            dirty = True
        out.append(_stl_out(stl, automation))
    if dirty:
        await db.commit()
    return out


@stl_router.post("/upload", response_model=StlOut)
async def upload_stl(
    file: UploadFile = File(...),
    part_id: UUID | None = Form(None),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    settings = get_settings()
    filename = file.filename or "upload.stl"
    content = await file.read()
    dest = settings.stl_dir / filename
    dest.write_bytes(content)
    box = bounding_box(content)
    note = notes.strip() if notes else ""
    if not note:
        if box:
            note = (
                "Measured for a plate-fit estimate. Print FarmOS does not slice STLs — "
                "pack copies in your slicer and upload the G-code."
            )
        else:
            note = (
                "Could not measure this STL. Print FarmOS does not slice models; upload G-code for production."
            )
    stl = StlFile(
        filename=filename,
        stored_path=str(dest),
        part_id=part_id,
        notes=note,
        file_size_bytes=len(content),
        bbox_x_mm=box.x_mm if box else None,
        bbox_y_mm=box.y_mm if box else None,
        bbox_z_mm=box.z_mm if box else None,
        triangle_count=box.triangle_count if box else None,
    )
    db.add(stl)
    await db.commit()
    stl = (
        await db.execute(
            select(StlFile).options(selectinload(StlFile.part)).where(StlFile.id == stl.id)
        )
    ).scalar_one()
    return _stl_out(stl, await get_automation(db))
