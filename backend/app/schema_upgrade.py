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

TABLE_COLUMNS = {
    "filament_spools": {
        "product_id": "UUID",
        "location_id": "UUID",
        "supplier_id": "UUID",
        "purchase_order_id": "UUID",
        "public_code": "VARCHAR(40)",
        "cost_per_kg": "DOUBLE PRECISION DEFAULT 0",
        "date_received": "TIMESTAMPTZ",
        "date_opened": "TIMESTAMPTZ",
        "last_dried_at": "TIMESTAMPTZ",
        "is_sealed": "BOOLEAN DEFAULT true",
        "is_empty": "BOOLEAN DEFAULT false",
        "consumed_g": "DOUBLE PRECISION DEFAULT 0",
    },
    "printers": {
        "public_code": "VARCHAR(40)",
    },
    "part_bins": {
        "public_code": "VARCHAR(40)",
        "kind": "VARCHAR(40) DEFAULT 'finished_part'",
    },
    "print_jobs": {
        "filament_override": "BOOLEAN DEFAULT false",
        "hold_reason": "VARCHAR(80)",
        "filament_required_g": "DOUBLE PRECISION DEFAULT 0",
        "filament_available_g": "DOUBLE PRECISION DEFAULT 0",
    },
    "gcode_files": {
        "required_color": "VARCHAR(80) DEFAULT ''",
    },
}


def _notifications_type_udt(conn: Connection) -> str | None:
    return conn.execute(
        text(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = 'notifications' AND column_name = 'type'"
        )
    ).scalar()


def _add_columns(conn: Connection, insp, table: str, columns: dict[str, str]) -> None:
    if table not in set(insp.get_table_names()):
        return
    existing = {c["name"] for c in insp.get_columns(table)}
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            logger.info("Added %s.%s", table, name)


def _add_unique_index(conn: Connection, table: str, column: str, index_name: str) -> None:
    conn.execute(
        text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table} ({column}) "
            f"WHERE {column} IS NOT NULL"
        )
    )


def upgrade_schema(conn: Connection) -> None:
    Base.metadata.create_all(bind=conn)
    insp = inspect(conn)
    tables = set(insp.get_table_names())
    if "notifications" in tables:
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
    insp = inspect(conn)
    for table, columns in TABLE_COLUMNS.items():
        _add_columns(conn, insp, table, columns)
    if "filament_spools" in tables:
        _add_unique_index(conn, "filament_spools", "public_code", "ux_filament_spools_public_code")
    if "printers" in tables:
        _add_unique_index(conn, "printers", "public_code", "ux_printers_public_code")
    if "part_bins" in tables:
        _add_unique_index(conn, "part_bins", "public_code", "ux_part_bins_public_code")
    if "filament_products" in tables:
        _add_unique_index(conn, "filament_products", "barcode_id", "ux_filament_products_barcode")
