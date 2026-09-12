import unittest
from unittest.mock import patch

from app.services.auspost import (
    AusPostClient,
    AusPostError,
    address_from_shopify,
    address_from_store_payload,
    address_from_woocommerce,
    auspost_party,
    build_shipment_payload,
    extract_tracking,
    merge_address,
    normalize_au_state,
    parse_auspost_errors,
    validate_au_address,
)


WOO_ORDER = {
    "id": 1042,
    "number": "1042",
    "billing": {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "company": "Analytical Engines",
        "email": "ada@example.com",
        "phone": "0391110000",
        "address_1": "1 Billing Lane",
        "city": "Carlton",
        "state": "VIC",
        "postcode": "3053",
        "country": "AU",
    },
    "shipping": {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "company": "Analytical Engines",
        "address_1": "12 Flinders Street",
        "address_2": "Level 3",
        "city": "Melbourne",
        "state": "Victoria",
        "postcode": "3000",
        "country": "AU",
        "phone": "0400111222",
    },
}

SHOPIFY_ORDER = {
    "id": 998877,
    "email": "ada@example.com",
    "customer": {"first_name": "Ada", "last_name": "Lovelace"},
    "shipping_address": {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "company": "Analytical Engines",
        "address1": "12 Flinders Street",
        "address2": "Level 3",
        "city": "Melbourne",
        "province": "Victoria",
        "province_code": "VIC",
        "zip": "3000",
        "country": "Australia",
        "country_code": "AU",
        "phone": "0400111222",
    },
}


class StateNormalizeTests(unittest.TestCase):
    def test_full_name_and_code(self):
        self.assertEqual(normalize_au_state("Victoria"), "VIC")
        self.assertEqual(normalize_au_state("vic"), "VIC")
        self.assertEqual(normalize_au_state("New South Wales"), "NSW")
        self.assertEqual(normalize_au_state("ACT"), "ACT")


class WooAddressTests(unittest.TestCase):
    def test_maps_suburb_state_postcode(self):
        addr = address_from_woocommerce(WOO_ORDER)
        self.assertEqual(addr["suburb"], "Melbourne")
        self.assertEqual(addr["state"], "VIC")
        self.assertEqual(addr["postcode"], "3000")
        self.assertEqual(addr["name"], "Ada Lovelace")
        self.assertEqual(addr["business_name"], "Analytical Engines")
        self.assertEqual(addr["lines"], ["12 Flinders Street", "Level 3"])
        self.assertEqual(addr["phone"], "0400111222")
        self.assertEqual(addr["email"], "ada@example.com")
        party = auspost_party(addr)
        self.assertEqual(party["suburb"], "Melbourne")
        self.assertEqual(party["state"], "VIC")
        self.assertEqual(party["postcode"], "3000")
        self.assertEqual(party["lines"][0], "12 Flinders Street")

    def test_falls_back_to_billing_when_shipping_empty(self):
        addr = address_from_woocommerce({"billing": WOO_ORDER["billing"], "shipping": {}})
        self.assertEqual(addr["suburb"], "Carlton")
        self.assertEqual(addr["postcode"], "3053")
        self.assertEqual(addr["email"], "ada@example.com")


class ShopifyAddressTests(unittest.TestCase):
    def test_maps_suburb_state_postcode(self):
        addr = address_from_shopify(SHOPIFY_ORDER)
        self.assertEqual(addr["suburb"], "Melbourne")
        self.assertEqual(addr["state"], "VIC")
        self.assertEqual(addr["postcode"], "3000")
        self.assertEqual(addr["lines"], ["12 Flinders Street", "Level 3"])
        self.assertEqual(addr["phone"], "0400111222")
        self.assertEqual(addr["email"], "ada@example.com")

    def test_nested_order_envelope(self):
        addr = address_from_shopify({"order": SHOPIFY_ORDER})
        self.assertEqual(addr["suburb"], "Melbourne")
        self.assertEqual(addr["postcode"], "3000")

    def test_store_payload_uses_source(self):
        woo = address_from_store_payload(WOO_ORDER, "woocommerce")
        shop = address_from_store_payload(SHOPIFY_ORDER, "shopify")
        self.assertEqual(woo["suburb"], shop["suburb"])
        self.assertEqual(woo["state"], shop["state"])
        self.assertEqual(woo["postcode"], shop["postcode"])


