import unittest

from app.util import parse_quantity_from_filename


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

    def test_uses_last_x_count(self):
        self.assertEqual(parse_quantity_from_filename("Kit-x2-final-x10.gcode"), 10)


if __name__ == "__main__":
    unittest.main()
