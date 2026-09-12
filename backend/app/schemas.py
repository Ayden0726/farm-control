from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    email: str
    full_name: str


class LoginIn(BaseModel):
    email: str
    password: str


class SetupIn(BaseModel):
    email: str
    password: str = Field(min_length=8)
    full_name: str = "Farm Admin"
    company_name: str = "Print Farm"
    load_demo: bool = True


class SetupStatus(BaseModel):
    needs_setup: bool
    company_name: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool


class PrinterIn(BaseModel):
    name: str
    model: str = ""
    adapter_type: Literal["octoprint", "moonraker", "creality", "simulated"]
    base_url: str | None = None
    api_key: str | None = None
    extra_config: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True
    assigned_spool_id: UUID | None = None
    maintenance_interval_hours: float = 200
    maintenance_notes: str = ""
    build_x_mm: float | None = None
    build_y_mm: float | None = None
    build_z_mm: float | None = None
    nozzle_diameter_mm: float | None = None
    nozzle_material: str = ""
    supported_materials: list[str] = Field(default_factory=list)
    max_nozzle_temp_c: float | None = None
    max_bed_temp_c: float | None = None
    build_plate_type: str = ""
    slicer_profile: str = ""
    camera_snapshot_url: str = ""
    camera_stream_url: str = ""
    camera_auth: str | None = None
    unattended_mode: str = "allowed"
    avg_power_watts: float = 180
    machine_rate_per_hour: float = 0


class PrinterUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    adapter_type: Literal["octoprint", "moonraker", "creality", "simulated"] | None = None
    base_url: str | None = None
    api_key: str | None = None
    extra_config: dict[str, Any] | None = None
    is_enabled: bool | None = None
    assigned_spool_id: UUID | None = None
    maintenance_interval_hours: float | None = None
    maintenance_notes: str | None = None
    build_x_mm: float | None = None
    build_y_mm: float | None = None
    build_z_mm: float | None = None
    nozzle_diameter_mm: float | None = None
    nozzle_material: str | None = None
    supported_materials: list[str] | None = None
    max_nozzle_temp_c: float | None = None
    max_bed_temp_c: float | None = None
    build_plate_type: str | None = None
    slicer_profile: str | None = None
    camera_snapshot_url: str | None = None
    camera_stream_url: str | None = None
    camera_auth: str | None = None
    unattended_mode: str | None = None
    avg_power_watts: float | None = None
    machine_rate_per_hour: float | None = None
    current_downtime_reason: str | None = None


class PrinterOut(BaseModel):
    id: UUID
    name: str
    model: str
    adapter_type: str
    base_url: str | None
    has_api_key: bool
    extra_config: dict[str, Any]
    is_enabled: bool
    status: str
    nozzle_temp: float
    bed_temp: float
    target_nozzle: float
    target_bed: float
    current_file: str | None
    progress_percent: float
    time_remaining_seconds: int
    current_job_id: UUID | None
    assigned_spool_id: UUID | None
    assigned_spool_name: str | None = None
    last_error: str | None
    last_seen_at: datetime | None
    total_print_seconds: int
    total_jobs: int
    failed_jobs: int
    last_maintenance_at: datetime | None
    maintenance_interval_hours: float
    maintenance_notes: str
    qr_token: str
    hours_until_maintenance: float | None = None
    public_code: str | None = None
    assigned_spool_code: str | None = None
    assigned_spool_remaining_g: float | None = None
    build_x_mm: float | None = None
    build_y_mm: float | None = None
    build_z_mm: float | None = None
    nozzle_diameter_mm: float | None = None
    nozzle_material: str = ""
    supported_materials: list[str] = Field(default_factory=list)
    max_nozzle_temp_c: float | None = None
    max_bed_temp_c: float | None = None
    build_plate_type: str = ""
    slicer_profile: str = ""
    unattended_mode: str = "allowed"
    avg_power_watts: float = 180
    machine_rate_per_hour: float = 0
    current_downtime_reason: str | None = None
    camera_configured: bool = False
    camera_status: str = "offline"
    camera_proxy_url: str | None = None


