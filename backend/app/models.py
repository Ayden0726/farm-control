from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    admin = "admin"
    operator = "operator"
    packing = "packing"
    inventory = "inventory"
    viewer = "viewer"


class PrinterAdapterType(str, enum.Enum):
    octoprint = "octoprint"
    moonraker = "moonraker"
    creality = "creality"
    simulated = "simulated"


class PrinterStatus(str, enum.Enum):
    offline = "offline"
    idle = "idle"
    printing = "printing"
    paused = "paused"
    error = "error"
    waiting_for_bed_clear = "waiting_for_bed_clear"


class JobStatus(str, enum.Enum):
    queued = "queued"
    held = "held"
    printing = "printing"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ProductionRunStatus(str, enum.Enum):
    draft = "draft"
    queued = "queued"
    in_progress = "in_progress"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"


class OrderStatus(str, enum.Enum):
    new = "new"
    awaiting_production = "awaiting_production"
    in_production = "in_production"
    awaiting_qc = "awaiting_qc"
    ready_to_ship = "ready_to_ship"
    shipped = "shipped"
    cancelled = "cancelled"


class QcStatus(str, enum.Enum):
    awaiting_qc = "awaiting_qc"
    complete = "complete"


class DryingStatus(str, enum.Enum):
    dry = "dry"
    drying = "drying"
    needs_drying = "needs_drying"
    unknown = "unknown"


class NotificationType(str, enum.Enum):
    print_completed = "print_completed"
    print_failed = "print_failed"
    printer_offline = "printer_offline"
    printer_error = "printer_error"
    bed_needs_clearing = "bed_needs_clearing"
    production_run_completed = "production_run_completed"
    order_production_complete = "order_production_complete"
    order_ready = "order_ready"
    filament_low = "filament_low"
    filament_reorder = "filament_reorder"
    hardware_reorder = "hardware_reorder"
    maintenance_due = "maintenance_due"
    backup_failed = "backup_failed"
    info = "info"


PHONE_EVENTS: tuple[NotificationType, ...] = (
    NotificationType.print_completed,
    NotificationType.print_failed,
    NotificationType.printer_offline,
    NotificationType.printer_error,
    NotificationType.bed_needs_clearing,
    NotificationType.production_run_completed,
    NotificationType.order_production_complete,
    NotificationType.order_ready,
    NotificationType.filament_low,
    NotificationType.filament_reorder,
    NotificationType.hardware_reorder,
    NotificationType.maintenance_due,
    NotificationType.backup_failed,
)


class DeliveryStatus(str, enum.Enum):
    sent = "sent"
    failed = "failed"
    skipped = "skipped"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.operator)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, default=dict)


class Part(TimestampMixin, Base):
    __tablename__ = "parts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    min_stock: Mapped[int] = mapped_column(Integer, default=0)
    target_stock: Mapped[int] = mapped_column(Integer, default=0)

    gcode_files: Mapped[list[GCodeFile]] = relationship(back_populates="part")
    stl_files: Mapped[list[StlFile]] = relationship(back_populates="part")
    stock: Mapped[FinishedPartStock | None] = relationship(back_populates="part", uselist=False)


class GCodeFile(TimestampMixin, Base):
    __tablename__ = "gcode_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id"), nullable=True)
    quantity_per_file: Mapped[int] = mapped_column(Integer, default=1)
    material: Mapped[str] = mapped_column(String(50), default="PETG")
    estimated_time_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    estimated_filament_grams: Mapped[float] = mapped_column(Float, default=20.0)
    required_color: Mapped[str] = mapped_column(String(80), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    slicer: Mapped[str] = mapped_column(String(80), default="")
    slicer_profile: Mapped[str] = mapped_column(String(120), default="")
    nozzle_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    layer_height_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_bed_x_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_bed_y_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    required_nozzle_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    unattended_approved: Mapped[bool] = mapped_column(Boolean, default=True)
    production_approved: Mapped[bool] = mapped_column(Boolean, default=False)

    part: Mapped[Part | None] = relationship(back_populates="gcode_files")
    compatible_printers: Mapped[list[GCodePrinterCompat]] = relationship(
        back_populates="gcode", cascade="all, delete-orphan"
    )


class GCodePrinterCompat(Base):
    __tablename__ = "gcode_printer_compat"
    __table_args__ = (UniqueConstraint("gcode_id", "printer_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gcode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gcode_files.id", ondelete="CASCADE"))
    printer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("printers.id", ondelete="CASCADE"))

    gcode: Mapped[GCodeFile] = relationship(back_populates="compatible_printers")
    printer: Mapped[Printer] = relationship()


