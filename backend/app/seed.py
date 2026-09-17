from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import struct

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    BomItem,
    FinishedPartStock,
    GCodeFile,
    JobStatus,
    MaintenanceLog,
    Notification,
    NotificationType,
    Order,
    OrderLine,
    OrderPartNeed,
    OrderStatus,
    Part,
    PartBin,
    PrintJob,
    Printer,
    PrinterAdapterType,
    PrinterStatus,
    Product,
    ProductionRun,
    ProductionRunItem,
    ProductionRunPrinter,
    ProductionRunStatus,
    QcBatch,
    QcStatus,
    StlFile,
    utcnow,
)
from app.services.gcode_meta import (
    apply_filename_filament_fallback,
    apply_filename_time_fallback,
    parse_gcode_file_bytes,
)
from app.services.demo_mode import DEMO_MODE_KEY, mark_demo_if_present, upsert_app_setting
from app.services.inventory import get_or_create_stock
from app.util import new_qr_token, parse_quantity_from_filename


def _demo_stl_box(sx: float, sy: float, sz: float) -> bytes:
    verts = [
        (0, 0, 0),
        (sx, 0, 0),
        (sx, sy, 0),
        (0, sy, 0),
        (0, 0, sz),
        (sx, 0, sz),
        (sx, sy, sz),
        (0, sy, sz),
    ]
    faces = [
        (0, 1, 2),
        (0, 2, 3),
        (4, 6, 5),
        (4, 7, 6),
        (0, 4, 5),
        (0, 5, 1),
        (1, 5, 6),
        (1, 6, 2),
        (2, 6, 7),
        (2, 7, 3),
        (3, 7, 4),
        (3, 4, 0),
    ]
    buf = bytearray(80)
    buf += struct.pack("<I", 12)
    for i, j, k in faces:
        buf += struct.pack("<12fH", 0, 0, 1, *verts[i], *verts[j], *verts[k], 0)
    return bytes(buf)


def _gcode_content(name: str, seconds: int, grams: float) -> str:
    return f"""; Print FarmOS library file
;TIME:{seconds}
; filament used [g] = {grams}
; part={name}
G28
G1 X10 Y10 F3000
; demo body omitted
M84
"""