class PartIn(BaseModel):
    sku: str
    name: str
    description: str = ""
    is_active: bool = True
    min_stock: int = 0
    target_stock: int = 0


class PartOut(BaseModel):
    id: UUID
    sku: str
    name: str
    description: str
    is_active: bool
    quantity_on_hand: int = 0
    quantity_reserved: int = 0
    quantity_available: int = 0
    min_stock: int = 0
    target_stock: int = 0


class GCodeOut(BaseModel):
    id: UUID
    filename: str
    part_id: UUID | None
    part_sku: str | None = None
    quantity_per_file: int
    material: str
    estimated_time_seconds: int
    estimated_filament_grams: float
    version: int
    is_archived: bool
    notes: str
    file_size_bytes: int
    compatible_printer_ids: list[UUID] = []
    created_at: datetime
    required_color: str = ""
    slicer: str = ""
    slicer_profile: str = ""
    nozzle_mm: float | None = None
    layer_height_mm: float | None = None
    min_bed_x_mm: float | None = None
    min_bed_y_mm: float | None = None
    required_nozzle_mm: float | None = None
    unattended_approved: bool = True
    production_approved: bool = False


class GCodeUpdate(BaseModel):
    part_id: UUID | None = None
    quantity_per_file: int | None = None
    material: str | None = None
    estimated_time_seconds: int | None = None
    estimated_filament_grams: float | None = None
    notes: str | None = None
    is_archived: bool | None = None
    compatible_printer_ids: list[UUID] | None = None
    slicer: str | None = None
    slicer_profile: str | None = None
    nozzle_mm: float | None = None
    layer_height_mm: float | None = None
    min_bed_x_mm: float | None = None
    min_bed_y_mm: float | None = None
    required_nozzle_mm: float | None = None
    unattended_approved: bool | None = None
    production_approved: bool | None = None
    required_color: str | None = None


class StlOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    filename: str
    part_id: UUID | None
    part_sku: str | None = None
    notes: str
    file_size_bytes: int
    created_at: datetime
    bbox_x_mm: float | None = None
    bbox_y_mm: float | None = None
    bbox_z_mm: float | None = None
    triangle_count: int | None = None
    copies_per_plate: int | None = None
    pack_rotated: bool = False
    pack_cols: int | None = None
    pack_rows: int | None = None
    pack_bed_x_mm: float | None = None
    pack_bed_y_mm: float | None = None
    pack_gap_mm: float | None = None


class BomItemIn(BaseModel):
    part_id: UUID
    quantity: int = 1
    is_optional: bool = False


class BomHardwareIn(BaseModel):
    hardware_item_id: UUID
    quantity: float = 1
    is_optional: bool = False


class ProductIn(BaseModel):
    sku: str
    name: str
    description: str = ""
    woocommerce_product_id: int | None = None
    shopify_product_id: str | None = None
    is_active: bool = True
    bom: list[BomItemIn] = Field(default_factory=list)
    hardware_bom: list[BomHardwareIn] = Field(default_factory=list)


class BomItemOut(BaseModel):
    id: UUID
    part_id: UUID
    part_sku: str
    part_name: str
    quantity: int
    is_optional: bool


class BomHardwareOut(BaseModel):
    id: UUID
    hardware_item_id: UUID
    sku: str
    name: str
    quantity: float
    is_optional: bool


class ProductOut(BaseModel):
    id: UUID
    sku: str
    name: str
    description: str
    woocommerce_product_id: int | None
    shopify_product_id: str | None = None
    is_active: bool
    bom: list[BomItemOut] = []
    hardware_bom: list[BomHardwareOut] = []


class ProductionItemIn(BaseModel):
    part_id: UUID
    gcode_file_id: UUID | None = None
    required_qty: int = 1


class ProductionProductIn(BaseModel):
    product_id: UUID
    quantity: int = 1
    include_optional: bool = False


