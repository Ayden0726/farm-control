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
    maintenance_due = "maintenance_due"
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
    NotificationType.maintenance_due,
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
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)

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

    part: Mapped[Part | None] = relationship(back_populates="stl_files")


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    woocommerce_product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    bom_items: Mapped[list[BomItem]] = relationship(
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
    purchase_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_printer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("printers.id", use_alter=True), nullable=True
    )
    drying_status: Mapped[DryingStatus] = mapped_column(
        Enum(DryingStatus), default=DryingStatus.unknown
    )
    low_stock_threshold_g: Mapped[float] = mapped_column(Float, default=150)
    qr_token: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")

    assigned_printer: Mapped[Printer | None] = relationship(
        foreign_keys=[assigned_printer_id], post_update=True
    )


class ProductionRun(TimestampMixin, Base):
    __tablename__ = "production_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[ProductionRunStatus] = mapped_column(
        Enum(ProductionRunStatus), default=ProductionRunStatus.draft
    )
    notes: Mapped[str] = mapped_column(Text, default="")
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

    part: Mapped[Part | None] = relationship()


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(100), index=True)
    customer_name: Mapped[str] = mapped_column(String(255), default="")
    customer_email: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(40), default="manual")
    woocommerce_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.new)
    shipping_status: Mapped[str] = mapped_column(String(40), default="unfulfilled")
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    production_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_runs.id"), nullable=True
    )

    lines: Mapped[list[OrderLine]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    part_needs: Mapped[list[OrderPartNeed]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    production_run: Mapped[ProductionRun | None] = relationship()


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
