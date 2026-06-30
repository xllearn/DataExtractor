import tempfile
import unittest
from pathlib import Path

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ConfigLoaderTests(unittest.TestCase):
    def test_loads_yaml_and_expands_database_url_from_environment(self):
        from config_loader import load_db_config

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db_config.yml"
            path.write_text(
                """
database:
  url: "${DATABASE_URL}"
source:
  table: articles
  id_column: id
  info_id_column: info_id
  title_column: Title
  html_column: Content
  text_column: Text
  article_time_column: PublishTime
  audit_time_column: AuditTime
  region_column: areaname
  source_url_column: SourceURL
  related_info_column: RelatedInfo
  insurance_type_column: insurancetypename
query:
  default_limit: 25
  keyword_mode: and
direct_field_columns:
  文章时间: PublishTime
  审核日期: AuditTime
  info_id: info_id
  地区名称: areaname
  保险类型: insurancetypename
""",
                encoding="utf-8",
            )

            self.addCleanup(lambda: __import__("os").environ.pop("DATABASE_URL", None))
            __import__("os").environ["DATABASE_URL"] = "sqlite:///tmp.db"

            config = load_db_config(path)

            self.assertTrue(config.exists)
            self.assertEqual(config.database_url, "sqlite:///tmp.db")
            self.assertEqual(config.source.table, "articles")
            self.assertEqual(config.query.default_limit, 25)
            self.assertEqual(config.query.keyword_mode, "and")

    def test_missing_config_file_returns_legacy_fallback(self):
        from config_loader import load_db_config

        config = load_db_config(Path(tempfile.gettempdir()) / "missing-db-config.yml")

        self.assertFalse(config.exists)
        self.assertFalse(config.use_configured_reader)

    def test_existing_config_missing_required_table_has_clear_error(self):
        from config_loader import ConfigError, load_db_config

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yml"
            path.write_text(
                """
database:
  url: "sqlite:///:memory:"
source:
  table: ""
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "source.table"):
                load_db_config(path, require_ready=True)

    def test_parse_selected_ids_ignores_empty_parts(self):
        from config_loader import parse_selected_ids

        self.assertEqual(parse_selected_ids(" 1, 2,, abc "), ["1", "2", "abc"])

    def test_config_default_limit_wins_when_cli_limit_missing_for_configured_db(self):
        from config import build_arg_parser, load_settings
        from config_loader import DbConfig, QueryConfig
        from main import resolve_effective_limit

        parser = build_arg_parser(load_settings())
        args = parser.parse_args([])
        db_config = DbConfig(exists=True, database_url="sqlite:///:memory:", query=QueryConfig(default_limit=25))

        self.assertIsNone(args.limit)
        self.assertEqual(resolve_effective_limit(args.limit, load_settings(), db_config, configured_db_enabled=True), 25)

    def test_cli_limit_wins_over_config_default_limit(self):
        from config import build_arg_parser, load_settings
        from config_loader import DbConfig, QueryConfig
        from main import resolve_effective_limit

        parser = build_arg_parser(load_settings())
        args = parser.parse_args(["--limit", "7"])
        db_config = DbConfig(exists=True, database_url="sqlite:///:memory:", query=QueryConfig(default_limit=25))

        self.assertEqual(resolve_effective_limit(args.limit, load_settings(), db_config, configured_db_enabled=True), 7)


class KeywordUtilsTests(unittest.TestCase):
    def test_expands_single_and_multiple_keywords(self):
        from keyword_utils import expand_keyword_groups

        groups = expand_keyword_groups("医保 报销")

        self.assertEqual(groups[0][0], "医保")
        self.assertIn("医疗保险", groups[0])
        self.assertIn("医保基金", groups[0])
        self.assertEqual(groups[1][0], "报销")
        self.assertIn("支付", groups[1])

    def test_empty_keyword_returns_no_groups(self):
        from keyword_utils import expand_keyword_groups

        self.assertEqual(expand_keyword_groups("   "), [])


class DbReaderTests(unittest.TestCase):
    def test_builds_selected_ids_query_before_keyword_query(self):
        from config_loader import DbConfig, QueryConfig, SourceConfig
        from db_reader import build_article_query
        from keyword_utils import expand_keyword_groups

        config = DbConfig(
            exists=True,
            database_url="sqlite:///:memory:",
            source=SourceConfig(
                table="articles",
                id_column="id",
                info_id_column="info_id",
                title_column="Title",
                html_column="Content",
                text_column="Text",
                source_url_column="SourceURL",
            ),
            query=QueryConfig(keyword_mode="or"),
        )

        query = build_article_query(
            config=config,
            limit=10,
            offset=0,
            selected_ids=["1", "2"],
            keyword_groups=expand_keyword_groups("医保"),
            keyword_mode="or",
        )

        self.assertIn("`id` IN", str(query.statement))
        self.assertIn("`info_id` IN", str(query.statement))
        self.assertNotIn("LIKE", str(query.statement))
        self.assertEqual(query.params["selected_id_0"], "1")
        self.assertEqual(query.params["selected_id_1"], "2")

    def test_maps_database_row_to_legacy_record_shape(self):
        from config_loader import DbConfig, SourceConfig
        from db_reader import map_row_to_record

        config = DbConfig(
            exists=True,
            source=SourceConfig(
                table="articles",
                id_column="id",
                info_id_column="info_id",
                title_column="title",
                html_column="html",
                audit_time_column="audit_time",
                region_column="region",
                source_url_column="url",
                insurance_type_column="insurance",
            ),
            direct_field_columns={"文章时间": "audit_time", "info_id": "info_id", "地区名称": "region", "保险类型": "insurance"},
        )

        record = map_row_to_record(
            {
                "id": 7,
                "info_id": "A-1",
                "title": "标题",
                "html": "<p>正文</p>",
                "audit_time": "2026-01-02",
                "region": "山东省",
                "url": "https://example.com",
                "insurance": "医保",
            },
            config,
        )

        self.assertEqual(record["Title"], "标题")
        self.assertEqual(record["Content"], "<p>正文</p>")
        self.assertEqual(record["SourceURL"], "https://example.com")
        self.assertEqual(record["info_id"], "A-1")
        self.assertEqual(record["_source_id"], 7)
        self.assertEqual(record["_direct_fields"]["地区名称"], "山东省")


class FieldMappingTests(unittest.TestCase):
    def test_normalizes_aliases_defaults_and_removes_extra_fields(self):
        from field_mapping import load_field_mapping, normalize_record_fields
        from utils import EXCEL_HEADERS

        mapping = load_field_mapping(None)
        row = normalize_record_fields(
            {"支付比例": "80%", "起付线": "500元", "最高支付限额": "15万元", "多余": "x"},
            mapping,
        )

        self.assertEqual(list(row.keys()), EXCEL_HEADERS)
        self.assertEqual(row["报销比例"], "80%")
        self.assertEqual(row["起付标准"], "500元")
        self.assertEqual(row["补助限额"], "15万元")
        self.assertNotIn("多余", row)
        self.assertEqual(row["执行状态"], "执行中")

    def test_bad_header_order_raises_clear_error(self):
        from field_mapping import FieldMappingError, load_field_mapping
        from utils import EXCEL_HEADERS

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "field_mapping.yml"
            wrong = list(EXCEL_HEADERS)
            wrong[0], wrong[1] = wrong[1], wrong[0]
            path.write_text("headers:\n" + "\n".join(f"  - {item}" for item in wrong), encoding="utf-8")

            with self.assertRaisesRegex(FieldMappingError, "headers"):
                load_field_mapping(path)


class IntegrationSurfaceTests(unittest.TestCase):
    def test_arg_parser_exposes_new_cli_options(self):
        from config import build_arg_parser, load_settings

        parser = build_arg_parser(load_settings())
        args = parser.parse_args(
            [
                "--config",
                "config/db_config.yml",
                "--field-config",
                "config/field_mapping.yml",
                "--keyword",
                "医保 报销",
                "--keyword-mode",
                "and",
                "--selected-ids",
                "1,2",
                "--llm-format",
                "legacy",
            ]
        )

        self.assertEqual(args.config, "config/db_config.yml")
        self.assertEqual(args.field_config, "config/field_mapping.yml")
        self.assertEqual(args.keyword, "医保 报销")
        self.assertEqual(args.keyword_mode, "and")
        self.assertEqual(args.selected_ids, "1,2")
        self.assertEqual(args.llm_format, "legacy")

    def test_json_normalization_uses_field_mapping_aliases(self):
        from json_utils import normalize_llm_rows

        with tempfile.TemporaryDirectory() as tmp:
            rows = normalize_llm_rows(
                '{"支付比例":"80%","起付线":"500元","最高支付限额":"15万元","多余":"x"}',
                {"AuditTime": "2026-01-02"},
                "20260630",
                Path(tmp),
            )

        self.assertEqual(rows[0]["报销比例"], "80%")
        self.assertEqual(rows[0]["起付标准"], "500元")
        self.assertEqual(rows[0]["补助限额"], "15万元")
        self.assertNotIn("多余", rows[0])

    def test_invalid_json_fallback_still_applies_direct_fields(self):
        from json_utils import normalize_llm_rows

        record = {
            "AuditTime": "2026-01-02",
            "_direct_fields": {"info_id": "A-001", "地区名称": "山东省", "保险类型": "居民医保"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            rows = normalize_llm_rows("not json", record, "20260630", Path(tmp))

        self.assertEqual(rows[0]["info_id"], "A-001")
        self.assertEqual(rows[0]["地区名称"], "山东省")
        self.assertEqual(rows[0]["保险类型"], "居民医保")

    def test_empty_json_array_fallback_still_applies_direct_fields(self):
        from json_utils import normalize_llm_rows

        record = {
            "AuditTime": "2026-01-02",
            "_direct_fields": {"info_id": "A-002", "地区名称": "济南市", "保险类型": "职工医保"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            rows = normalize_llm_rows("[]", record, "20260630", Path(tmp))

        self.assertEqual(rows[0]["info_id"], "A-002")
        self.assertEqual(rows[0]["地区名称"], "济南市")
        self.assertEqual(rows[0]["保险类型"], "职工医保")

    def test_legacy_db_keyword_is_rejected_instead_of_ignored(self):
        from main import validate_keyword_supported

        with self.assertRaisesRegex(ValueError, "--keyword 需要启用"):
            validate_keyword_supported(keyword="医保", configured_db_enabled=False)


if __name__ == "__main__":
    unittest.main()