class StlFile(TimestampMixin, Base):
    __tablename__ = "stl_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    bbox_x_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_z_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    triangle_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    part: Mapped[Part | None] = relationship(back_populates="stl_files")


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    woocommerce_product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shopify_product_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    bom_items: Mapped[list[BomItem]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    bom_hardware: Mapped[list[BomHardwareItem]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class BomItem(Base):
    __tablename__ = "bom_items"
    __table_args__ = (UniqueConstraint("product_id", "part_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)

    product: Mapped[Product] = relationship(back_populates="bom_items")
    part: Mapped[Part] = relationship()


class Printer(TimestampMixin, Base):
    __tablename__ = "printers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(255), default="")
    adapter_type: Mapped[PrinterAdapterType] = mapped_column(Enum(PrinterAdapterType))
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[PrinterStatus] = mapped_column(
        Enum(PrinterStatus), default=PrinterStatus.offline
    )
    nozzle_temp: Mapped[float] = mapped_column(Float, default=0)
    bed_temp: Mapped[float] = mapped_column(Float, default=0)
    target_nozzle: Mapped[float] = mapped_column(Float, default=0)
    target_bed: Mapped[float] = mapped_column(Float, default=0)
    current_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    progress_percent: Mapped[float] = mapped_column(Float, default=0)
    time_remaining_seconds: Mapped[int] = mapped_column(Integer, default=0)
    current_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assigned_spool_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("filament_spools.id", use_alter=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_print_seconds: Mapped[int] = mapped_column(Integer, default=0)
    total_jobs: Mapped[int] = mapped_column(Integer, default=0)
    failed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    last_maintenance_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    maintenance_interval_hours: Mapped[float] = mapped_column(Float, default=200)
    maintenance_notes: Mapped[str] = mapped_column(Text, default="")
    qr_token: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    public_code: Mapped[str | None] = mapped_column(String(40), unique=True, index=True, nullable=True)
    build_x_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    build_y_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    build_z_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    nozzle_diameter_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    nozzle_material: Mapped[str] = mapped_column(String(40), default="")
    supported_materials: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_nozzle_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_bed_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    build_plate_type: Mapped[str] = mapped_column(String(80), default="")
    slicer_profile: Mapped[str] = mapped_column(String(120), default="")
    camera_snapshot_url: Mapped[str] = mapped_column(String(500), default="")
    camera_stream_url: Mapped[str] = mapped_column(String(500), default="")
    camera_auth_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    unattended_mode: Mapped[str] = mapped_column(String(40), default="allowed")
    avg_power_watts: Mapped[float] = mapped_column(Float, default=180)
    machine_rate_per_hour: Mapped[float] = mapped_column(Float, default=0)
    current_downtime_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)

    assigned_spool: Mapped[FilamentSpool | None] = relationship(
        foreign_keys=[assigned_spool_id], post_update=True
    )
    maintenance_logs: Mapped[list[MaintenanceLog]] = relationship(back_populates="printer")


class FilamentSpool(TimestampMixin, Base):
    __tablename__ = "filament_spools"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    manufacturer: Mapped[str] = mapped_column(String(100), default="")
    material: Mapped[str] = mapped_column(String(50), default="PETG")
    color: Mapped[str] = mapped_column(String(80), default="")
    initial_weight_g: Mapped[float] = mapped_column(Float, default=1000)
    remaining_weight_g: Mapped[float] = mapped_column(Float, default=1000)
    cost: Mapped[float] = mapped_column(Float, default=0)
    cost_per_kg: Mapped[float] = mapped_column(Float, default=0)
    purchase_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_received: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_opened: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_dried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_printer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("printers.id", use_alter=True), nullable=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("filament_products.id"), nullable=True, index=True
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("storage_locations.id"), nullable=True, index=True
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=True
    )
    drying_status: Mapped[DryingStatus] = mapped_column(
        Enum(DryingStatus), default=DryingStatus.unknown
    )
    low_stock_threshold_g: Mapped[float] = mapped_column(Float, default=150)
    qr_token: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    public_code: Mapped[str | None] = mapped_column(String(40), unique=True, index=True, nullable=True)
    is_sealed: Mapped[bool] = mapped_column(Boolean, default=True)
    is_empty: Mapped[bool] = mapped_column(Boolean, default=False)
    consumed_g: Mapped[float] = mapped_column(Float, default=0)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")

    assigned_printer: Mapped[Printer | None] = relationship(
        foreign_keys=[assigned_printer_id], post_update=True
    )
    product: Mapped[FilamentProduct | None] = relationship(back_populates="spools")
    location: Mapped[StorageLocation | None] = relationship(back_populates="spools")
    supplier: Mapped[Supplier | None] = relationship()
    purchase_order: Mapped[PurchaseOrder | None] = relationship()
    transactions: Mapped[list[FilamentTransaction]] = relationship(back_populates="spool")


class ProductionRun(TimestampMixin, Base):
    __tablename__ = "production_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[ProductionRunStatus] = mapped_column(
        Enum(ProductionRunStatus), default=ProductionRunStatus.draft
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    batch_code: Mapped[str | None] = mapped_column(String(80), unique=True, index=True, nullable=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    needed_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[ProductionRunItem]] = relationship(
        back_populates="production_run", cascade="all, delete-orphan"
    )
    printers: Mapped[list[ProductionRunPrinter]] = relationship(
        back_populates="production_run", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[PrintJob]] = relationship(back_populates="production_run")


class ProductionRunItem(Base):
    __tablename__ = "production_run_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    production_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_runs.id", ondelete="CASCADE")
    )
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"))
    gcode_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gcode_files.id"), nullable=True
    )
    required_qty: Mapped[int] = mapped_column(Integer, default=1)
    printed_qty: Mapped[int] = mapped_column(Integer, default=0)
    passed_qc: Mapped[int] = mapped_column(Integer, default=0)
    failed_qc: Mapped[int] = mapped_column(Integer, default=0)

    production_run: Mapped[ProductionRun] = relationship(back_populates="items")
    part: Mapped[Part] = relationship()
    gcode_file: Mapped[GCodeFile | None] = relationship()

    @property
    def remaining_qty(self) -> int:
        return max(0, self.required_qty - self.passed_qc)

    @property
    def remaining_to_print(self) -> int:
        return max(0, self.required_qty - self.printed_qty)


