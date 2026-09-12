from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BackupRecord, NotificationProviderSetting, Printer, PrinterStatus
from app.config import get_settings
from app.services.woocommerce import woocommerce_configured
from app.services.shopify import shopify_config, shopify_configured
from sqlalchemy import text
import shutil


async def collect_health(db: AsyncSession) -> dict:
    settings = get_settings()
    checks: list[dict] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    add("FarmOS backend", "healthy", "API process is responding")

    try:
        await db.execute(text("SELECT 1"))
        add("Database", "healthy", "PostgreSQL accepted a ping")
    except Exception as exc:
        add("Database", "error", str(exc))

    redis_status = "warning"
    redis_detail = "Redis is used as a scheduler lock"
    try:
        from redis.asyncio import Redis

        r = Redis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        redis_status = "healthy"
        redis_detail = "Connected"
    except Exception as exc:
        redis_detail = str(exc)
    add("Redis", redis_status, redis_detail)

    usage = shutil.disk_usage(str(settings.upload_dir))
    pct = usage.used / max(1, usage.total) * 100
    disk_status = "healthy" if pct < 85 else ("warning" if pct < 95 else "error")
    add("Disk", disk_status, f"{pct:.0f}% used ({usage.free // (1024**3)} GB free)")

    printers = (await db.execute(select(Printer).where(Printer.is_enabled.is_(True)))).scalars().all()
    offline = [p for p in printers if p.status == PrinterStatus.offline]
    if not printers:
        add("Printers", "warning", "No enabled printers")
    elif offline:
        add("Printers", "warning", f"{len(offline)} of {len(printers)} enabled printers offline")
    else:
        add("Printers", "healthy", f"{len(printers)} printers reporting")

    if woocommerce_configured():
        add("WooCommerce", "healthy", "Credentials configured")
    else:
        add("WooCommerce", "warning", "Not configured")

    shopify = await shopify_config(db)
    if shopify_configured(shopify):
        add("Shopify", "healthy", f"Shop {shopify['shop']}")
    else:
        add("Shopify", "warning", "Not configured")

    providers = (await db.execute(select(NotificationProviderSetting))).scalars().all()
    enabled = [p for p in providers if p.enabled]
    if enabled:
        add("Notifications", "healthy", f"{len(enabled)} provider(s) enabled")
    else:
        add("Notifications", "warning", "No phone notification provider enabled")

    last = (
        await db.execute(select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(1))
    ).scalars().first()
    if not last:
        add("Backups", "warning", "No backup recorded yet")
    elif last.status != "ok":
        add("Backups", "error", last.error_message or "Last backup failed")
    else:
        add("Backups", "healthy", f"Last backup {last.created_at.isoformat()} ({last.filename})")

    worst = "healthy"
    if any(c["status"] == "error" for c in checks):
        worst = "error"
    elif any(c["status"] == "warning" for c in checks):
        worst = "warning"
    return {"status": worst, "generated_at": datetime.now(timezone.utc).isoformat(), "checks": checks}