class ValidateAddressTests(unittest.TestCase):
    def test_requires_suburb_state_postcode(self):
        errors = validate_au_address({"name": "A", "lines": ["1 St"]}, who="Ship-to")
        joined = " ".join(errors)
        self.assertIn("suburb", joined)
        self.assertIn("state", joined)
        self.assertIn("postcode", joined)

    def test_accepts_complete_address(self):
        addr = address_from_woocommerce(WOO_ORDER)
        self.assertEqual(validate_au_address(addr), [])


class PayloadTests(unittest.TestCase):
    def test_weight_converted_to_kg(self):
        from_addr = merge_address({}, {"name": "Farm", "lines": ["1 Farm Rd"], "suburb": "Clayton", "state": "VIC", "postcode": "3168"})
        to_addr = address_from_woocommerce(WOO_ORDER)
        payload = build_shipment_payload(
            from_addr=from_addr,
            to_addr=to_addr,
            product_id="AUS_PARCEL_EXPRESS",
            weight_g=500,
            length_cm=20,
            width_cm=15,
            height_cm=10,
            reference="RK-1042",
            contents="Flex Rack 5",
        )
        item = payload["shipments"][0]["items"][0]
        self.assertEqual(item["product_id"], "AUS_PARCEL_EXPRESS")
        self.assertEqual(item["weight"], 0.5)
        self.assertEqual(payload["shipments"][0]["to"]["suburb"], "Melbourne")
        self.assertEqual(payload["shipments"][0]["to"]["state"], "VIC")
        self.assertEqual(payload["shipments"][0]["to"]["postcode"], "3000")


class ErrorParseTests(unittest.TestCase):
    def test_401(self):
        err = parse_auspost_errors({"errors": [{"message": "Unauthorised"}]}, 401)
        self.assertEqual(err.status_code, 401)
        self.assertIn("credentials", err.message.lower())

    def test_postcode(self):
        err = parse_auspost_errors({"errors": [{"field": "to.postcode", "message": "postcode is invalid"}]}, 400)
        self.assertIn("postcode", err.message.lower())


class DummyResponse:
    def __init__(self, status_code, json_data=None, content=b"", headers=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.headers = headers or {}
        self.text = text or ("" if json_data is None else str(json_data))

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class DummyClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def request(self, method, url, headers=None, json=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return self.responses.pop(0)

    async def get(self, url):
        self.calls.append({"method": "GET", "url": url})
        return self.responses.pop(0)


class AusPostClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_shipments_uses_basic_auth_and_account_header(self):
        client = AusPostClient(api_key="key", password="secret", account_number="000123", sandbox=True)
        dummy = DummyClient(
            [
                DummyResponse(
                    200,
                    {
                        "shipments": [
                            {
                                "shipment_id": "abc",
                                "items": [{"tracking_details": {"consignment_id": "DEMO-NOT-USED", "article_id": "DEMO-NOT-USED"}}],
                            }
                        ]
                    },
                )
            ]
        )
        with patch("app.services.auspost.httpx.AsyncClient", return_value=dummy):
            body = await client.create_shipments({"shipments": []})
        self.assertEqual(body["shipments"][0]["shipment_id"], "abc")
        self.assertEqual(dummy.calls[0]["headers"]["Account-Number"], "000123")
        self.assertTrue(dummy.calls[0]["url"].startswith("https://digitalapi.auspost.com.au/test/shipping/v1/"))
        consignment, tracking = extract_tracking(body["shipments"][0])
        self.assertEqual(consignment, "DEMO-NOT-USED")
        self.assertEqual(tracking, "DEMO-NOT-USED")

    async def test_401_does_not_raise_live_network(self):
        client = AusPostClient(api_key="bad", password="bad", account_number="000")
        dummy = DummyClient([DummyResponse(401, {"errors": [{"message": "Unauthorised"}]}, text="Unauthorised")])
        with patch("app.services.auspost.httpx.AsyncClient", return_value=dummy):
            with self.assertRaises(AusPostError) as ctx:
                await client.create_shipments({"shipments": []})
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("credentials", ctx.exception.message.lower())

    async def test_fetch_label_pdf(self):
        client = AusPostClient(api_key="key", password="secret", account_number="000123")
        dummy = DummyClient([DummyResponse(200, content=b"%PDF-fake", headers={"content-type": "application/pdf"})])
        with patch("app.services.auspost.httpx.AsyncClient", return_value=dummy):
            pdf = await client.fetch_label_pdf("label-1")
        self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