class ProductionRunPrinter(Base):
    __tablename__ = "production_run_printers"
    __table_args__ = (UniqueConstraint("production_run_id", "printer_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    production_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_runs.id", ondelete="CASCADE")
    )
    printer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("printers.id", ondelete="CASCADE"))

    production_run: Mapped[ProductionRun] = relationship(back_populates="printers")
    printer: Mapped[Printer] = relationship()


class PrintJob(TimestampMixin, Base):
    __tablename__ = "print_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    production_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_runs.id"), nullable=True
    )
    production_run_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_run_items.id"), nullable=True
    )
    gcode_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gcode_files.id"))
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id"), nullable=True)
    assigned_printer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("printers.id"), nullable=True
    )
    actual_printer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("printers.id"), nullable=True
    )
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued, index=True)
    queue_position: Mapped[int] = mapped_column(Integer, default=0, index=True)
    quantity_produced: Mapped[int] = mapped_column(Integer, default=1)
    progress_percent: Mapped[float] = mapped_column(Float, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pause_seconds: Mapped[float] = mapped_column(Float, default=0)
    fail_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_filament_grams: Mapped[float] = mapped_column(Float, default=0)
    filament_used_grams: Mapped[float] = mapped_column(Float, default=0)
    filament_cost: Mapped[float] = mapped_column(Float, default=0)
    spool_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("filament_spools.id"), nullable=True
    )
    estimated_time_seconds: Mapped[int] = mapped_column(Integer, default=0)
    qr_token: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    filament_override: Mapped[bool] = mapped_column(Boolean, default=False)
    hold_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    filament_required_g: Mapped[float] = mapped_column(Float, default=0)
    filament_available_g: Mapped[float] = mapped_column(Float, default=0)
    compatibility_override: Mapped[bool] = mapped_column(Boolean, default=False)
    incompatibility_reason: Mapped[str] = mapped_column(String(500), default="")
    batch_code: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    unattended_approved: Mapped[bool] = mapped_column(Boolean, default=True)

    production_run: Mapped[ProductionRun | None] = relationship(back_populates="jobs")
    production_run_item: Mapped[ProductionRunItem | None] = relationship()
    gcode_file: Mapped[GCodeFile] = relationship()
    part: Mapped[Part | None] = relationship()
    assigned_printer: Mapped[Printer | None] = relationship(foreign_keys=[assigned_printer_id])
    actual_printer: Mapped[Printer | None] = relationship(foreign_keys=[actual_printer_id])
    spool: Mapped[FilamentSpool | None] = relationship()


