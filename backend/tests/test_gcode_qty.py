import unittest

from app.util import (
    parse_filament_grams_from_filename,
    parse_quantity_from_filename,
    parse_time_from_filename,
)


class FilenameQuantityTests(unittest.TestCase):
    def test_suffix_dash(self):
        self.assertEqual(parse_quantity_from_filename("RK-FR5-Handle-x4.gcode"), 4)

    def test_suffix_underscore(self):
        self.assertEqual(parse_quantity_from_filename("Handle_x8.gcode"), 8)

    def test_middle_of_name(self):
        self.assertEqual(parse_quantity_from_filename("Bracket-x4-PETG.gcode"), 4)

    def test_prefix(self):
        self.assertEqual(parse_quantity_from_filename("x12-plate.gcode"), 12)

    def test_space(self):
        self.assertEqual(parse_quantity_from_filename("Side panel x6.gcode"), 6)

    def test_uppercase(self):
        self.assertEqual(parse_quantity_from_filename("Clip-X3.gcode"), 3)

    def test_no_marker(self):
        self.assertEqual(parse_quantity_from_filename("RK-FR5-Handle.gcode"), 1)

    def test_does_not_match_max2(self):
        self.assertEqual(parse_quantity_from_filename("K1Max2.gcode"), 1)

    def test_does_not_match_nozzle_0_4(self):
        self.assertEqual(parse_quantity_from_filename("Handle-0.4mm.gcode"), 1)
        self.assertEqual(parse_quantity_from_filename("Handle-0.4.gcode"), 1)
        self.assertEqual(parse_quantity_from_filename("Handle-0.4pcs.gcode"), 1)

    def test_uses_last_x_count(self):
        self.assertEqual(parse_quantity_from_filename("Kit-x2-final-x10.gcode"), 10)

    def test_pcs_compact(self):
        self.assertEqual(parse_quantity_from_filename("Handle-4pcs.gcode"), 4)

    def test_pcs_space(self):
        self.assertEqual(parse_quantity_from_filename("Handle-4 pcs.gcode"), 4)
        self.assertEqual(parse_quantity_from_filename("Side panel 6 pcs.gcode"), 6)

    def test_pcs_uppercase(self):
        self.assertEqual(parse_quantity_from_filename("Handle-4PCS.gcode"), 4)

    def test_pcs_dash_separator(self):
        self.assertEqual(parse_quantity_from_filename("Bracket-8-pcs.gcode"), 8)

    def test_pcs_underscore_separator(self):
        self.assertEqual(parse_quantity_from_filename("Handle-4_pcs.gcode"), 4)

    def test_pcs_parentheses(self):
        self.assertEqual(parse_quantity_from_filename("Handle-(4pcs).gcode"), 4)
        self.assertEqual(parse_quantity_from_filename("Handle_(4pcs)_PETG.gcode"), 4)

    def test_pcs_piece_words(self):
        self.assertEqual(parse_quantity_from_filename("Handle-4pieces.gcode"), 4)
        self.assertEqual(parse_quantity_from_filename("Handle-4piece.gcode"), 4)
        self.assertEqual(parse_quantity_from_filename("Handle-4pc.gcode"), 4)

    def test_pcs_prefix(self):
        self.assertEqual(parse_quantity_from_filename("4pcs-plate.gcode"), 4)

    def test_uses_last_pcs_count(self):
        self.assertEqual(parse_quantity_from_filename("Kit-2pcs-final-10pcs.gcode"), 10)

    def test_pcs_preferred_over_x(self):
        self.assertEqual(parse_quantity_from_filename("Handle-4pcs-x8.gcode"), 4)
        self.assertEqual(parse_quantity_from_filename("Handle-x8-4pcs.gcode"), 4)
        self.assertEqual(parse_quantity_from_filename("RK-FR5-Handle-x4-8pcs.gcode"), 8)

    def test_combined_pcs_time_grams(self):
        name = "RK-FR5-Handle-4pcs-2h15m-48g.gcode"
        self.assertEqual(parse_quantity_from_filename(name), 4)
        self.assertEqual(parse_time_from_filename(name), 2 * 3600 + 15 * 60)
        self.assertEqual(parse_filament_grams_from_filename(name), 48)

    def test_ignores_unbounded_pcs(self):
        self.assertEqual(parse_quantity_from_filename("Handle4pcs.gcode"), 1)

    def test_caps_at_999(self):
        self.assertEqual(parse_quantity_from_filename("Handle-1000pcs.gcode"), 999)
        self.assertEqual(parse_quantity_from_filename("Handle-x1000.gcode"), 999)


if __name__ == "__main__":
    unittest.main()
