import tempfile
import unittest
from pathlib import Path

from app.services.demo_mode import is_demo_part_sku, is_demo_product_sku
from app.services.update_control import (
    apply_dotenv_updates,
    parse_restart_env,
    set_dotenv_key,
    write_restart_request,
)


class DemoSkuTests(unittest.TestCase):
    def test_flex_rack_skus(self) -> None:
        self.assertTrue(is_demo_part_sku("RK-FR5-Handle"))
        self.assertTrue(is_demo_part_sku("rk-fr5-bottomframe"))
        self.assertFalse(is_demo_part_sku("CUSTOM-BRACKET"))
        self.assertFalse(is_demo_part_sku(""))
        self.assertTrue(is_demo_product_sku("RK-FR5"))
        self.assertFalse(is_demo_product_sku("RK-FR5-Handle"))


class DotenvTests(unittest.TestCase):
    def test_replaces_existing_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("SECRET_KEY=keep\nSIMULATED_TIME_SCALE=20\nCORS_ORIGINS=http://x\n", encoding="utf-8")
            set_dotenv_key(path, "SIMULATED_TIME_SCALE", "1")
            text = path.read_text(encoding="utf-8")
            self.assertIn("SIMULATED_TIME_SCALE=1\n", text)
            self.assertNotIn("SIMULATED_TIME_SCALE=20", text)
            self.assertIn("SECRET_KEY=keep", text)
            self.assertIn("CORS_ORIGINS=http://x", text)

    def test_appends_missing_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("SECRET_KEY=keep\n", encoding="utf-8")
            apply_dotenv_updates(path, {"SIMULATED_TIME_SCALE": "1"})
            text = path.read_text(encoding="utf-8")
            self.assertIn("SECRET_KEY=keep", text)
            self.assertIn("SIMULATED_TIME_SCALE=1", text)

    def test_rejects_unsafe_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            with self.assertRaises(ValueError):
                set_dotenv_key(path, "not-a-key", "1")


class RestartEnvTests(unittest.TestCase):
    def test_parse_ignores_junk(self) -> None:
        parsed = parse_restart_env("# comment\nSIMULATED_TIME_SCALE=1\n\nbad line\nFOO=bar\r\n")
        self.assertEqual(parsed["SIMULATED_TIME_SCALE"], "1")
        self.assertEqual(parsed["FOO"], "bar")
        self.assertNotIn("bad line", parsed)

    def test_write_restart_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import os

            os.environ["UPDATE_CONTROL_DIR"] = tmp
            try:
                folder = write_restart_request(reason="demo_mode_off", env={"SIMULATED_TIME_SCALE": "1"})
                self.assertTrue((folder / "restart").is_file())
                self.assertEqual((folder / "restart").read_text(encoding="utf-8").strip(), "demo_mode_off")
                self.assertEqual(
                    parse_restart_env((folder / "restart.env").read_text(encoding="utf-8")),
                    {"SIMULATED_TIME_SCALE": "1"},
                )
            finally:
                os.environ.pop("UPDATE_CONTROL_DIR", None)


if __name__ == "__main__":
    unittest.main()