class ProductionRunIn(BaseModel):
    name: str
    notes: str = ""
    printer_ids: list[UUID] = Field(default_factory=list)
    items: list[ProductionItemIn] = Field(default_factory=list)
    start_immediately: bool = True
    product_id: UUID | None = None
    product_qty: int = 1
    include_optional: bool = False
    needed_by: str | None = None


class ProductionItemOut(BaseModel):
    id: UUID
    part_id: UUID
    part_sku: str
    part_name: str
    gcode_file_id: UUID | None
    gcode_filename: str | None = None
    required_qty: int
    printed_qty: int
    passed_qc: int
    failed_qc: int
    remaining_qty: int
    remaining_to_print: int


class ProductionRunOut(BaseModel):
    id: UUID
    name: str
    status: str
    notes: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    printer_ids: list[UUID]
    items: list[ProductionItemOut]
    queued_jobs: int = 0
    printing_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    batch_code: str | None = None
    needed_by: datetime | None = None


class JobOut(BaseModel):
    id: UUID
    production_run_id: UUID | None
    production_run_name: str | None = None
    gcode_file_id: UUID
    gcode_filename: str | None = None
    part_id: UUID | None
    part_sku: str | None = None
    assigned_printer_id: UUID | None
    assigned_printer_name: str | None = None
    actual_printer_id: UUID | None
    actual_printer_name: str | None = None
    status: str
    queue_position: int
    quantity_produced: int
    progress_percent: float
    started_at: datetime | None
    completed_at: datetime | None
    fail_reason: str | None
    estimated_filament_grams: float
    filament_used_grams: float
    filament_cost: float
    estimated_time_seconds: int
    qr_token: str
    created_at: datetime
    filament_override: bool = False
    hold_reason: str | None = None
    filament_required_g: float = 0
    filament_available_g: float = 0
    required_material: str | None = None
    required_color: str | None = None
    spool_code: str | None = None
    compatibility_override: bool = False
    incompatibility_reason: str = ""
    batch_code: str | None = None


class JobAction(BaseModel):
    printer_id: UUID | None = None
    position: int | None = None


class QcIn(BaseModel):
    passed: int
    failed: int
    notes: str = ""
    failure_reason: str = ""


class QcBatchOut(BaseModel):
    id: UUID
    job_id: UUID
    part_id: UUID
    part_sku: str | None = None
    part_name: str | None = None
    quantity: int
    passed: int
    failed: int
    status: str
    notes: str
    created_at: datetime
    inspected_at: datetime | None
    gcode_filename: str | None = None
    failure_reason: str = ""
    result: str = ""


class SpoolIn(BaseModel):
    name: str
    manufacturer: str = ""
    material: str = "PETG"
    color: str = ""
    initial_weight_g: float = 1000
    remaining_weight_g: float | None = None
    cost: float = 0
    purchase_date: datetime | None = None
    assigned_printer_id: UUID | None = None
    drying_status: str = "unknown"
    low_stock_threshold_g: float = 150
    notes: str = ""


class SpoolOut(BaseModel):
    id: UUID
    name: str
    manufacturer: str
    material: str
    color: str
    initial_weight_g: float
    remaining_weight_g: float
    cost: float
    cost_per_kg: float
    purchase_date: datetime | None
    assigned_printer_id: UUID | None
    assigned_printer_name: str | None = None
    drying_status: str
    low_stock_threshold_g: float
    qr_token: str
    is_archived: bool
    notes: str
    is_low: bool = False
    public_code: str | None = None
    product_id: UUID | None = None
    barcode_id: str | None = None
    is_sealed: bool = True
    is_empty: bool = False
    consumed_g: float = 0
    location_name: str | None = None


class OrderLineIn(BaseModel):
    product_id: UUID
    quantity: int = 1


class OrderIn(BaseModel):
    reference: str
    customer_name: str = ""
    customer_email: str = ""
    notes: str = ""
    lines: list[OrderLineIn]
    printer_ids: list[UUID] = Field(default_factory=list)
    create_production: bool = True


class OrderPartNeedOut(BaseModel):
    part_id: UUID
    part_sku: str
    part_name: str
    required_qty: int
    reserved_qty: int
    to_produce: int