class QcBatch(TimestampMixin, Base):
    __tablename__ = "qc_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("print_jobs.id"))
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"))
    production_run_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_run_items.id"), nullable=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[QcStatus] = mapped_column(Enum(QcStatus), default=QcStatus.awaiting_qc)
    notes: Mapped[str] = mapped_column(Text, default="")
    inspected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str] = mapped_column(String(80), default="")
    photo_path: Mapped[str] = mapped_column(String(500), default="")
    result: Mapped[str] = mapped_column(String(40), default="")

    job: Mapped[PrintJob] = relationship()
    part: Mapped[Part] = relationship()
    production_run_item: Mapped[ProductionRunItem | None] = relationship()


class FinishedPartStock(Base):
    __tablename__ = "finished_part_stock"

    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"), primary_key=True)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0)
    quantity_reserved: Mapped[int] = mapped_column(Integer, default=0)

    part: Mapped[Part] = relationship(back_populates="stock")

    @property
    def quantity_available(self) -> int:
        return max(0, self.quantity_on_hand - self.quantity_reserved)


class StockMovement(TimestampMixin, Base):
    __tablename__ = "stock_movements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(50))
    ref_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class PartBin(TimestampMixin, Base):
    __tablename__ = "part_bins"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    location: Mapped[str] = mapped_column(String(255), default="")
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id"), nullable=True)
    qr_token: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    public_code: Mapped[str | None] = mapped_column(String(40), unique=True, index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(40), default="finished_part")
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0)
    quantity_reserved: Mapped[int] = mapped_column(Integer, default=0)

    part: Mapped[Part | None] = relationship()
    movements: Mapped[list[BinMovement]] = relationship(back_populates="bin")

    @property
    def quantity_available(self) -> int:
        return max(0, self.quantity_on_hand - self.quantity_reserved)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(100), index=True)
    customer_name: Mapped[str] = mapped_column(String(255), default="")
    customer_email: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(40), default="manual")
    woocommerce_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    shopify_id: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.new)
    shipping_status: Mapped[str] = mapped_column(String(40), default="unfulfilled")
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    production_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_runs.id"), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revenue: Mapped[float] = mapped_column(Float, default=0)
    shipping_cost: Mapped[float] = mapped_column(Float, default=0)
    payment_fee: Mapped[float] = mapped_column(Float, default=0)
    packed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    packing_status: Mapped[str] = mapped_column(String(40), default="unpacked")
    packing_override: Mapped[bool] = mapped_column(Boolean, default=False)
    packing_notes: Mapped[str] = mapped_column(Text, default="")
    carrier: Mapped[str] = mapped_column(String(80), default="")
    tracking_number: Mapped[str] = mapped_column(String(120), default="")
    public_code: Mapped[str | None] = mapped_column(String(40), unique=True, index=True, nullable=True)
    shipping_address: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    lines: Mapped[list[OrderLine]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    part_needs: Mapped[list[OrderPartNeed]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    production_run: Mapped[ProductionRun | None] = relationship()
    shipments: Mapped[list["Shipment"]] = relationship(back_populates="order")


class OrderLine(Base):
    __tablename__ = "order_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    order: Mapped[Order] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class OrderPartNeed(Base):
    __tablename__ = "order_part_needs"
    __table_args__ = (UniqueConstraint("order_id", "part_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"))
    required_qty: Mapped[int] = mapped_column(Integer, default=0)
    reserved_qty: Mapped[int] = mapped_column(Integer, default=0)
    to_produce: Mapped[int] = mapped_column(Integer, default=0)

    order: Mapped[Order] = relationship(back_populates="part_needs")
    part: Mapped[Part] = relationship()


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(20), default="info")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    printer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    printer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    job_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    production_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    production_run_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    order_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    deep_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    deliveries: Mapped[list[NotificationDelivery]] = relationship(
        back_populates="notification", cascade="all, delete-orphan"
    )


class NotificationDelivery(TimestampMixin, Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="sent", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    notification: Mapped[Notification] = relationship(back_populates="deliveries")


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    event_type: Mapped[str] = mapped_column(String(50), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class PrinterNotificationPreference(Base):
    __tablename__ = "printer_notification_preferences"
    __table_args__ = (UniqueConstraint("printer_id", "event_type"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    printer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("printers.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    printer: Mapped[Printer] = relationship()


class NotificationProviderSetting(TimestampMixin, Base):
    __tablename__ = "notification_provider_settings"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    public_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    secrets_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)


class MaintenanceLog(TimestampMixin, Base):
    __tablename__ = "maintenance_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    printer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("printers.id", ondelete="CASCADE"))
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    hours_at_service: Mapped[float] = mapped_column(Float, default=0)
    kind: Mapped[str] = mapped_column(String(50), default="service")
    notes: Mapped[str] = mapped_column(Text, default="")

    printer: Mapped[Printer] = relationship(back_populates="maintenance_logs")


class Supplier(TimestampMixin, Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    website: Mapped[str] = mapped_column(String(500), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    adapter_type: Mapped[str] = mapped_column(String(40), default="url")
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class StorageLocation(TimestampMixin, Base):
    __tablename__ = "storage_locations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    kind: Mapped[str] = mapped_column(String(40), default="shelf")
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    printer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("printers.id"), nullable=True)

    printer: Mapped[Printer | None] = relationship()
    spools: Mapped[list[FilamentSpool]] = relationship(back_populates="location")


class FilamentProduct(TimestampMixin, Base):
    __tablename__ = "filament_products"
    __table_args__ = (Index("ix_filament_products_barcode", "barcode_id", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    barcode_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    manufacturer: Mapped[str] = mapped_column(String(100))
    product_name: Mapped[str] = mapped_column(String(255), default="")
    material: Mapped[str] = mapped_column(String(50), default="PETG")
    color: Mapped[str] = mapped_column(String(80), default="")
    spool_size_label: Mapped[str] = mapped_column(String(40), default="1 kg")
    filament_weight_g: Mapped[float] = mapped_column(Float, default=1000)
    purchase_cost: Mapped[float] = mapped_column(Float, default=0)
    cost_per_kg: Mapped[float] = mapped_column(Float, default=0)
    preferred_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id"), nullable=True
    )
    backup_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id"), nullable=True
    )
    supplier_sku: Mapped[str] = mapped_column(String(120), default="")
    supplier_url: Mapped[str] = mapped_column(String(500), default="")
    nozzle_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    bed_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    min_stock_g: Mapped[float] = mapped_column(Float, default=6000)
    target_stock_g: Mapped[float] = mapped_column(Float, default=18000)
    preferred_spool_weight_g: Mapped[float] = mapped_column(Float, default=3000)
    normal_price: Mapped[float] = mapped_column(Float, default=0)
    max_price: Mapped[float] = mapped_column(Float, default=0)
    max_price_per_kg: Mapped[float] = mapped_column(Float, default=0)
    min_reorder_qty: Mapped[int] = mapped_column(Integer, default=1)
    reorder_multiple: Mapped[int] = mapped_column(Integer, default=1)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7)
    reorder_mode: Mapped[str] = mapped_column(String(40), default="create_purchase_order")
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    max_po_amount: Mapped[float] = mapped_column(Float, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    preferred_supplier: Mapped[Supplier | None] = relationship(foreign_keys=[preferred_supplier_id])
    backup_supplier: Mapped[Supplier | None] = relationship(foreign_keys=[backup_supplier_id])
    spools: Mapped[list[FilamentSpool]] = relationship(back_populates="product")


class IdSequence(Base):
    __tablename__ = "id_sequences"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, default=1)


class FilamentTransaction(TimestampMixin, Base):
    __tablename__ = "filament_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    spool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("filament_spools.id"), index=True)
    previous_g: Mapped[float] = mapped_column(Float)
    amount_g: Mapped[float] = mapped_column(Float)
    remaining_g: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(80), index=True)
    printer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("printers.id"), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("print_jobs.id"), nullable=True)
    production_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_runs.id"), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")

    spool: Mapped[FilamentSpool] = relationship(back_populates="transactions")
    printer: Mapped[Printer | None] = relationship()
    job: Mapped[PrintJob | None] = relationship()
    production_run: Mapped[ProductionRun | None] = relationship()


class InventoryAudit(TimestampMixin, Base):
    __tablename__ = "inventory_audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(120), default="system")


class PurchaseOrder(TimestampMixin, Base):
    __tablename__ = "purchase_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    tracking: Mapped[str] = mapped_column(String(120), default="")
    total: Mapped[float] = mapped_column(Float, default=0)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_delivery: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_created: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True)

    supplier: Mapped[Supplier | None] = relationship()
    lines: Mapped[list[PurchaseOrderLine]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("filament_products.id"), nullable=True
    )
    hardware_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hardware_items.id"), nullable=True
    )
    line_kind: Mapped[str] = mapped_column(String(40), default="filament")
    quantity_ordered: Mapped[int] = mapped_column(Integer, default=1)
    quantity_received: Mapped[int] = mapped_column(Integer, default=0)
    spool_weight_g: Mapped[float] = mapped_column(Float, default=1000)
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    price_per_kg: Mapped[float] = mapped_column(Float, default=0)
    supplier_sku: Mapped[str] = mapped_column(String(120), default="")

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    product: Mapped[FilamentProduct | None] = relationship()
    hardware_item: Mapped[HardwareItem | None] = relationship()


