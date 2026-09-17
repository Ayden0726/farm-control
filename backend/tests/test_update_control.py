import unittest

from app.services.update_control import parse_heartbeat


class HeartbeatTests(unittest.TestCase):
    def test_ascii(self) -> None:
        self.assertEqual(parse_heartbeat(b"1789610000\n"), 1789610000)

    def test_utf16_le_bom(self) -> None:
        encoded = "1789610000\r\n".encode("utf-16")
        self.assertEqual(parse_heartbeat(encoded), 1789610000)

    def test_utf8_bom(self) -> None:
        self.assertEqual(parse_heartbeat(b"\xef\xbb\xbf1789610000"), 1789610000)

    def test_garbage(self) -> None:
        self.assertIsNone(parse_heartbeat(b""))
        self.assertIsNone(parse_heartbeat(b"not-a-time"))


if __name__ == "__main__":
    unittest.main()
