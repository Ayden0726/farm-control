from __future__ import annotations

import gzip
import json
import shutil
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import BackupRecord, NotificationType, utcnow
from app.services.farm_settings import get_mes
from app.services.notifications import NotifyContext, notify


def _dump_via_psycopg(settings, dest: Path) -> None:
    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    import subprocess

    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    proc = subprocess.run(
        ["pg_dump", url],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace")[:500] or "pg_dump failed")
    dest.write_bytes(gzip.compress(proc.stdout))


async def create_backup(db: AsyncSession, *, kind: str = "manual", include_files: bool | None = None) -> BackupRecord:
    settings = get_settings()
    mes = await get_mes(db)
    include_files = mes["backup_include_files"] if include_files is None else include_files
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"farmos-{stamp}.sql.gz"
    dest = settings.backup_dir / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    row = BackupRecord(filename=filename, stored_path=str(dest), kind=kind, status="running")
    db.add(row)
    await db.flush()
    try:
        try:
            _dump_via_psycopg(settings, dest)
        except Exception:
            # Fallback: JSON snapshot of configuration + counts (not a full SQL dump)
            from app.models import AppSetting, Order, Part, Printer

            payload = {
                "created_at": stamp,
                "settings": [
                    {"key": s.key, "value": s.value}
                    for s in (await db.execute(select(AppSetting))).scalars().all()
                ],
                "note": "pg_dump was unavailable; this backup contains settings JSON only. Database dump failed.",
            }
            dest.write_bytes(gzip.compress(json.dumps(payload, default=str).encode("utf-8")))
            row.notes = "Partial backup (pg_dump unavailable)"
        if include_files:
            files_dir = settings.backup_dir / f"files-{stamp}"
            for src_name in ("gcode",):
                src = settings.upload_dir / src_name
                if src.exists():
                    shutil.copytree(src, files_dir / src_name, dirs_exist_ok=True)
            row.include_files = True
        row.size_bytes = dest.stat().st_size if dest.exists() else 0
        row.status = "ok"
    except Exception as exc:
        row.status = "failed"
        row.error_message = str(exc)[:500]
    await _prune(db, mes["backup_retention_days"])
    return row


async def _prune(db: AsyncSession, retention_days: int) -> None:
    cutoff = utcnow() - timedelta(days=max(1, retention_days))
    old = (
        await db.execute(select(BackupRecord).where(BackupRecord.created_at < cutoff))
    ).scalars().all()
    for row in old:
        path = Path(row.stored_path)
        if path.exists():
            path.unlink(missing_ok=True)
        await db.delete(row)


async def restore_backup(db: AsyncSession, backup_id) -> BackupRecord:
    row = await db.get(BackupRecord, backup_id)
    if not row:
        raise ValueError("Backup not found")
    path = Path(row.stored_path)
    if not path.exists():
        raise ValueError("Backup file is missing from disk")
    url = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    import subprocess

    data = gzip.decompress(path.read_bytes())
    if data[:1] == b"{":
        raise ValueError("This backup is a settings snapshot only and cannot restore PostgreSQL")
    proc = subprocess.run(
        ["psql", url],
        input=data,
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace")[:500])
    row.notes = (row.notes + "\nRestored " + utcnow().isoformat()).strip()
    return row


async def notify_failed_backups(db: AsyncSession) -> None:
    recent = (
        await db.execute(
            select(BackupRecord)
            .where(BackupRecord.kind == "scheduled")
            .order_by(BackupRecord.created_at.desc())
            .limit(3)
        )
    ).scalars().all()
    if len(recent) < 2:
        return
    if all(r.status != "ok" for r in recent):
        await notify(
            db,
            NotificationType.backup_failed,
            "Scheduled backups are failing",
            recent[0].error_message or "The last scheduled FarmOS backups did not complete.",
            severity="error",
            entity_type="backup",
            entity_id=recent[0].id,
            ctx=NotifyContext(),
        )
