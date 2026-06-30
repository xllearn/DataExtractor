import tempfile
import unittest
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class StabilitySecurityTests(unittest.TestCase):
    def test_sensitive_text_and_database_url_are_masked(self):
        from security_utils import mask_database_url, mask_sensitive_text

        self.assertEqual(
            mask_database_url("mysql+pymysql://user:secret@127.0.0.1:3306/db?charset=utf8mb4"),
            "mysql+pymysql://user:***@127.0.0.1:3306/db?charset=utf8mb4",
        )
        masked = mask_sensitive_text("LLM_API_KEY=sk-123456789 password=secret token=abc")
        self.assertNotIn("sk-123456789", masked)
        self.assertNotIn("password=secret", masked)
        self.assertNotIn("token=abc", masked)

    def test_table_mapping_invalid_yaml_has_clear_error(self):
        from table_extractor import TableMappingError, load_table_mapping

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yml"
            path.write_text("header_aliases: [", encoding="utf-8")

            with self.assertRaisesRegex(TableMappingError, "表格配置 YAML 解析失败"):
                load_table_mapping(path)

    def test_table_mapping_confidence_is_clamped(self):
        from table_extractor import load_table_mapping

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table.yml"
            path.write_text("defaults:\n  confidence: 9\n", encoding="utf-8")

            mapping = load_table_mapping(path)

        self.assertEqual(mapping.confidence, 1.0)

    def test_strict_config_rejects_missing_database_url(self):
        from config_loader import DbConfig
        from main import validate_strict_runtime_config

        with self.assertRaisesRegex(ValueError, "DATABASE_URL"):
            validate_strict_runtime_config(DbConfig(exists=False), input_xlsx="")


if __name__ == "__main__":
    unittest.main()
