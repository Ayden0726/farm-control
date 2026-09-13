import unittest

from app.services.public_host import normalize_public_host
from app.services.qr import qr_payload


class PublicHostNormalizeTests(unittest.TestCase):
    def test_blank_means_no_public_host(self):
        for raw in ("", "   ", None):
            result = normalize_public_host(raw)
            self.assertTrue(result.ok)
            self.assertEqual(result.host, "")
            self.assertEqual(result.origin, "")

    def test_apex_gets_farm_prefix(self):
        result = normalize_public_host("example.com")
        self.assertTrue(result.ok)
        self.assertEqual(result.host, "farm.example.com")
        self.assertEqual(result.origin, "https://farm.example.com")

    def test_country_tld(self):
        result = normalize_public_host("myprintshop.au")
        self.assertEqual(result.origin, "https://farm.myprintshop.au")

    def test_already_farm_prefixed(self):
        result = normalize_public_host("farm.example.com")
        self.assertEqual(result.origin, "https://farm.example.com")
        self.assertNotIn("farm.farm.", result.origin)

    def test_full_url_not_double_prefixed(self):
        result = normalize_public_host("https://farm.example.com/path")
        self.assertEqual(result.host, "farm.example.com")
        self.assertEqual(result.origin, "https://farm.example.com")

    def test_www_is_root_site(self):
        result = normalize_public_host("www.example.com")
        self.assertEqual(result.origin, "https://farm.example.com")

    def test_www_farm_already_explicit(self):
        result = normalize_public_host("www.farm.example.com")
        self.assertEqual(result.origin, "https://farm.example.com")
        self.assertNotIn("farm.farm.", result.origin)

    def test_http_url_of_apex_becomes_https_farm(self):
        result = normalize_public_host("http://example.com")
        self.assertEqual(result.origin, "https://farm.example.com")

    def test_ip_untouched(self):
        result = normalize_public_host("192.168.1.10")
        self.assertTrue(result.ok)
        self.assertEqual(result.host, "192.168.1.10")
        self.assertEqual(result.origin, "http://192.168.1.10")
        self.assertNotIn("farm.", result.origin)

    def test_ip_with_port(self):
        result = normalize_public_host("192.168.1.10:3000")
        self.assertEqual(result.origin, "http://192.168.1.10:3000")

    def test_localhost_untouched(self):
        result = normalize_public_host("localhost")
        self.assertEqual(result.origin, "http://localhost")
        self.assertNotIn("farm.", result.origin)

    def test_localhost_port(self):
        result = normalize_public_host("localhost:43123")
        self.assertEqual(result.origin, "http://localhost:43123")

    def test_loopback_url(self):
        result = normalize_public_host("http://127.0.0.1:43123")
        self.assertEqual(result.origin, "http://127.0.0.1:43123")

    def test_explicit_farm_localhost_kept(self):
        result = normalize_public_host("farm.localhost")
        self.assertEqual(result.origin, "http://farm.localhost")

    def test_single_label_not_prefixed(self):
        result = normalize_public_host("farmos")
        self.assertEqual(result.origin, "https://farmos")
        self.assertNotIn("farm.farmos", result.origin)

    def test_spaces_rejected(self):
        result = normalize_public_host("example .com")
        self.assertFalse(result.ok)
        self.assertIn("space", result.error.lower())

    def test_junk_rejected(self):
        for raw in ("http://", "://oops", "not a domain", "example.com/foo bar", "javascript:alert(1)"):
            result = normalize_public_host(raw)
            self.assertFalse(result.ok, msg=raw)

    def test_empty_label_rejected(self):
        result = normalize_public_host("example..com")
        self.assertFalse(result.ok)

    def test_qr_payload_uses_scan_path_when_host_set(self):
        origin = normalize_public_host("example.com").origin
        self.assertEqual(qr_payload("spool", "SPOOL-1", origin), "https://farm.example.com/scan/spool/SPOOL-1")

    def test_qr_payload_stays_local_when_unset(self):
        self.assertEqual(qr_payload("spool", "SPOOL-1", ""), "farmos:spool:SPOOL-1")
        self.assertEqual(qr_payload("bin", "BIN-A", normalize_public_host("").origin), "farmos:bin:BIN-A")


if __name__ == "__main__":
    unittest.main()
