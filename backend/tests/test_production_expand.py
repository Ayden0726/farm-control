import unittest

from app.services.production_expand import BomLine, TaggedGCode, expand_product_to_run_items


def _bom(*rows: tuple[str, str, int, bool]) -> list[BomLine]:
    return [BomLine(part_id=r[0], part_sku=r[1], quantity=r[2], is_optional=r[3]) for r in rows]


def _gcode(gid: str, part: str, name: str, *, archived=False, approved=False, version=1) -> TaggedGCode:
    return TaggedGCode(
        id=gid,
        part_id=part,
        filename=name,
        is_archived=archived,
        production_approved=approved,
        version=version,
    )


class ExpandProductTests(unittest.TestCase):
    def test_adds_tagged_gcode_per_bom_part(self):
        result = expand_product_to_run_items(
            _bom(("h", "Handle", 4, False), ("f", "Frame", 1, False)),
            [
                _gcode("g1", "h", "Handle-x4.gcode", approved=True),
                _gcode("g2", "f", "Frame.gcode"),
            ],
            product_qty=2,
        )
        items = result["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["gcode_file_id"], "g1")
        self.assertEqual(items[0]["required_qty"], 8)
        self.assertEqual(items[1]["gcode_file_id"], "g2")
        self.assertEqual(items[1]["required_qty"], 2)
        self.assertEqual(result["missing_gcode"], [])
        self.assertEqual(result["multi_file_parts"], [])

    def test_includes_every_active_file_for_a_part(self):
        result = expand_product_to_run_items(
            _bom(("h", "Handle", 4, False)),
            [
                _gcode("old", "h", "Handle.gcode", version=1),
                _gcode("new", "h", "Handle-x4.gcode", approved=True, version=2),
                _gcode("dead", "h", "Handle-old.gcode", archived=True),
            ],
            product_qty=1,
        )
        ids = [row["gcode_file_id"] for row in result["items"]]
        self.assertEqual(ids, ["new", "old"])
        self.assertNotIn("dead", ids)
        self.assertEqual(result["multi_file_parts"], ["Handle"])

    def test_skips_optional_unless_requested(self):
        bom = _bom(("h", "Handle", 4, False), ("b", "Brace", 1, True))
        gcodes = [_gcode("g1", "h", "Handle.gcode"), _gcode("g2", "b", "Brace.gcode")]
        skipped = expand_product_to_run_items(bom, gcodes, 1, include_optional=False)
        self.assertEqual([r["part_sku"] for r in skipped["items"]], ["Handle"])
        self.assertEqual(skipped["optional_skipped"], ["Brace"])
        included = expand_product_to_run_items(bom, gcodes, 1, include_optional=True)
        self.assertEqual([r["part_sku"] for r in included["items"]], ["Handle", "Brace"])

    def test_missing_gcode_still_adds_the_part(self):
        result = expand_product_to_run_items(_bom(("h", "Handle", 4, False)), [], 1)
        self.assertEqual(result["missing_gcode"], ["Handle"])
        self.assertIsNone(result["items"][0]["gcode_file_id"])
        self.assertEqual(result["items"][0]["required_qty"], 4)


if __name__ == "__main__":
    unittest.main()
