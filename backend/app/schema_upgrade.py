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
        "build_x_mm": "DOUBLE PRECISION",
        "build_y_mm": "DOUBLE PRECISION",
        "build_z_mm": "DOUBLE PRECISION",
        "nozzle_diameter_mm": "DOUBLE PRECISION",
        "nozzle_material": "VARCHAR(40) DEFAULT ''",
        "supported_materials": "JSON DEFAULT '[]'::json",
        "max_nozzle_temp_c": "DOUBLE PRECISION",
        "max_bed_temp_c": "DOUBLE PRECISION",
        "build_plate_type": "VARCHAR(80) DEFAULT ''",
        "slicer_profile": "VARCHAR(120) DEFAULT ''",
        "camera_snapshot_url": "VARCHAR(500) DEFAULT ''",
        "camera_stream_url": "VARCHAR(500) DEFAULT ''",
        "camera_auth_encrypted": "TEXT",
        "unattended_mode": "VARCHAR(40) DEFAULT 'allowed'",
        "avg_power_watts": "DOUBLE PRECISION DEFAULT 180",
        "machine_rate_per_hour": "DOUBLE PRECISION DEFAULT 0",
        "current_downtime_reason": "VARCHAR(40)",
        "usable_x_mm": "DOUBLE PRECISION",
        "usable_y_mm": "DOUBLE PRECISION",
        "usable_z_mm": "DOUBLE PRECISION",
        "bed_shape": "VARCHAR(40) DEFAULT 'rectangular'",
        "bed_origin": "VARCHAR(40) DEFAULT 'corner'",
        "keepout_polygons": "JSON DEFAULT '[]'::json",
        "firmware": "VARCHAR(40) DEFAULT ''",
        "filament_diameter_mm": "DOUBLE PRECISION DEFAULT 1.75",
        "max_speed_mm_s": "DOUBLE PRECISION",
        "max_accel_mm_s2": "DOUBLE PRECISION",
        "max_volumetric_mm3_s": "DOUBLE PRECISION",
    },
    "part_bins": {
        "public_code": "VARCHAR(40)",
        "kind": "VARCHAR(40) DEFAULT 'finished_part'",
        "quantity_on_hand": "INTEGER DEFAULT 0",
        "quantity_reserved": "INTEGER DEFAULT 0",
    },
    "print_jobs": {
        "filament_override": "BOOLEAN DEFAULT false",
        "hold_reason": "VARCHAR(80)",
        "filament_required_g": "DOUBLE PRECISION DEFAULT 0",
        "filament_available_g": "DOUBLE PRECISION DEFAULT 0",
        "compatibility_override": "BOOLEAN DEFAULT false",
        "incompatibility_reason": "VARCHAR(500) DEFAULT ''",
        "batch_code": "VARCHAR(80)",
        "unattended_approved": "BOOLEAN DEFAULT true",
        "slice_job_id": "UUID",
    },
    "gcode_files": {
        "required_color": "VARCHAR(80) DEFAULT ''",
        "slicer": "VARCHAR(80) DEFAULT ''",
        "slicer_profile": "VARCHAR(120) DEFAULT ''",
        "nozzle_mm": "DOUBLE PRECISION",
        "layer_height_mm": "DOUBLE PRECISION",
        "min_bed_x_mm": "DOUBLE PRECISION",
        "min_bed_y_mm": "DOUBLE PRECISION",
        "required_nozzle_mm": "DOUBLE PRECISION",
        "unattended_approved": "BOOLEAN DEFAULT true",
        "production_approved": "BOOLEAN DEFAULT false",
        "stl_file_id": "UUID",
        "slicer_profile_id": "UUID",
        "slicer_profile_version": "INTEGER",
        "sliced_printer_id": "UUID",
        "plate_json": "JSON DEFAULT '{}'::json",
        "filament_length_mm": "DOUBLE PRECISION",
        "filament_volume_cm3": "DOUBLE PRECISION",
        "density_g_cm3": "DOUBLE PRECISION",
    },
    "stl_files": {
        "bbox_x_mm": "DOUBLE PRECISION",
        "bbox_y_mm": "DOUBLE PRECISION",
        "bbox_z_mm": "DOUBLE PRECISION",
        "triangle_count": "INTEGER",
        "volume_mm3": "DOUBLE PRECISION",
        "version": "INTEGER DEFAULT 1",
        "is_archived": "BOOLEAN DEFAULT false",
        "production_approved": "BOOLEAN DEFAULT false",
        "recommended_spacing_mm": "DOUBLE PRECISION DEFAULT 6",
        "orientation_json": "JSON DEFAULT '{}'::json",
    },
    "parts": {
        "min_stock": "INTEGER DEFAULT 0",
        "target_stock": "INTEGER DEFAULT 0",
    },
    "production_runs": {
        "batch_code": "VARCHAR(80)",
        "product_id": "UUID",
        "needed_by": "TIMESTAMPTZ",
    },
    "production_plans": {
        "needed_by": "TIMESTAMPTZ",
    },
    "qc_batches": {
        "failure_reason": "VARCHAR(80) DEFAULT ''",
        "photo_path": "VARCHAR(500) DEFAULT ''",
        "result": "VARCHAR(40) DEFAULT ''",
    },
    "orders": {
        "due_at": "TIMESTAMPTZ",
        "revenue": "DOUBLE PRECISION DEFAULT 0",
        "shipping_cost": "DOUBLE PRECISION DEFAULT 0",
        "payment_fee": "DOUBLE PRECISION DEFAULT 0",
        "packed_at": "TIMESTAMPTZ",
        "packing_status": "VARCHAR(40) DEFAULT 'unpacked'",
        "packing_override": "BOOLEAN DEFAULT false",
        "packing_notes": "TEXT DEFAULT ''",
        "carrier": "VARCHAR(80) DEFAULT ''",
        "tracking_number": "VARCHAR(120) DEFAULT ''",
        "public_code": "VARCHAR(40)",
        "shopify_id": "VARCHAR(40)",
        "shipping_address": "JSON",
    },
    "shipments": {
        "service": "VARCHAR(80) DEFAULT ''",
        "consignment_id": "VARCHAR(120) DEFAULT ''",
        "auspost_shipment_id": "VARCHAR(120) DEFAULT ''",
        "auspost_label_id": "VARCHAR(120) DEFAULT ''",
        "weight_g": "DOUBLE PRECISION DEFAULT 0",
        "length_cm": "DOUBLE PRECISION DEFAULT 0",
        "width_cm": "DOUBLE PRECISION DEFAULT 0",
        "height_cm": "DOUBLE PRECISION DEFAULT 0",
        "payload_snapshot": "JSON",
        "label_path": "VARCHAR(500) DEFAULT ''",
    },
    "filament_products": {
        "density_g_cm3": "DOUBLE PRECISION",
    },
    "products": {
        "shopify_product_id": "VARCHAR(40)",
    },
    "purchase_order_lines": {
        "hardware_item_id": "UUID",
        "line_kind": "VARCHAR(40) DEFAULT 'filament'",
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


def _add_enum_value(conn: Connection, type_name: str, value: str) -> None:
    exists = conn.execute(
        text(
            "SELECT 1 FROM pg_type t JOIN pg_enum e ON t.oid = e.enumtypid "
            "WHERE t.typname = :t AND e.enumlabel = :v"
        ),
        {"t": type_name, "v": value},
    ).scalar()
    if exists:
        return
    conn.execute(text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{value}'"))
    logger.info("Added enum value %s.%s", type_name, value)


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
    if "orders" in tables:
        _add_unique_index(conn, "orders", "public_code", "ux_orders_public_code")
        _add_unique_index(conn, "orders", "shopify_id", "ux_orders_shopify_id")
    if "production_runs" in tables:
        _add_unique_index(conn, "production_runs", "batch_code", "ux_production_runs_batch_code")
        run_cols = {c["name"] for c in inspect(conn).get_columns("production_runs")}
        if "product_id" in run_cols:
            conn.execute(text("ALTER TABLE production_runs ALTER COLUMN product_id DROP NOT NULL"))
    if "purchase_order_lines" in tables:
        conn.execute(text("ALTER TABLE purchase_order_lines ALTER COLUMN product_id DROP NOT NULL"))
    if "production_run_items" in tables:
        item_cols = {c["name"] for c in inspect(conn).get_columns("production_run_items")}
        if "gcode_file_id" in item_cols:
            conn.execute(text("ALTER TABLE production_run_items ALTER COLUMN gcode_file_id DROP NOT NULL"))
    if "printers" in set(inspect(conn).get_table_names()):
        conn.execute(
            text(
                "UPDATE printers SET usable_x_mm = COALESCE(usable_x_mm, build_x_mm), "
                "usable_y_mm = COALESCE(usable_y_mm, build_y_mm), "
                "usable_z_mm = COALESCE(usable_z_mm, build_z_mm) "
                "WHERE usable_x_mm IS NULL OR usable_y_mm IS NULL OR usable_z_mm IS NULL"
            )
        )
    _add_enum_value(conn, "userrole", "packing")
    _add_enum_value(conn, "userrole", "inventory")
