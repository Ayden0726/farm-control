import base64
import hashlib
import hmac
import unittest

from app.services.shopify import (
    _customer_name,
    _shipping_total,
    normalize_shop,
    shopify_configured,
    shopify_numeric_id,
    verify_webhook_hmac,
)


class NormalizeShopTests(unittest.TestCase):
    def test_short_name(self):
        self.assertEqual(normalize_shop("MyStore"), "mystore.myshopify.com")

    def test_myshopify_host(self):
        self.assertEqual(normalize_shop("MyStore.myshopify.com"), "mystore.myshopify.com")

    def test_admin_url(self):
        self.assertEqual(
            normalize_shop("https://MyStore.myshopify.com/admin"),
            "mystore.myshopify.com",
        )

    def test_empty(self):
        self.assertEqual(normalize_shop(""), "")
        self.assertEqual(normalize_shop("   "), "")


class ShopifyIdTests(unittest.TestCase):
    def test_int(self):
        self.assertEqual(shopify_numeric_id(998877), "998877")

    def test_string(self):
        self.assertEqual(shopify_numeric_id(" 12345 "), "12345")

    def test_gid(self):
        self.assertEqual(shopify_numeric_id("gid://shopify/Product/998877"), "998877")
        self.assertEqual(shopify_numeric_id("gid://shopify/Order/1001"), "1001")

    def test_rejects_junk(self):
        self.assertIsNone(shopify_numeric_id(None))
        self.assertIsNone(shopify_numeric_id(""))
        self.assertIsNone(shopify_numeric_id("K1Max2"))
        self.assertIsNone(shopify_numeric_id("gid://shopify/Product/abc"))


class WebhookHmacTests(unittest.TestCase):
    def test_accepts_matching_signature(self):
        secret = "shpss_test"
        body = b'{"id":1}'
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        header = base64.b64encode(digest).decode("utf-8")
        self.assertTrue(verify_webhook_hmac(body, header, secret))

    def test_rejects_mismatch(self):
        secret = "shpss_test"
        body = b'{"id":1}'
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        header = base64.b64encode(digest).decode("utf-8")
        self.assertFalse(verify_webhook_hmac(body, "nope", secret))
        self.assertFalse(verify_webhook_hmac(body, header, "other-secret"))
        self.assertFalse(verify_webhook_hmac(body, header, ""))
        self.assertFalse(verify_webhook_hmac(body, None, secret))


class PayloadHelperTests(unittest.TestCase):
    def test_customer_name_from_customer(self):
        self.assertEqual(
            _customer_name({"customer": {"first_name": "Ada", "last_name": "Lovelace"}}),
            "Ada Lovelace",
        )

    def test_customer_name_falls_back_to_email(self):
        self.assertEqual(_customer_name({"email": "ada@example.com"}), "ada@example.com")

    def test_shipping_from_shop_money(self):
        payload = {"total_shipping_price_set": {"shop_money": {"amount": "12.50"}}}
        self.assertEqual(_shipping_total(payload), 12.5)

    def test_shipping_from_lines(self):
        payload = {"shipping_lines": [{"price": "4.00"}, {"price": "1.25"}]}
        self.assertEqual(_shipping_total(payload), 5.25)


class ConfiguredTests(unittest.TestCase):
    def test_needs_shop_and_token(self):
        self.assertFalse(shopify_configured({}))
        self.assertFalse(shopify_configured({"shop": "x.myshopify.com", "token": ""}))
        self.assertTrue(shopify_configured({"shop": "x.myshopify.com", "token": "shpat"}))


if __name__ == "__main__":
    unittest.main()
