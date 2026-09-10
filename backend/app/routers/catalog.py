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
from app.services.inventory import get_or_create_stock
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
    qty = parse_quantity_from_filename(filename)
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
    await db.commit()
    gcode = (
        await db.execute(
            select(GCodeFile)
            .options(selectinload(GCodeFile.part), selectinload(GCodeFile.compatible_printers))
            .where(GCodeFile.id == gcode.id)
        )
    ).scalar_one()
    return gcode_out(gcode)


@stl_router.get("", response_model=list[StlOut])
async def list_stl(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(StlFile).order_by(StlFile.created_at.desc()))).scalars().all()
    return rows


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
    stl = StlFile(
        filename=filename,
        stored_path=str(dest),
        part_id=part_id,
        notes=notes or "Stored for future automated slicing. Slicing is not run automatically yet.",
        file_size_bytes=len(content),
    )
    db.add(stl)
    await db.commit()
    await db.refresh(stl)
    return stl
