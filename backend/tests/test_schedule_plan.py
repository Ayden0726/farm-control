import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.models import PrinterStatus
from app.services.schedule_plan import (
    auto_select_printers,
    calendar_month_span,
    due_priority_key,
    insert_queue_positions,
    needed_by_iso,
    needed_by_utc,
    printer_is_idle_capable,
    should_yield_to_new,
)


def _printer(**kwargs):
    defaults = dict(
        id=uuid4(),
        name="P1",
        is_enabled=True,
        status=PrinterStatus.idle,
        nozzle_diameter_mm=0.4,
        supported_materials=["PETG"],
        build_x_mm=220,
        build_y_mm=220,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _gcode(**kwargs):
    defaults = dict(
        id=uuid4(),
        filename="part.gcode",
        required_nozzle_mm=0.4,
        nozzle_mm=0.4,
        material="PETG",
        min_bed_x_mm=None,
        min_bed_y_mm=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class NeededByTests(unittest.TestCase):
    def test_utc_midnight_from_iso_date(self):
        dt = needed_by_utc("2026-09-20")
        self.assertEqual(dt, datetime(2026, 9, 20, tzinfo=timezone.utc))
        self.assertEqual(needed_by_iso(dt), "2026-09-20")

    def test_none_and_blank_stay_none(self):
        self.assertIsNone(needed_by_utc(None))
        self.assertIsNone(needed_by_utc("  "))
        self.assertIsNone(needed_by_iso(None))

    def test_date_object(self):
        self.assertEqual(needed_by_utc(date(2026, 1, 5)).isoformat(), "2026-01-05T00:00:00+00:00")

    def test_datetime_uses_calendar_date_not_time(self):
        src = datetime(2026, 9, 20, 18, 30, tzinfo=timezone.utc)
        self.assertEqual(needed_by_utc(src), datetime(2026, 9, 20, tzinfo=timezone.utc))


class QueuePriorityTests(unittest.TestCase):
    def test_earlier_due_date_sorts_first(self):
        early = needed_by_utc("2026-09-10")
        late = needed_by_utc("2026-09-20")
        ranked = sorted(
            [
                ("undated", *due_priority_key(None, 1)),
                ("late", *due_priority_key(late, 2)),
                ("early", *due_priority_key(early, 9)),
            ],
            key=lambda row: row[1:],
        )
        self.assertEqual([row[0] for row in ranked], ["early", "late", "undated"])

    def test_undated_yields_to_dated_work(self):
        due = needed_by_utc("2026-09-12")
        self.assertTrue(should_yield_to_new(None, due))
        self.assertFalse(should_yield_to_new(due, None))
        self.assertTrue(should_yield_to_new(needed_by_utc("2026-09-20"), due))
        self.assertFalse(should_yield_to_new(needed_by_utc("2026-09-10"), due))

    def test_insert_shifts_later_and_undated_only(self):
        existing = [
            (1, needed_by_utc("2026-09-10")),
            (2, needed_by_utc("2026-09-20")),
            (3, None),
        ]
        insert_at, shifts = insert_queue_positions(existing, needed_by_utc("2026-09-12"), 2)
        self.assertEqual(insert_at, 2)
        self.assertEqual(shifts, {2: 4, 3: 5})

    def test_null_needed_by_appends(self):
        existing = [(1, needed_by_utc("2026-09-10")), (2, None)]
        insert_at, shifts = insert_queue_positions(existing, None, 1)
        self.assertEqual(insert_at, 3)
        self.assertEqual(shifts, {})

    def test_empty_queue_starts_at_one(self):
        insert_at, shifts = insert_queue_positions([], needed_by_utc("2026-09-12"), 1)
        self.assertEqual(insert_at, 1)
        self.assertEqual(shifts, {})


class AutoPrinterTests(unittest.TestCase):
    def test_empty_fields_are_compatible(self):
        printer = _printer(nozzle_diameter_mm=None, supported_materials=[], build_x_mm=None)
        gcode = _gcode(required_nozzle_mm=None, nozzle_mm=None, material="")
        rows = auto_select_printers([printer], [gcode], {})
        self.assertTrue(rows[0]["selected"])
        self.assertEqual(rows[0]["compatible_file_count"], 1)

    def test_material_mismatch_not_auto_selected(self):
        printer = _printer(supported_materials=["PLA"])
        gcode = _gcode(material="PETG")
        rows = auto_select_printers([printer], [gcode], {})
        self.assertFalse(rows[0]["selected"])
        self.assertEqual(rows[0]["compatible_file_count"], 0)
        self.assertTrue(rows[0]["issues"])

    def test_disabled_and_error_printers_listed_but_not_selected(self):
        ok = _printer(name="Idle")
        down = _printer(name="Down", status=PrinterStatus.error)
        off = _printer(name="Off", is_enabled=False)
        gcode = _gcode()
        rows = {row["name"]: row for row in auto_select_printers([ok, down, off], [gcode], {})}
        self.assertTrue(rows["Idle"]["selected"])
        self.assertFalse(rows["Down"]["selected"])
        self.assertFalse(rows["Off"]["selected"])

    def test_union_selects_printer_compatible_with_any_file(self):
        petg = _printer(name="PETG", supported_materials=["PETG"])
        pla = _printer(name="PLA", supported_materials=["PLA"])
        files = [_gcode(material="PETG"), _gcode(material="PLA", filename="pla.gcode")]
        rows = {row["name"]: row for row in auto_select_printers([petg, pla], files, {})}
        self.assertTrue(rows["PETG"]["selected"])
        self.assertTrue(rows["PLA"]["selected"])
        self.assertEqual(rows["PETG"]["compatible_file_count"], 1)

    def test_allowlist_restricts_when_present(self):
        a = _printer(name="A")
        b = _printer(name="B")
        gcode = _gcode()
        rows = {row["name"]: row for row in auto_select_printers([a, b], [gcode], {gcode.id: {a.id}})}
        self.assertTrue(rows["A"]["selected"])
        self.assertFalse(rows["B"]["selected"])

    def test_empty_allowlist_is_compatible(self):
        printer = _printer()
        gcode = _gcode()
        rows = auto_select_printers([printer], [gcode], {})
        self.assertTrue(rows[0]["selected"])

    def test_no_files_selects_nobody(self):
        rows = auto_select_printers([_printer()], [], {})
        self.assertFalse(rows[0]["selected"])

    def test_idle_capable_excludes_error_only(self):
        self.assertTrue(printer_is_idle_capable(_printer(status=PrinterStatus.printing)))
        self.assertTrue(printer_is_idle_capable(_printer(status=PrinterStatus.waiting_for_bed_clear)))
        self.assertFalse(printer_is_idle_capable(_printer(status=PrinterStatus.error)))
        self.assertFalse(printer_is_idle_capable(_printer(is_enabled=False)))


class CalendarSpanTests(unittest.TestCase):
    def test_september_2026_pads_to_sundays(self):
        start, end = calendar_month_span(2026, 9)
        self.assertEqual(start.isoformat(), "2026-08-30")
        self.assertEqual(end.isoformat(), "2026-10-03")


if __name__ == "__main__":
    unittest.main()
