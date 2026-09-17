import unittest
from types import SimpleNamespace

from app.services.printer_templates import SNAPSHOT_KEYS, apply_snapshot, printer_snapshot


class PrinterTemplateTests(unittest.TestCase):
    def test_snapshot_includes_plate_and_nozzle(self) -> None:
        printer = SimpleNamespace(
            model="Creality K1 Max",
            adapter_type=SimpleNamespace(value="creality"),
            build_x_mm=300,
            build_y_mm=300,
            build_z_mm=250,
            usable_x_mm=290,
            usable_y_mm=290,
            usable_z_mm=250,
            nozzle_diameter_mm=0.4,
            nozzle_material="Brass",
            supported_materials=["PETG", "PLA"],
            max_nozzle_temp_c=300,
            max_bed_temp_c=100,
            build_plate_type="PEI",
            slicer_profile="",
            firmware="klipper",
            filament_diameter_mm=1.75,
            bed_shape="rectangular",
            bed_origin="corner",
            keepout_polygons=[],
            max_speed_mm_s=None,
            max_accel_mm_s2=None,
            max_volumetric_mm3_s=None,
            unattended_mode="allowed",
            avg_power_watts=180,
            machine_rate_per_hour=0,
            maintenance_interval_hours=200,
        )
        snap = printer_snapshot(printer)
        self.assertEqual(snap["adapter_type"], "creality")
        self.assertEqual(snap["usable_x_mm"], 290)
        self.assertEqual(snap["nozzle_diameter_mm"], 0.4)
        self.assertEqual(set(SNAPSHOT_KEYS), set(snap))

    def test_apply_only_fills_empty(self) -> None:
        printer = SimpleNamespace(build_x_mm=220, nozzle_diameter_mm=None, nozzle_material="", usable_x_mm=None)
        apply_snapshot(
            printer,
            {"build_x_mm": 300, "nozzle_diameter_mm": 0.6, "nozzle_material": "Hardened", "usable_x_mm": 290},
            only_empty=True,
        )
        self.assertEqual(printer.build_x_mm, 220)
        self.assertEqual(printer.nozzle_diameter_mm, 0.6)
        self.assertEqual(printer.nozzle_material, "Hardened")
        self.assertEqual(printer.usable_x_mm, 290)


if __name__ == "__main__":
    unittest.main()
