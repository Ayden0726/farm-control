from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import SessionLocal, engine
from app.schema_upgrade import upgrade_schema
from app.routers.auth import router as auth_router
from app.routers.catalog import gcode_router, parts_router, stl_router
from app.routers.dashboard import router as dashboard_router
from app.routers.filament import router as filament_router
from app.routers.filament_ops import router as filament_ops_router
from app.routers.inventory import router as inventory_router
from app.routers.labels import router as labels_router
from app.routers.notify_api import router as notify_router
from app.routers.orders import router as orders_router
from app.routers.printers import router as printers_router
from app.routers.production import router as production_router
from app.routers.products import router as products_router
from app.routers.purchasing import router as purchasing_router
from app.routers.queue import router as queue_router
from app.routers.system import router as system_router
from app.routers.misc import analytics_router, maint_router, qr_router, scan_router, settings_router
from app.util import configure_logging

logger = logging.getLogger("farmos")


async def _scheduler_loop() -> None:
    from app.config import get_settings
    from app.db import SessionLocal
    from app.services.scheduler import tick

    settings = get_settings()
    redis = None
    try:
        from redis.asyncio import Redis

        redis = Redis.from_url(settings.redis_url)
        await redis.ping()
    except Exception:
        logger.warning("Redis unavailable — scheduler will run without a distributed lock")
        redis = None
    while True:
        try:
            got_lock = True
            if redis is not None:
                got_lock = bool(await redis.set("farmos:scheduler_lock", "1", ex=12, nx=True))
            if got_lock:
                async with SessionLocal() as db:
                    await tick(db)
                    await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scheduler tick failed")
        await asyncio.sleep(settings.scheduler_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(upgrade_schema)
    except Exception:
        logger.exception("schema upgrade failed — API will still listen for setup")
    async with SessionLocal() as db:
        try:
            from app.seed_filament import ensure_filament_system
            from app.services.notifications import ensure_defaults

            await ensure_defaults(db)
            await ensure_filament_system(db)
            await db.commit()
        except Exception:
            logger.exception("startup seed failed — API will still serve first-run setup")
            await db.rollback()
    task = None
    if settings.run_scheduler:
        task = asyncio.create_task(_scheduler_loop())
        logger.info("FarmOS scheduler started")
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Print FarmOS",
        version="1.0.0",
        description="Self-hosted production control for the print farm.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list + ["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_origin_regex=r"https?://.*",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(RequestValidationError)
    async def invalid_payload(_: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @application.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        logger.exception("unhandled error")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    api = "/api/v1"
    application.include_router(auth_router, prefix=api)
    application.include_router(printers_router, prefix=api)
    application.include_router(queue_router, prefix=api)
    application.include_router(production_router, prefix=api)
    application.include_router(parts_router, prefix=api)
    application.include_router(gcode_router, prefix=api)
    application.include_router(stl_router, prefix=api)
    application.include_router(inventory_router, prefix=api)
    application.include_router(filament_ops_router, prefix=api)
    application.include_router(filament_router, prefix=api)
    application.include_router(purchasing_router, prefix=api)
    application.include_router(labels_router, prefix=api)
    application.include_router(products_router, prefix=api)
    application.include_router(orders_router, prefix=api)
    application.include_router(dashboard_router, prefix=api)
    application.include_router(notify_router, prefix=api)
    application.include_router(maint_router, prefix=api)
    application.include_router(analytics_router, prefix=api)
    application.include_router(settings_router, prefix=api)
    application.include_router(system_router, prefix=api)
    application.include_router(qr_router, prefix=api)
    application.include_router(scan_router, prefix=api)

    @application.get("/health")
    async def health():
        return {"status": "ok", "app": "Print FarmOS", "version": settings.app_version}

    return application


app = create_app()
