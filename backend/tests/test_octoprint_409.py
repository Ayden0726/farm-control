import unittest

from app.adapters.octoprint import snapshot_from_octoprint
from app.services.printer_connect import _fixes_for


class OctoPrint409Tests(unittest.TestCase):
    def test_disconnected_printer_is_reachable_host(self) -> None:
        snap = snapshot_from_octoprint(409, {}, {})
        self.assertFalse(snap.online)
        self.assertEqual(snap.status, "offline")
        self.assertTrue(snap.extra.get("control_host_ok"))
        self.assertTrue(snap.extra.get("printer_disconnected"))

    def test_operational_printer(self) -> None:
        snap = snapshot_from_octoprint(
            200,
            {"state": {"text": "Operational", "flags": {"ready": True}}, "temperature": {}},
            {},
        )
        self.assertTrue(snap.online)
        self.assertEqual(snap.status, "idle")

    def test_409_help_text_is_not_about_certs(self) -> None:
        tips = " ".join(_fixes_for("octoprint", "http://192.168.1.185", "OctoPrint HTTP 409"))
        self.assertIn("not a certificate", tips.lower())
        self.assertIn("not connected", tips.lower())


if __name__ == "__main__":
    unittest.main()
