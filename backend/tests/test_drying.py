import unittest

from app.models import DryingStatus
from app.services.filament import parse_drying_status


class DryingStatusParseTests(unittest.TestCase):
    def test_defaults_unknown(self):
        self.assertEqual(parse_drying_status(None), DryingStatus.unknown)
        self.assertEqual(parse_drying_status(""), DryingStatus.unknown)

    def test_accepts_known_values(self):
        self.assertEqual(parse_drying_status("drying"), DryingStatus.drying)
        self.assertEqual(parse_drying_status("needs_drying"), DryingStatus.needs_drying)
        self.assertEqual(parse_drying_status(DryingStatus.dry), DryingStatus.dry)

    def test_rejects_unknown_values(self):
        with self.assertRaises(ValueError):
            parse_drying_status("soaking")


if __name__ == "__main__":
    unittest.main()