class BomHardwareItem(Base):
    __tablename__ = "bom_hardware_items"
    __table_args__ = (UniqueConstraint("product_id", "hardware_item_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    hardware_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hardware_items.id"))
    quantity: Mapped[float] = mapped_column(Float, default=1)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)

    product: Mapped[Product] = relationship(back_populates="bom_hardware")
    hardware_item: Mapped[HardwareItem] = relationship()


class HardwareItem(TimestampMixin, Base):
    __tablename__ = "hardware_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(80), default="hardware")
    supplier: Mapped[str] = mapped_column(String(255), default="")
    supplier_url: Mapped[str] = mapped_column(String(500), default="")
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    purchase_cost: Mapped[float] = mapped_column(Float, default=0)
    unit_cost: Mapped[float] = mapped_column(Float, default=0)
    quantity_on_hand: Mapped[float] = mapped_column(Float, default=0)
    quantity_reserved: Mapped[float] = mapped_column(Float, default=0)
    min_stock: Mapped[float] = mapped_column(Float, default=0)
    target_stock: Mapped[float] = mapped_column(Float, default=0)
    storage_location: Mapped[str] = mapped_column(String(255), default="")
    reorder_mode: Mapped[str] = mapped_column(String(40), default="off")
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    public_code: Mapped[str | None] = mapped_column(String(40), unique=True, index=True, nullable=True)
    barcode: Mapped[str] = mapped_column(String(80), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def quantity_available(self) -> float:
        return max(0.0, (self.quantity_on_hand or 0) - (self.quantity_reserved or 0))


class HardwareMovement(TimestampMixin, Base):
    __tablename__ = "hardware_movements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hardware_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hardware_items.id"), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(50))
    ref_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class BinMovement(TimestampMixin, Base):
    __tablename__ = "bin_movements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("part_bins.id", ondelete="CASCADE"), index=True)
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(50))
    notes: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(120), default="operator")

    bin: Mapped[PartBin] = relationship(back_populates="movements")