async def seed_demo(db: AsyncSession) -> None:
    existing = (await db.execute(select(Part).limit(1))).scalar_one_or_none()
    if existing:
        await mark_demo_if_present(db)
        return

    settings = get_settings()
    settings.gcode_dir.mkdir(parents=True, exist_ok=True)
    now = utcnow()

    parts_spec = [
        ("RK-FR5-BottomFrame", "Flex Rack 5 Bottom Frame", "Primary lower chassis for Flex Rack 5."),
        ("RK-FR5-TopFrame", "Flex Rack 5 Top Frame", "Upper chassis matching the bottom frame."),
        ("RK-FR5-Upright", "Flex Rack 5 Upright", "Vertical extrusion-style upright. Four required per rack."),
        ("RK-FR5-Handle", "Flex Rack 5 Handle", "Carry handle. Four required per rack."),
        ("RK-FR5-OptionalBrace", "Flex Rack 5 Optional Brace", "Optional stiffness brace."),
        ("RK-FR5-SideUtilityPanel", "Flex Rack 5 Side Utility Panel", "Side panel with accessory mounting."),
    ]
    parts: dict[str, Part] = {}
    for sku, name, desc in parts_spec:
        part = Part(sku=sku, name=name, description=desc)
        db.add(part)
        parts[sku] = part
    await db.flush()
    for part in parts.values():
        await get_or_create_stock(db, part.id)

    gcode_spec = [
        ("RK-FR5-BottomFrame.gcode", "RK-FR5-BottomFrame", 15000, 186, "PETG"),
        ("RK-FR5-TopFrame.gcode", "RK-FR5-TopFrame", 13800, 172, "PETG"),
        ("RK-FR5-Upright-x2.gcode", "RK-FR5-Upright", 9800, 94, "PETG"),
        ("RK-FR5-Handle-x4.gcode", "RK-FR5-Handle", 4200, 48, "PETG"),
        ("RK-FR5-OptionalBrace.gcode", "RK-FR5-OptionalBrace", 3600, 28, "PETG"),
        ("RK-FR5-SideUtilityPanel.gcode", "RK-FR5-SideUtilityPanel", 7200, 61, "PETG"),
    ]
    gcodes: dict[str, GCodeFile] = {}
    for filename, sku, seconds, grams, material in gcode_spec:
        path = settings.gcode_dir / filename
        path.write_text(_gcode_content(sku, seconds, grams))
        meta = parse_gcode_file_bytes(path.read_bytes())
        apply_filename_time_fallback(meta, filename)
        apply_filename_filament_fallback(meta, filename)
        gcode = GCodeFile(
            filename=filename,
            stored_path=str(path),
            part_id=parts[sku].id,
            quantity_per_file=parse_quantity_from_filename(filename),
            material=material,
            estimated_time_seconds=int(meta.get("estimated_time_seconds") or seconds),
            estimated_filament_grams=float(meta.get("estimated_filament_grams") or grams),
            required_color="Black" if material == "PETG" else "Grey",
            version=1,
            notes="Demo library file. Replace with production-sliced G-code when ready.",
            file_size_bytes=path.stat().st_size,
        )
        db.add(gcode)
        gcodes[sku] = gcode
    await db.flush()

    product = Product(
        sku="RK-FR5",
        name="RackKit Flex Rack 5",
        description="Complete Flex Rack 5. BOM is data-driven — add future products from the Products page.",
        woocommerce_product_id=None,
    )
    db.add(product)
    await db.flush()
    bom = [
        ("RK-FR5-BottomFrame", 1, False),
        ("RK-FR5-TopFrame", 1, False),
        ("RK-FR5-Upright", 4, False),
        ("RK-FR5-Handle", 4, False),
        ("RK-FR5-SideUtilityPanel", 2, False),
        ("RK-FR5-OptionalBrace", 1, True),
    ]
    for sku, qty, optional in bom:
        db.add(BomItem(product_id=product.id, part_id=parts[sku].id, quantity=qty, is_optional=optional))

    printers_spec = [
        ("Bay-01 CR-6 Max", "Creality CR-6 Max", PrinterAdapterType.simulated, PrinterStatus.printing, 250, 80),
        ("Bay-02 K1 Max", "Creality K1 Max", PrinterAdapterType.simulated, PrinterStatus.waiting_for_bed_clear, 200, 60),
        ("Bay-03 K2 Pro", "Creality K2 Pro", PrinterAdapterType.simulated, PrinterStatus.printing, 255, 80),
        ("Bay-04 Voron 2.4", "Voron 2.4 350", PrinterAdapterType.simulated, PrinterStatus.idle, 28, 24),
        ("Bay-05 CR-6 SE", "Creality CR-6 SE", PrinterAdapterType.simulated, PrinterStatus.idle, 26, 23),
    ]
    printers: list[Printer] = []
    for name, model, adapter, status, nozzle, bed in printers_spec:
        printer = Printer(
            name=name,
            model=model,
            adapter_type=adapter,
            base_url=None,
            is_enabled=True,
            status=status,
            nozzle_temp=nozzle,
            bed_temp=bed,
            target_nozzle=250 if status == PrinterStatus.printing else 0,
            target_bed=80 if status == PrinterStatus.printing else 0,
            total_print_seconds=int(timedelta(hours=42 + len(printers) * 11).total_seconds()),
            total_jobs=18 + len(printers) * 3,
            failed_jobs=1 if "K1" in name else 0,
            last_seen_at=now,
            last_maintenance_at=now - timedelta(days=12 + len(printers)),
            maintenance_interval_hours=200,
            maintenance_notes="Check belts, nozzle, and PEI sheet.",
            qr_token=new_qr_token(),
            extra_config={"sim": {"status": status.value}},
        )
        from app.services.printer_geometry import apply_printer_geometry_defaults

        apply_printer_geometry_defaults(printer)
        db.add(printer)
        printers.append(printer)
    await db.flush()

    from app.services.slicer_defaults import ensure_slicer_defaults
    from app.services.stl import bounding_box

    await ensure_slicer_defaults(db)
    settings.stl_dir.mkdir(parents=True, exist_ok=True)
    handle_stl = _demo_stl_box(48.0, 18.0, 8.0)
    handle_path = settings.stl_dir / "RK-FR5-Handle-v1.stl"
    handle_path.write_bytes(handle_stl)
    box = bounding_box(handle_stl)
    db.add(
        StlFile(
            filename="RK-FR5-Handle-v1.stl",
            stored_path=str(handle_path),
            part_id=parts["RK-FR5-Handle"].id,
            notes="Demo handle mesh (placeholder). Replace with the production STL before real slicing.",
            file_size_bytes=len(handle_stl),
            bbox_x_mm=box.x_mm if box else 48.0,
            bbox_y_mm=box.y_mm if box else 18.0,
            bbox_z_mm=box.z_mm if box else 8.0,
            triangle_count=box.triangle_count if box else 12,
            volume_mm3=box.volume_mm3 if box else 48.0 * 18.0 * 8.0,
            version=1,
            production_approved=True,
            recommended_spacing_mm=6.0,
        )
    )

    run = ProductionRun(
        name="Flex Rack 5 — Batch 001",
        status=ProductionRunStatus.in_progress,
        notes="Shop-floor batch covering current Flex Rack 5 orders.",
        started_at=now - timedelta(hours=6),
    )
    db.add(run)
    await db.flush()
    for printer in printers[:4]:
        db.add(ProductionRunPrinter(production_run_id=run.id, printer_id=printer.id))

    items_spec = [
        ("RK-FR5-BottomFrame", 8, 3, 2, 0),
        ("RK-FR5-TopFrame", 8, 2, 1, 0),
        ("RK-FR5-Upright", 32, 12, 8, 2),
        ("RK-FR5-Handle", 32, 16, 12, 0),
        ("RK-FR5-OptionalBrace", 4, 1, 1, 0),
        ("RK-FR5-SideUtilityPanel", 16, 6, 4, 0),
    ]
    items: dict[str, ProductionRunItem] = {}
    for sku, required, printed, passed, failed in items_spec:
        item = ProductionRunItem(
            production_run_id=run.id,
            part_id=parts[sku].id,
            gcode_file_id=gcodes[sku].id,
            required_qty=required,
            printed_qty=printed,
            passed_qc=passed,
            failed_qc=failed,
        )
        db.add(item)
        items[sku] = item
        stock = await get_or_create_stock(db, parts[sku].id)
        stock.quantity_on_hand += passed
    await db.flush()

    # Active print on Bay-01: Handle-x4, 67% complete
    handle_job = PrintJob(
        production_run_id=run.id,
        production_run_item_id=items["RK-FR5-Handle"].id,
        gcode_file_id=gcodes["RK-FR5-Handle"].id,
        part_id=parts["RK-FR5-Handle"].id,
        assigned_printer_id=printers[0].id,
        actual_printer_id=printers[0].id,
        status=JobStatus.printing,
        queue_position=1,
        quantity_produced=4,
        progress_percent=67,
        started_at=now - timedelta(seconds=4200 * 0.67 / get_settings().simulated_time_scale),
        estimated_filament_grams=48,
        estimated_time_seconds=4200,
        spool_id=None,
        qr_token=new_qr_token(),
    )
    db.add(handle_job)
    await db.flush()
    printers[0].current_job_id = handle_job.id
    printers[0].current_file = "RK-FR5-Handle-x4.gcode"
    printers[0].progress_percent = 67
    printers[0].time_remaining_seconds = int((4200 * 0.33) / get_settings().simulated_time_scale)
    printers[0].extra_config = {
        "sim": {
            "status": "printing",
            "current_file": "RK-FR5-Handle-x4.gcode",
            "progress_percent": 67,
            "time_remaining_seconds": printers[0].time_remaining_seconds,
            "target_nozzle": 250,
            "target_bed": 80,
        }
    }

    # Bay-03 printing bottom frame at 23%
    frame_job = PrintJob(
        production_run_id=run.id,
        production_run_item_id=items["RK-FR5-BottomFrame"].id,
        gcode_file_id=gcodes["RK-FR5-BottomFrame"].id,
        part_id=parts["RK-FR5-BottomFrame"].id,
        assigned_printer_id=printers[2].id,
        actual_printer_id=printers[2].id,
        status=JobStatus.printing,
        queue_position=2,
        quantity_produced=1,
        progress_percent=23,
        started_at=now - timedelta(seconds=15000 * 0.23 / get_settings().simulated_time_scale),
        estimated_filament_grams=186,
        estimated_time_seconds=15000,
        spool_id=None,
        qr_token=new_qr_token(),
    )
    db.add(frame_job)
    await db.flush()
    printers[2].current_job_id = frame_job.id
    printers[2].current_file = "RK-FR5-BottomFrame.gcode"
    printers[2].progress_percent = 23
    printers[2].time_remaining_seconds = int((15000 * 0.77) / get_settings().simulated_time_scale)
    printers[2].extra_config = {
        "sim": {
            "status": "printing",
            "current_file": "RK-FR5-BottomFrame.gcode",
            "progress_percent": 23,
            "time_remaining_seconds": printers[2].time_remaining_seconds,
            "target_nozzle": 255,
            "target_bed": 80,
        }
    }

    # Recently finished upright on K1 Max — waiting for bed clear + QC
    done_job = PrintJob(
        production_run_id=run.id,
        production_run_item_id=items["RK-FR5-Upright"].id,
        gcode_file_id=gcodes["RK-FR5-Upright"].id,
        part_id=parts["RK-FR5-Upright"].id,
        assigned_printer_id=printers[1].id,
        actual_printer_id=printers[1].id,
        status=JobStatus.completed,
        queue_position=0,
        quantity_produced=2,
        progress_percent=100,
        started_at=now - timedelta(hours=2),
        completed_at=now - timedelta(minutes=8),
        estimated_filament_grams=94,
        filament_used_grams=94,
        filament_cost=round((24 / 1000) * 94, 2),
        estimated_time_seconds=9800,
        spool_id=None,
        qr_token=new_qr_token(),
    )
    db.add(done_job)
    await db.flush()
    printers[1].current_file = "RK-FR5-Upright-x2.gcode"
    printers[1].progress_percent = 100
    printers[1].status = PrinterStatus.waiting_for_bed_clear
    printers[1].extra_config = {
        "sim": {"status": "waiting_for_bed_clear", "current_file": "RK-FR5-Upright-x2.gcode", "progress_percent": 100}
    }
    db.add(
        QcBatch(
            job_id=done_job.id,
            part_id=parts["RK-FR5-Upright"].id,
            production_run_item_id=items["RK-FR5-Upright"].id,
            quantity=2,
            status=QcStatus.awaiting_qc,
        )
    )

    failed_job = PrintJob(
        production_run_id=run.id,
        production_run_item_id=items["RK-FR5-TopFrame"].id,
        gcode_file_id=gcodes["RK-FR5-TopFrame"].id,
        part_id=parts["RK-FR5-TopFrame"].id,
        assigned_printer_id=printers[4].id,
        actual_printer_id=printers[4].id,
        status=JobStatus.failed,
        queue_position=0,
        quantity_produced=1,
        progress_percent=41,
        started_at=now - timedelta(hours=3),
        completed_at=now - timedelta(hours=1),
        fail_reason="Layer shift at 41% — belt skipped. Reprint queued.",
        estimated_filament_grams=172,
        estimated_time_seconds=13800,
        qr_token=new_qr_token(),
    )
    db.add(failed_job)

    # Queued remaining work
    queue_plan = [
        ("RK-FR5-Handle", 4, None),
        ("RK-FR5-Handle", 5, None),
        ("RK-FR5-Upright", 6, printers[3].id),
        ("RK-FR5-Upright", 7, None),
        ("RK-FR5-TopFrame", 8, None),
        ("RK-FR5-BottomFrame", 9, None),
        ("RK-FR5-SideUtilityPanel", 10, None),
        ("RK-FR5-SideUtilityPanel", 11, None),
        ("RK-FR5-OptionalBrace", 12, None),
    ]
    for sku, pos, assigned in queue_plan:
        db.add(
            PrintJob(
                production_run_id=run.id,
                production_run_item_id=items[sku].id,
                gcode_file_id=gcodes[sku].id,
                part_id=parts[sku].id,
                assigned_printer_id=assigned,
                status=JobStatus.queued,
                queue_position=pos,
                quantity_produced=gcodes[sku].quantity_per_file,
                estimated_filament_grams=gcodes[sku].estimated_filament_grams,
                estimated_time_seconds=gcodes[sku].estimated_time_seconds,
                qr_token=new_qr_token(),
            )
        )

    db.add(
        PartBin(
            name="FR5 Handles — QC passed",
            location="Shelf A3",
            part_id=parts["RK-FR5-Handle"].id,
            qr_token=new_qr_token(),
        )
    )
    db.add(
        PartBin(
            name="FR5 Uprights — awaiting QC",
            location="QC bench",
            part_id=parts["RK-FR5-Upright"].id,
            qr_token=new_qr_token(),
        )
    )

    ready_order = Order(
        reference="RK-1042",
        customer_name="Northline Studio",
        customer_email="ops@northline.example",
        notes="Ship with extra brace if QC surplus allows.",
        source="woocommerce",
        woocommerce_id=1042,
        status=OrderStatus.ready_to_ship,
        shipping_status="unfulfilled",
        packing_status="packed",
        shipping_address={
            "name": "Northline Studio",
            "business_name": "Northline Studio",
            "lines": ["48 Gertrude Street"],
            "suburb": "Fitzroy",
            "state": "VIC",
            "postcode": "3065",
            "phone": "0390001042",
            "email": "ops@northline.example",
            "country": "AU",
            "source": "woocommerce",
        },
    )
    db.add(ready_order)
    await db.flush()
    db.add(OrderLine(order_id=ready_order.id, product_id=product.id, quantity=1))
    for sku, qty in [("RK-FR5-BottomFrame", 1), ("RK-FR5-TopFrame", 1), ("RK-FR5-Upright", 4), ("RK-FR5-Handle", 4), ("RK-FR5-SideUtilityPanel", 2)]:
        reserved = min(qty, (await get_or_create_stock(db, parts[sku].id)).quantity_available)
        stock = await get_or_create_stock(db, parts[sku].id)
        stock.quantity_reserved += reserved
        db.add(
            OrderPartNeed(
                order_id=ready_order.id,
                part_id=parts[sku].id,
                required_qty=qty,
                reserved_qty=reserved,
                to_produce=max(0, qty - reserved),
            )
        )

    waiting_order = Order(
        reference="RK-1048",
        customer_name="Harbour Makerspace",
        customer_email="shop@harbour.example",
        notes="Imported from WooCommerce. Missing uprights and handles.",
        source="woocommerce",
        woocommerce_id=1048,
        status=OrderStatus.in_production,
        production_run_id=run.id,
        shipping_address={
            "name": "Harbour Makerspace",
            "business_name": "Harbour Makerspace",
            "lines": ["12 Darling Drive"],
            "suburb": "Sydney",
            "state": "NSW",
            "postcode": "2000",
            "phone": "0290001048",
            "email": "shop@harbour.example",
            "country": "AU",
            "source": "woocommerce",
        },
    )
    db.add(waiting_order)
    await db.flush()
    db.add(OrderLine(order_id=waiting_order.id, product_id=product.id, quantity=2))
    for sku, qty in [("RK-FR5-BottomFrame", 2), ("RK-FR5-TopFrame", 2), ("RK-FR5-Upright", 8), ("RK-FR5-Handle", 8), ("RK-FR5-SideUtilityPanel", 4)]:
        stock = await get_or_create_stock(db, parts[sku].id)
        reserved = min(2, stock.quantity_available)
        stock.quantity_reserved += reserved
        db.add(
            OrderPartNeed(
                order_id=waiting_order.id,
                part_id=parts[sku].id,
                required_qty=qty,
                reserved_qty=reserved,
                to_produce=max(0, qty - reserved),
            )
        )

    db.add(
        MaintenanceLog(
            printer_id=printers[0].id,
            performed_at=now - timedelta(days=12),
            hours_at_service=38,
            kind="service",
            notes="Replaced PEI sheet, tightened X belt, flushed nozzle.",
        )
    )
    from app.services.notifications import ensure_defaults, print_complete_copy

    complete_title, complete_body = print_complete_copy(
        printers[1].name,
        "RK-FR5-Upright-x2.gcode",
        run.name,
        2,
        9800,
        now - timedelta(minutes=8),
    )
    db.add(
        Notification(
            type=NotificationType.print_completed.value,
            title=complete_title,
            body=complete_body,
            severity="info",
            entity_type="job",
            entity_id=str(done_job.id),
            printer_id=printers[1].id,
            printer_name=printers[1].name,
            job_id=done_job.id,
            job_label="RK-FR5-Upright-x2.gcode",
            production_run_id=run.id,
            production_run_name=run.name,
            deep_link="/printers/" + str(printers[1].id),
            extra={"quantity": 2, "duration_seconds": 9800},
        )
    )
    db.add(
        Notification(
            type=NotificationType.bed_needs_clearing.value,
            title="Bay-02 K1 Max — Bed needs clearing",
            body="RK-FR5-Upright-x2.gcode is finished on Bay-02 K1 Max.\n\nStatus: Waiting for Bed Clear\nConfirm the bed is empty to release the next queued job.",
            severity="warning",
            entity_type="printer",
            entity_id=str(printers[1].id),
            printer_id=printers[1].id,
            printer_name=printers[1].name,
            job_label="RK-FR5-Upright-x2.gcode",
            production_run_name=run.name,
            deep_link="/printers/" + str(printers[1].id),
        )
    )
    db.add(
        Notification(
            type=NotificationType.print_failed.value,
            title="Bay-05 CR-6 SE — Print Failed",
            body="RK-FR5-TopFrame.gcode failed on Bay-05 CR-6 SE.\n\nReason: Layer shift at 41% — belt skipped. Reprint queued.",
            severity="error",
            entity_type="job",
            entity_id=str(failed_job.id),
            printer_id=printers[4].id,
            printer_name=printers[4].name,
            job_id=failed_job.id,
            job_label="RK-FR5-TopFrame.gcode",
            production_run_name=run.name,
            deep_link="/printers/" + str(printers[4].id),
        )
    )
    db.add(
        Notification(
            type=NotificationType.order_ready.value,
            title="Order RK-1042 ready for fulfilment",
            body="Northline Studio — parts reserved from finished inventory.",
            severity="info",
            entity_type="order",
            entity_id=str(ready_order.id),
            order_id=ready_order.id,
            order_reference=ready_order.reference,
            deep_link="/orders/" + str(ready_order.id),
        )
    )
    await ensure_defaults(db)
    from app.seed_filament import ensure_filament_system

    await ensure_filament_system(db)
    await upsert_app_setting(db, DEMO_MODE_KEY, True)
    await db.flush()
