"""Dedicated PrusaSlicer worker. Separate from uvicorn so slicing cannot freeze the UI."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.config import get_settings
from app.db import SessionLocal, engine
from app.schema_upgrade import upgrade_schema
from app.services.slice_jobs import process_slice_job, waiting_job_ids
from app.services.slicer_defaults import ensure_slicer_defaults
from app.util import configure_logging

logger = logging.getLogger("farmos.slicer_worker")


async def _claim_waiting() -> None:
    async with SessionLocal() as db:
        ids = await waiting_job_ids(db)
    for job_id in ids:
        logger.info("Processing leftover slice job %s", job_id)
        async with SessionLocal() as db:
            await process_slice_job(db, job_id)


async def main() -> None:
    configure_logging()
    settings = get_settings()
    async with engine.begin() as conn:
        await conn.run_sync(upgrade_schema)
    async with SessionLocal() as db:
        await ensure_slicer_defaults(db)
        await db.commit()
    logger.info("Print FarmOS slicer-worker starting (bin=%s)", settings.slicer_bin)
    await _claim_waiting()
    redis = None
    try:
        from redis.asyncio import Redis

        redis = Redis.from_url(settings.redis_url)
        await redis.ping()
    except Exception:
        logger.warning("Redis unavailable — slicer-worker will poll the database every 5s")
        redis = None
    while True:
        job_id = None
        try:
            if redis is not None:
                item = await redis.blpop(settings.slicer_queue_key, timeout=5)
                if item:
                    raw = item[1]
                    job_id = UUID(raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw))
            else:
                await asyncio.sleep(5)
                async with SessionLocal() as db:
                    waiting = await waiting_job_ids(db)
                job_id = waiting[0] if waiting else None
            if job_id is None:
                continue
            async with SessionLocal() as db:
                await process_slice_job(db, job_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("slicer-worker loop error")
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