class ProductionPlan(TimestampMixin, Base):
    __tablename__ = "production_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    needed_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    production_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_runs.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(120), default="")

    lines: Mapped[list[ProductionPlanLine]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class ProductionPlanLine(Base):
    __tablename__ = "production_plan_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("production_plans.id", ondelete="CASCADE"))
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"))
    gcode_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("gcode_files.id"), nullable=True)
    printer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("printers.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    jobs_needed: Mapped[int] = mapped_column(Integer, default=1)
    estimated_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estimated_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    required_filament_g: Mapped[float] = mapped_column(Float, default=0)
    filament_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    compatible: Mapped[bool] = mapped_column(Boolean, default=True)
    incompatibility_reason: Mapped[str] = mapped_column(String(500), default="")
    order_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    order_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(String(255), default="")
    included: Mapped[bool] = mapped_column(Boolean, default=True)

    plan: Mapped[ProductionPlan] = relationship(back_populates="lines")
    part: Mapped[Part] = relationship()
    gcode_file: Mapped[GCodeFile | None] = relationship()
    printer: Mapped[Printer | None] = relationship()


class AssemblyKit(TimestampMixin, Base):
    __tablename__ = "assembly_kits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    public_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default="parts_required", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assembled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped[Product] = relationship()
    order: Mapped[Order | None] = relationship()
    lines: Mapped[list[AssemblyKitLine]] = relationship(
        back_populates="kit", cascade="all, delete-orphan"
    )


class AssemblyKitLine(Base):
    __tablename__ = "assembly_kit_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assembly_kits.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), default="part")
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id"), nullable=True)
    hardware_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hardware_items.id"), nullable=True
    )
    required_qty: Mapped[float] = mapped_column(Float, default=1)
    reserved_qty: Mapped[float] = mapped_column(Float, default=0)
    available_qty: Mapped[float] = mapped_column(Float, default=0)

    kit: Mapped[AssemblyKit] = relationship(back_populates="lines")
    part: Mapped[Part | None] = relationship()
    hardware_item: Mapped[HardwareItem | None] = relationship()


