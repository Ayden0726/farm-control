from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.models import (
    FinishedPartStock,
    GCodeFile,
    Printer,
    PrintJob,
    ProductionRun,
    ProductionRunItem,
)
from app.schemas import (
    GCodeOut,
    JobOut,
    PrinterOut,
    ProductionItemOut,
    ProductionRunOut,
)
from app.services.camera import camera_public


def hours_until_maintenance(printer: Printer) -> float | None:
    interval = printer.maintenance_interval_hours or 0
    if interval <= 0:
        return None
    hours = printer.total_print_seconds / 3600
    last = 0.0
    if printer.last_maintenance_at:
        # approximate hours at last service from remaining interval tracking
        last = 0.0
    remaining = interval - (hours - last)
    return round(remaining, 1)


def printer_out(printer: Printer) -> PrinterOut:
    spool_name = None
    spool_code = None
    spool_remaining = None
    if printer.assigned_spool is not None:
        spool_name = printer.assigned_spool.name
        spool_code = printer.assigned_spool.public_code
        spool_remaining = printer.assigned_spool.remaining_weight_g
    extra = dict(printer.extra_config or {})
    extra.pop("sim", None)
    extra.pop("camera_auth", None)
    extra.pop("camera_password", None)
    cam = camera_public(printer)
    return PrinterOut(
        id=printer.id,
        name=printer.name,
        model=printer.model,
        adapter_type=printer.adapter_type.value,
        base_url=printer.base_url,
        has_api_key=bool(printer.api_key_encrypted),
        extra_config=extra,
        is_enabled=printer.is_enabled,
        status=printer.status.value,
        nozzle_temp=printer.nozzle_temp,
        bed_temp=printer.bed_temp,
        target_nozzle=printer.target_nozzle,
        target_bed=printer.target_bed,
        current_file=printer.current_file,
        progress_percent=printer.progress_percent,
        time_remaining_seconds=printer.time_remaining_seconds,
        current_job_id=printer.current_job_id,
        assigned_spool_id=printer.assigned_spool_id,
        assigned_spool_name=spool_name,
        last_error=printer.last_error,
        last_seen_at=printer.last_seen_at,
        total_print_seconds=printer.total_print_seconds,
        total_jobs=printer.total_jobs,
        failed_jobs=printer.failed_jobs,
        last_maintenance_at=printer.last_maintenance_at,
        maintenance_interval_hours=printer.maintenance_interval_hours,
        maintenance_notes=printer.maintenance_notes,
        qr_token=printer.qr_token,
        hours_until_maintenance=hours_until_maintenance(printer),
        public_code=printer.public_code,
        assigned_spool_code=spool_code,
        assigned_spool_remaining_g=spool_remaining,
        build_x_mm=getattr(printer, "build_x_mm", None),
        build_y_mm=getattr(printer, "build_y_mm", None),
        build_z_mm=getattr(printer, "build_z_mm", None),
        nozzle_diameter_mm=getattr(printer, "nozzle_diameter_mm", None),
        nozzle_material=getattr(printer, "nozzle_material", "") or "",
        supported_materials=list(printer.supported_materials or []) if getattr(printer, "supported_materials", None) else [],
        max_nozzle_temp_c=getattr(printer, "max_nozzle_temp_c", None),
        max_bed_temp_c=getattr(printer, "max_bed_temp_c", None),
        build_plate_type=getattr(printer, "build_plate_type", "") or "",
        slicer_profile=getattr(printer, "slicer_profile", "") or "",
        unattended_mode=getattr(printer, "unattended_mode", None) or "allowed",
        avg_power_watts=getattr(printer, "avg_power_watts", None) or 180,
        machine_rate_per_hour=getattr(printer, "machine_rate_per_hour", None) or 0,
        current_downtime_reason=getattr(printer, "current_downtime_reason", None),
        camera_configured=cam["configured"],
        camera_status=cam["status"],
        camera_proxy_url=cam["proxy_url"] if cam["configured"] else None,
    )