class OrderLineOut(BaseModel):
    product_id: UUID
    product_sku: str
    product_name: str
    quantity: int


class OrderOut(BaseModel):
    id: UUID
    reference: str
    customer_name: str
    customer_email: str
    notes: str
    source: str
    woocommerce_id: int | None
    shopify_id: str | None = None
    status: str
    shipping_status: str
    shipped_at: datetime | None
    production_run_id: UUID | None
    created_at: datetime
    lines: list[OrderLineOut]
    part_needs: list[OrderPartNeedOut]
    public_code: str | None = None
    packing_status: str = "unpacked"
    packed_at: datetime | None = None
    packing_override: bool = False
    packing_notes: str = ""
    revenue: float = 0
    shipping_cost: float = 0
    payment_fee: float = 0
    carrier: str = ""
    tracking_number: str = ""
    due_at: datetime | None = None


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    type: str
    title: str
    body: str
    severity: str
    is_read: bool
    entity_type: str | None
    entity_id: str | None
    created_at: datetime


class MaintenanceIn(BaseModel):
    notes: str = ""
    kind: str = "service"
    hours_at_service: float | None = None


class MaintenanceOut(BaseModel):
    id: UUID
    printer_id: UUID
    printer_name: str | None = None
    performed_at: datetime
    hours_at_service: float
    kind: str
    notes: str


class BinIn(BaseModel):
    name: str
    location: str = ""
    part_id: UUID | None = None


class BinOut(BaseModel):
    id: UUID
    name: str
    location: str
    part_id: UUID | None
    part_sku: str | None = None
    qr_token: str
    public_code: str | None = None
    kind: str = "finished_part"
    quantity_on_hand: int = 0
    quantity_reserved: int = 0
    quantity_available: int = 0


class SettingsOut(BaseModel):
    company_name: str
    woocommerce_url: str
    woocommerce_configured: bool
    shopify_shop: str = ""
    shopify_configured: bool = False
    shopify_api_version: str = "2024-10"
    notify_webhook_configured: bool
    simulated_time_scale: float
    filament_low_grams: float
    app_version: str = "dev"
    update_command: str = "./update.sh"
    auto_part_ejection: bool = False
    pack_bed_x_mm: float = 220.0
    pack_bed_y_mm: float = 220.0
    pack_gap_mm: float = 8.0
    auto_requeue_failed_qc: bool = True
    electricity_price_per_kwh: float = 0.32
    labour_rate_per_hour: float = 0.0
    enable_electricity_cost: bool = True
    enable_machine_cost: bool = True
    enable_labour_cost: bool = False
    enable_failure_cost: bool = True
    payment_fee_percent: float = 0.0
    overnight_start_hour: int = 22
    overnight_end_hour: int = 7
    backup_retention_days: int = 14
    backup_include_files: bool = False
    include_camera_in_notifications: bool = False


class SettingsIn(BaseModel):
    company_name: str | None = None
    woocommerce_url: str | None = None
    woocommerce_key: str | None = None
    woocommerce_secret: str | None = None
    shopify_shop: str | None = None
    shopify_access_token: str | None = None
    shopify_webhook_secret: str | None = None
    shopify_api_version: str | None = None
    notify_webhook_url: str | None = None
    auto_part_ejection: bool | None = None
    pack_bed_x_mm: float | None = Field(default=None, gt=0, le=2000)
    pack_bed_y_mm: float | None = Field(default=None, gt=0, le=2000)
    pack_gap_mm: float | None = Field(default=None, ge=0, le=100)
    auto_requeue_failed_qc: bool | None = None
    electricity_price_per_kwh: float | None = None
    labour_rate_per_hour: float | None = None
    enable_electricity_cost: bool | None = None
    enable_machine_cost: bool | None = None
    enable_labour_cost: bool | None = None
    enable_failure_cost: bool | None = None
    payment_fee_percent: float | None = None
    overnight_start_hour: int | None = None
    overnight_end_hour: int | None = None
    backup_retention_days: int | None = None
    backup_include_files: bool | None = None
    include_camera_in_notifications: bool | None = None
