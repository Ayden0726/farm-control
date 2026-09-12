from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IdSequence, utcnow


async def next_sequence(db: AsyncSession, name: str) -> int:
    seq = await db.get(IdSequence, name)
    if seq is None:
        seq = IdSequence(name=name, next_value=1)
        db.add(seq)
        await db.flush()
    n = seq.next_value or 1
    seq.next_value = n + 1
    return n


async def next_batch_code(db: AsyncSession, sku: str = "GEN") -> str:
    n = await next_sequence(db, "production_batch")
    year = utcnow().year
    slug = "".join(ch for ch in (sku or "GEN").upper() if ch.isalnum())[:8] or "GEN"
    return f"BATCH-{slug}-{year}-{n:04d}"


async def next_kit_code(db: AsyncSession) -> str:
    n = await next_sequence(db, "assembly_kit")
    return f"KIT-{n:06d}"


async def next_order_code(db: AsyncSession, reference: str) -> str:
    n = await next_sequence(db, "order_code")
    slug = "".join(ch for ch in (reference or "ORDER").upper() if ch.isalnum())[:12] or "ORDER"
    return f"ORDER-{slug}-{n:04d}"