def job_out(job: PrintJob) -> JobOut:
    return JobOut(
        id=job.id,
        production_run_id=job.production_run_id,
        production_run_name=job.production_run.name if job.production_run else None,
        gcode_file_id=job.gcode_file_id,
        gcode_filename=job.gcode_file.filename if job.gcode_file else None,
        part_id=job.part_id,
        part_sku=job.part.sku if job.part else None,
        assigned_printer_id=job.assigned_printer_id,
        assigned_printer_name=job.assigned_printer.name if job.assigned_printer else None,
        actual_printer_id=job.actual_printer_id,
        actual_printer_name=job.actual_printer.name if job.actual_printer else None,
        status=job.status.value,
        queue_position=job.queue_position,
        quantity_produced=job.quantity_produced,
        progress_percent=job.progress_percent,
        started_at=job.started_at,
        completed_at=job.completed_at,
        fail_reason=job.fail_reason,
        estimated_filament_grams=job.estimated_filament_grams,
        filament_used_grams=job.filament_used_grams,
        filament_cost=job.filament_cost,
        estimated_time_seconds=job.estimated_time_seconds,
        qr_token=job.qr_token,
        created_at=job.created_at,
        filament_override=bool(getattr(job, "filament_override", False)),
        hold_reason=getattr(job, "hold_reason", None),
        filament_required_g=getattr(job, "filament_required_g", 0) or 0,
        filament_available_g=getattr(job, "filament_available_g", 0) or 0,
        required_material=job.gcode_file.material if job.gcode_file else None,
        required_color=job.gcode_file.required_color if job.gcode_file else None,
        spool_code=(job.__dict__.get("spool").public_code if job.__dict__.get("spool") is not None else None),
        compatibility_override=bool(getattr(job, "compatibility_override", False)),
        incompatibility_reason=getattr(job, "incompatibility_reason", "") or "",
        batch_code=getattr(job, "batch_code", None),
    )


def item_out(item: ProductionRunItem) -> ProductionItemOut:
    return ProductionItemOut(
        id=item.id,
        part_id=item.part_id,
        part_sku=item.part.sku if item.part else "",
        part_name=item.part.name if item.part else "",
        gcode_file_id=item.gcode_file_id,
        gcode_filename=item.gcode_file.filename if item.gcode_file else None,
        required_qty=item.required_qty,
        printed_qty=item.printed_qty,
        passed_qc=item.passed_qc,
        failed_qc=item.failed_qc,
        remaining_qty=item.remaining_qty,
        remaining_to_print=item.remaining_to_print,
    )


def run_out(run: ProductionRun, jobs: list[PrintJob] | None = None) -> ProductionRunOut:
    jobs = jobs if jobs is not None else list(run.jobs or [])
    counts = {"queued": 0, "printing": 0, "completed": 0, "failed": 0}
    for job in jobs:
        if job.status.value in counts:
            counts[job.status.value] += 1
        elif job.status.value in {"held", "paused"}:
            counts["queued"] += 1
    return ProductionRunOut(
        id=run.id,
        name=run.name,
        status=run.status.value,
        notes=run.notes,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        printer_ids=[p.printer_id for p in run.printers],
        items=[item_out(i) for i in run.items],
        queued_jobs=counts["queued"],
        printing_jobs=counts["printing"],
        completed_jobs=counts["completed"],
        failed_jobs=counts["failed"],
        batch_code=getattr(run, "batch_code", None),
        needed_by=getattr(run, "needed_by", None),
    )


def gcode_out(gcode: GCodeFile) -> GCodeOut:
    return GCodeOut(
        id=gcode.id,
        filename=gcode.filename,
        part_id=gcode.part_id,
        part_sku=gcode.part.sku if gcode.part else None,
        quantity_per_file=gcode.quantity_per_file,
        material=gcode.material,
        estimated_time_seconds=gcode.estimated_time_seconds,
        estimated_filament_grams=gcode.estimated_filament_grams,
        version=gcode.version,
        is_archived=gcode.is_archived,
        notes=gcode.notes,
        file_size_bytes=gcode.file_size_bytes,
        compatible_printer_ids=[c.printer_id for c in gcode.compatible_printers],
        created_at=gcode.created_at,
        required_color=getattr(gcode, "required_color", "") or "",
        slicer=getattr(gcode, "slicer", "") or "",
        slicer_profile=getattr(gcode, "slicer_profile", "") or "",
        nozzle_mm=getattr(gcode, "nozzle_mm", None),
        layer_height_mm=getattr(gcode, "layer_height_mm", None),
        min_bed_x_mm=getattr(gcode, "min_bed_x_mm", None),
        min_bed_y_mm=getattr(gcode, "min_bed_y_mm", None),
        required_nozzle_mm=getattr(gcode, "required_nozzle_mm", None),
        unattended_approved=bool(getattr(gcode, "unattended_approved", True)),
        production_approved=bool(getattr(gcode, "production_approved", False)),
    )


def eta_iso(seconds: int) -> str | None:
    if seconds <= 0:
        return None
    from datetime import timedelta

    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
