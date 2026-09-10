"""Idempotent schema upgrades for existing FarmOS databases."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.db import Base

logger = logging.getLogger("farmos.schema")

NOTIFICATION_COLUMNS = {
    "printer_id": "UUID",
    "printer_name": "VARCHAR(255)",
    "job_id": "UUID",
    "job_label": "VARCHAR(255)",
    "production_run_id": "UUID",
    "production_run_name": "VARCHAR(255)",
    "order_id": "UUID",
    "order_reference": "VARCHAR(100)",
    "deep_link": "VARCHAR(500)",
    "extra": "JSON DEFAULT '{}'::json",
}


def _notifications_type_udt(conn: Connection) -> str | None:
    return conn.execute(
        text(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = 'notifications' AND column_name = 'type'"
        )
    ).scalar()


def upgrade_schema(conn: Connection) -> None:
    Base.metadata.create_all(bind=conn)
    insp = inspect(conn)
    tables = set(insp.get_table_names())
    if "notifications" not in tables:
        return
    udt = _notifications_type_udt(conn)
    if udt and udt.lower() not in {"varchar", "text", "bpchar"}:
        conn.execute(
            text(
                "ALTER TABLE notifications ALTER COLUMN type TYPE varchar(50) "
                "USING type::text"
            )
        )
        conn.execute(text("DROP TYPE IF EXISTS notificationtype CASCADE"))
        logger.info("Converted notifications.type from %s to varchar", udt)
    cols = {c["name"]: c for c in insp.get_columns("notifications")}
    existing = set(cols)
    for name, ddl in NOTIFICATION_COLUMNS.items():
        if name not in existing:
            conn.execute(text(f"ALTER TABLE notifications ADD COLUMN {name} {ddl}"))
            logger.info("Added notifications.%s", name)