class QcFailureReason(Base):
    __tablename__ = "qc_failure_reasons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    label: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class MaintenanceRule(TimestampMixin, Base):
    __tablename__ = "maintenance_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(80), default="service")
    printer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("printers.id"), nullable=True)
    interval_print_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    interval_prints: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_filament_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    printer: Mapped[Printer | None] = relationship()


class MaintenanceTask(TimestampMixin, Base):
    __tablename__ = "maintenance_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("maintenance_rules.id"), nullable=True)
    printer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("printers.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(80), default="service")
    status: Mapped[str] = mapped_column(String(40), default="due", index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    printer: Mapped[Printer] = relationship()


class PrinterDowntime(TimestampMixin, Base):
    __tablename__ = "printer_downtime"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    printer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("printers.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(40), default="unknown")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    printer: Mapped[Printer] = relationship()


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    previous_value: Mapped[Any] = mapped_column(JSON, default=dict)
    new_value: Mapped[Any] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    source: Mapped[str] = mapped_column(String(40), default="api")


class PartCostSnapshot(TimestampMixin, Base):
    __tablename__ = "part_cost_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"), index=True)
    gcode_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("gcode_files.id"), nullable=True)
    filament_cost: Mapped[float] = mapped_column(Float, default=0)
    electricity_cost: Mapped[float] = mapped_column(Float, default=0)
    failure_cost: Mapped[float] = mapped_column(Float, default=0)
    machine_cost: Mapped[float] = mapped_column(Float, default=0)
    labour_cost: Mapped[float] = mapped_column(Float, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0)
    filament_cost_per_kg: Mapped[float] = mapped_column(Float, default=0)
    electricity_price: Mapped[float] = mapped_column(Float, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")


class PackingCheck(TimestampMixin, Base):
    __tablename__ = "packing_checks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(40), default="part")
    required_qty: Mapped[float] = mapped_column(Float, default=1)
    confirmed_qty: Mapped[float] = mapped_column(Float, default=0)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    missing: Mapped[bool] = mapped_column(Boolean, default=False)

    order: Mapped[Order] = relationship()


class Shipment(TimestampMixin, Base):
    __tablename__ = "shipments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="manual")
    carrier: Mapped[str] = mapped_column(String(80), default="")
    tracking_number: Mapped[str] = mapped_column(String(120), default="")
    cost: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(40), default="created")
    label_url: Mapped[str] = mapped_column(String(500), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    service: Mapped[str] = mapped_column(String(80), default="")
    consignment_id: Mapped[str] = mapped_column(String(120), default="")
    auspost_shipment_id: Mapped[str] = mapped_column(String(120), default="")
    auspost_label_id: Mapped[str] = mapped_column(String(120), default="")
    weight_g: Mapped[float] = mapped_column(Float, default=0)
    length_cm: Mapped[float] = mapped_column(Float, default=0)
    width_cm: Mapped[float] = mapped_column(Float, default=0)
    height_cm: Mapped[float] = mapped_column(Float, default=0)
    payload_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    label_path: Mapped[str] = mapped_column(String(500), default="")

    order: Mapped[Order] = relationship(back_populates="shipments")


class BackupRecord(TimestampMixin, Base):
    __tablename__ = "backup_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(40), default="manual")
    status: Mapped[str] = mapped_column(String(40), default="ok")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    include_files: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

