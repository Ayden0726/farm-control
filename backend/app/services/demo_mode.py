"""Turn off first-run demo mode: drop sample farm data and request a stack restart."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AppSetting,
    AssemblyKit,
    AssemblyKitLine,
    BinMovement,
    BomHardwareItem,
    BomItem,
    FinishedPartStock,
    FilamentSpool,
    FilamentTransaction,
    GCodeFile,
    GCodePrinterCompat,
    MaintenanceLog,
    MaintenanceRule,
    MaintenanceTask,
    Notification,
    NotificationDelivery,
    Order,
    OrderLine,
    OrderPartNeed,
    PackingCheck,
    Part,
    PartBin,
    PartCostSnapshot,
    PlateLayout,
    PrintJob,
    Printer,
    PrinterAdapterType,
    PrinterDowntime,
    PrinterNotificationPreference,
    Product,
    ProductionPlan,
    ProductionPlanLine,
    ProductionRun,
    ProductionRunItem,
    ProductionRunPrinter,
    QcBatch,
    Shipment,
    SliceJob,
    SlicerDurationStat,
    StockMovement,
    StorageLocation,
    StlFile,
)
from app.services.update_control import farm_root, write_restart_request

logger = logging.getLogger("farmos.demo")

DEMO_MODE_KEY = "demo_mode"
DEMO_SKU_PREFIX = "RK-FR5"
DEMO_PRODUCT_SKU = "RK-FR5"
DEMO_ORDER_REFS = ("RK-1042", "RK-1048")
DEMO_RUN_NAME_MATCH = "%Flex Rack 5%"


def is_demo_part_sku(sku: str | None) -> bool:
    return bool(sku) and sku.upper().startswith(DEMO_SKU_PREFIX)


def is_demo_product_sku(sku: str | None) -> bool:
    return (sku or "").upper() == DEMO_PRODUCT_SKU


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


async def upsert_app_setting(db: AsyncSession, key: str, value: object) -> None:
    row = await db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


async def _id_list(db: AsyncSession, stmt) -> list:
    return [row[0] for row in (await db.execute(stmt)).all() if row[0] is not None]


async def infer_demo_farm(db: AsyncSession) -> bool:
    product = (
        await db.execute(select(Product.id).where(Product.sku == DEMO_PRODUCT_SKU).limit(1))
    ).first()
    sim = (
        await db.execute(
            select(Printer.id)
            .where(Printer.adapter_type == PrinterAdapterType.simulated)
            .limit(1)
        )
    ).first()
    return product is not None and sim is not None


async def demo_mode_enabled(db: AsyncSession) -> bool:
    row = await db.get(AppSetting, DEMO_MODE_KEY)
    if row is not None:
        return _truthy(row.value)
    return await infer_demo_farm(db)


async def mark_demo_if_present(db: AsyncSession) -> None:
    if await infer_demo_farm(db):
        await upsert_app_setting(db, DEMO_MODE_KEY, True)


def _unlink_demo_file(stored_path: str | None, filename: str | None) -> None:
    if not stored_path:
        return
    name = Path(stored_path).name
    if not is_demo_part_sku(filename or name):
        return
    path = Path(stored_path)
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        logger.warning("could not delete demo file %s", path)


async def disable_demo_farm(db: AsyncSession) -> dict[str, int]:
    """Remove seeded Flex Rack 5 farm data and simulated printers. Keep the admin user."""
    part_ids = await _id_list(db, select(Part.id).where(Part.sku.startswith(DEMO_SKU_PREFIX)))
    product_ids = await _id_list(db, select(Product.id).where(Product.sku == DEMO_PRODUCT_SKU))
    printer_ids = await _id_list(
        db, select(Printer.id).where(Printer.adapter_type == PrinterAdapterType.simulated)
    )

    gcode_filters = []
    if part_ids:
        gcode_filters.append(GCodeFile.part_id.in_(part_ids))
    gcode_filters.append(GCodeFile.filename.startswith(DEMO_SKU_PREFIX))
    gcode_ids = await _id_list(db, select(GCodeFile.id).where(or_(*gcode_filters)))

    stl_filters = []
    if part_ids:
        stl_filters.append(StlFile.part_id.in_(part_ids))
    stl_filters.append(StlFile.filename.startswith(DEMO_SKU_PREFIX))
    stl_ids = await _id_list(db, select(StlFile.id).where(or_(*stl_filters)))

    run_ids: set = set(await _id_list(db, select(ProductionRun.id).where(ProductionRun.name.ilike(DEMO_RUN_NAME_MATCH))))
    if part_ids:
        run_ids.update(
            await _id_list(
                db,
                select(ProductionRunItem.production_run_id).where(ProductionRunItem.part_id.in_(part_ids)),
            )
        )
    if printer_ids:
        run_ids.update(
            await _id_list(
                db,
                select(ProductionRunPrinter.production_run_id).where(
                    ProductionRunPrinter.printer_id.in_(printer_ids)
                ),
            )
        )
    run_id_list = list(run_ids)

    job_filters = []
    if part_ids:
        job_filters.append(PrintJob.part_id.in_(part_ids))
    if printer_ids:
        job_filters.append(PrintJob.assigned_printer_id.in_(printer_ids))
        job_filters.append(PrintJob.actual_printer_id.in_(printer_ids))
    if run_id_list:
        job_filters.append(PrintJob.production_run_id.in_(run_id_list))
    if gcode_ids:
        job_filters.append(PrintJob.gcode_file_id.in_(gcode_ids))
    job_ids = await _id_list(db, select(PrintJob.id).where(or_(*job_filters))) if job_filters else []

    order_ids = set(await _id_list(db, select(Order.id).where(Order.reference.in_(DEMO_ORDER_REFS))))
    if run_id_list:
        order_ids.update(
            await _id_list(db, select(Order.id).where(Order.production_run_id.in_(run_id_list)))
        )
    if product_ids:
        order_ids.update(
            await _id_list(db, select(OrderLine.order_id).where(OrderLine.product_id.in_(product_ids)))
        )
    order_id_list = list(order_ids)

    printer_location_ids: list = []
    if printer_ids:
        printer_location_ids = await _id_list(
            db, select(StorageLocation.id).where(StorageLocation.printer_id.in_(printer_ids))
        )
        await db.execute(update(Printer).where(Printer.id.in_(printer_ids)).values(current_job_id=None, assigned_spool_id=None))
        await db.execute(
            update(FilamentSpool)
            .where(FilamentSpool.assigned_printer_id.in_(printer_ids))
            .values(assigned_printer_id=None)
        )
        await db.execute(
            update(StorageLocation)
            .where(StorageLocation.printer_id.in_(printer_ids))
            .values(printer_id=None)
        )
        await db.execute(
            update(GCodeFile)
            .where(GCodeFile.sliced_printer_id.in_(printer_ids))
            .values(sliced_printer_id=None)
        )

    if job_ids:
        await db.execute(update(PrintJob).where(PrintJob.id.in_(job_ids)).values(spool_id=None, slice_job_id=None))

    async def _delete(model, column, ids: Iterable) -> int:
        id_list = list(ids)
        if not id_list:
            return 0
        result = await db.execute(delete(model).where(column.in_(id_list)))
        return int(result.rowcount or 0)

    note_filters = []
    if printer_ids:
        note_filters.append(Notification.printer_id.in_(printer_ids))
    if job_ids:
        note_filters.append(Notification.job_id.in_(job_ids))
    if order_id_list:
        note_filters.append(Notification.order_id.in_(order_id_list))
    if run_id_list:
        note_filters.append(Notification.production_run_id.in_(run_id_list))
    note_ids = await _id_list(db, select(Notification.id).where(or_(*note_filters))) if note_filters else []
    await _delete(NotificationDelivery, NotificationDelivery.notification_id, note_ids)
    await _delete(Notification, Notification.id, note_ids)

    await _delete(QcBatch, QcBatch.job_id, job_ids)
    await _delete(QcBatch, QcBatch.part_id, part_ids)

    tx_filters = []
    if job_ids:
        tx_filters.append(FilamentTransaction.job_id.in_(job_ids))
    if printer_ids:
        tx_filters.append(FilamentTransaction.printer_id.in_(printer_ids))
    if run_id_list:
        tx_filters.append(FilamentTransaction.production_run_id.in_(run_id_list))
    if tx_filters:
        await db.execute(delete(FilamentTransaction).where(or_(*tx_filters)))

    kit_ids: list = []
    if product_ids:
        kit_ids.extend(await _id_list(db, select(AssemblyKit.id).where(AssemblyKit.product_id.in_(product_ids))))
    if order_id_list:
        kit_ids.extend(await _id_list(db, select(AssemblyKit.id).where(AssemblyKit.order_id.in_(order_id_list))))
    kit_ids = list(dict.fromkeys(kit_ids))
    await _delete(AssemblyKitLine, AssemblyKitLine.kit_id, kit_ids)
    if part_ids:
        await db.execute(delete(AssemblyKitLine).where(AssemblyKitLine.part_id.in_(part_ids)))
    await _delete(AssemblyKit, AssemblyKit.id, kit_ids)

    await _delete(PackingCheck, PackingCheck.order_id, order_id_list)
    await _delete(Shipment, Shipment.order_id, order_id_list)
    await _delete(OrderLine, OrderLine.order_id, order_id_list)
    await _delete(OrderPartNeed, OrderPartNeed.order_id, order_id_list)
    if part_ids:
        await db.execute(delete(OrderPartNeed).where(OrderPartNeed.part_id.in_(part_ids)))
    await _delete(Order, Order.id, order_id_list)

    slice_filters = []
    if stl_ids:
        slice_filters.append(SliceJob.stl_file_id.in_(stl_ids))
    if printer_ids:
        slice_filters.append(SliceJob.printer_id.in_(printer_ids))
    if part_ids:
        slice_filters.append(SliceJob.part_id.in_(part_ids))
    if run_id_list:
        slice_filters.append(SliceJob.production_run_id.in_(run_id_list))
    if order_id_list:
        slice_filters.append(SliceJob.order_id.in_(order_id_list))
    if gcode_ids:
        slice_filters.append(SliceJob.gcode_file_id.in_(gcode_ids))
    slice_ids = await _id_list(db, select(SliceJob.id).where(or_(*slice_filters))) if slice_filters else []
    if job_ids:
        await db.execute(update(PrintJob).where(PrintJob.id.in_(job_ids)).values(slice_job_id=None))
    await _delete(SliceJob, SliceJob.id, slice_ids)

    plan_ids: set = set()
    if run_id_list:
        plan_ids.update(
            await _id_list(db, select(ProductionPlan.id).where(ProductionPlan.production_run_id.in_(run_id_list)))
        )
    if part_ids:
        plan_ids.update(
            await _id_list(db, select(ProductionPlanLine.plan_id).where(ProductionPlanLine.part_id.in_(part_ids)))
        )
    if printer_ids:
        plan_ids.update(
            await _id_list(
                db, select(ProductionPlanLine.plan_id).where(ProductionPlanLine.printer_id.in_(printer_ids))
            )
        )
    if gcode_ids:
        plan_ids.update(
            await _id_list(
                db, select(ProductionPlanLine.plan_id).where(ProductionPlanLine.gcode_file_id.in_(gcode_ids))
            )
        )
    await _delete(ProductionPlanLine, ProductionPlanLine.plan_id, plan_ids)
    await _delete(ProductionPlan, ProductionPlan.id, plan_ids)

    await _delete(PrintJob, PrintJob.id, job_ids)
    await _delete(ProductionRunPrinter, ProductionRunPrinter.production_run_id, run_id_list)
    await _delete(ProductionRunItem, ProductionRunItem.production_run_id, run_id_list)
    if printer_ids:
        await db.execute(delete(ProductionRunPrinter).where(ProductionRunPrinter.printer_id.in_(printer_ids)))
    if part_ids:
        await db.execute(delete(ProductionRunItem).where(ProductionRunItem.part_id.in_(part_ids)))

    plate_filters = []
    if part_ids:
        plate_filters.append(PlateLayout.part_id.in_(part_ids))
    if stl_ids:
        plate_filters.append(PlateLayout.stl_file_id.in_(stl_ids))
    if printer_ids:
        plate_filters.append(PlateLayout.printer_id.in_(printer_ids))
    if plate_filters:
        await db.execute(delete(PlateLayout).where(or_(*plate_filters)))

    await _delete(SlicerDurationStat, SlicerDurationStat.printer_id, printer_ids)
    await _delete(PartCostSnapshot, PartCostSnapshot.part_id, part_ids)
    await _delete(PartCostSnapshot, PartCostSnapshot.gcode_file_id, gcode_ids)
    await _delete(StockMovement, StockMovement.part_id, part_ids)
    await _delete(FinishedPartStock, FinishedPartStock.part_id, part_ids)

    bin_ids = []
    if part_ids:
        bin_ids = await _id_list(db, select(PartBin.id).where(PartBin.part_id.in_(part_ids)))
    await _delete(BinMovement, BinMovement.bin_id, bin_ids)
    if part_ids:
        await db.execute(delete(BinMovement).where(BinMovement.part_id.in_(part_ids)))
    await _delete(PartBin, PartBin.id, bin_ids)

    await _delete(BomItem, BomItem.product_id, product_ids)
    await _delete(BomHardwareItem, BomHardwareItem.product_id, product_ids)
    if part_ids:
        await db.execute(delete(BomItem).where(BomItem.part_id.in_(part_ids)))

    await _delete(GCodePrinterCompat, GCodePrinterCompat.gcode_id, gcode_ids)
    await _delete(GCodePrinterCompat, GCodePrinterCompat.printer_id, printer_ids)

    if gcode_ids:
        for row in (
            await db.execute(select(GCodeFile.stored_path, GCodeFile.filename).where(GCodeFile.id.in_(gcode_ids)))
        ).all():
            _unlink_demo_file(row[0], row[1])
    if stl_ids:
        await db.execute(update(GCodeFile).where(GCodeFile.stl_file_id.in_(stl_ids)).values(stl_file_id=None))
        for row in (
            await db.execute(select(StlFile.stored_path, StlFile.filename).where(StlFile.id.in_(stl_ids)))
        ).all():
            _unlink_demo_file(row[0], row[1])

    await _delete(GCodeFile, GCodeFile.id, gcode_ids)
    await _delete(StlFile, StlFile.id, stl_ids)

    await _delete(MaintenanceTask, MaintenanceTask.printer_id, printer_ids)
    await _delete(MaintenanceLog, MaintenanceLog.printer_id, printer_ids)
    await _delete(PrinterDowntime, PrinterDowntime.printer_id, printer_ids)
    await _delete(PrinterNotificationPreference, PrinterNotificationPreference.printer_id, printer_ids)
    await _delete(MaintenanceRule, MaintenanceRule.printer_id, printer_ids)

    if printer_location_ids:
        await db.execute(
            update(FilamentSpool)
            .where(FilamentSpool.location_id.in_(printer_location_ids))
            .values(location_id=None)
        )
        await db.execute(delete(StorageLocation).where(StorageLocation.id.in_(printer_location_ids)))

    await _delete(ProductionRun, ProductionRun.id, run_id_list)
    await _delete(Printer, Printer.id, printer_ids)
    await _delete(Product, Product.id, product_ids)
    await _delete(Part, Part.id, part_ids)

    from app.seed_filament import clear_seeded_filament_inventory

    await clear_seeded_filament_inventory(db)
    await upsert_app_setting(db, DEMO_MODE_KEY, False)
    await db.flush()
    return {
        "parts": len(part_ids),
        "printers": len(printer_ids),
        "jobs": len(job_ids),
        "orders": len(order_id_list),
        "runs": len(run_id_list),
    }


def request_demo_off_restart() -> Path:
    root = farm_root()
    if root is not None:
        from app.services.update_control import apply_dotenv_updates

        apply_dotenv_updates(root / ".env", {"SIMULATED_TIME_SCALE": "1"})
        try:
            from app.config import get_settings

            get_settings.cache_clear()
        except Exception:
            pass
    return write_restart_request(reason="demo_mode_off", env={"SIMULATED_TIME_SCALE": "1"})
