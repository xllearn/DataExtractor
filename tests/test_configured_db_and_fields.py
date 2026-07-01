import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_dotenv_database_url_keeps_dollar_sign_password(self):
        from config_loader import load_db_config

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "DATABASE_URL=mysql+pymysql://user:p$word@127.0.0.1:3306/db?charset=utf8mb4\n",
                encoding="utf-8-sig",
            )
            path = root / "db_config.yml"
            path.write_text(
                """
database:
  url: "${DATABASE_URL}"
source:
  table: articles
  html_column: Content
""",
                encoding="utf-8",
            )

            with patch.dict(__import__("os").environ, {}, clear=True), patch("config_loader.PROJECT_ROOT", root):
                config = load_db_config(path)

        self.assertEqual(config.database_url, "mysql+pymysql://user:p$word@127.0.0.1:3306/db?charset=utf8mb4")

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


    def test_llm_config_overrides_settings_and_expands_environment(self):
        from config import apply_llm_config, load_settings

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm_config.yml"
            path.write_text(
                """
provider: custom
api_key: "${LLM_API_KEY}"
base_url: https://example.com/v1
model: custom-model
""",
                encoding="utf-8",
            )
            self.addCleanup(lambda: __import__("os").environ.pop("LLM_API_KEY", None))
            __import__("os").environ["LLM_API_KEY"] = "sk-test-1234567890"

            settings = apply_llm_config(load_settings(), path)

        self.assertEqual(settings.llm_provider, "custom")
        self.assertEqual(settings.llm_api_key, "sk-test-1234567890")
        self.assertEqual(settings.llm_base_url, "https://example.com/v1")
        self.assertEqual(settings.llm_model, "custom-model")


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

    def test_builds_count_query_with_same_safe_filters(self):
        from config_loader import DbConfig, QueryConfig, SourceConfig
        from db_reader import build_article_count_query
        from keyword_utils import expand_keyword_groups

        config = DbConfig(
            exists=True,
            database_url="sqlite:///:memory:",
            source=SourceConfig(
                table="数据源.商业补充保险",
                id_column="id",
                info_id_column="info_id",
                title_column="标题",
                html_column="正文",
                text_column="纯文本",
                source_url_column="链接",
            ),
            query=QueryConfig(keyword_mode="or"),
        )

        selected_query = build_article_count_query(
            config=config,
            selected_ids=["1", "2"],
            keyword_groups=expand_keyword_groups("医保"),
            keyword_mode="or",
        )
        keyword_query = build_article_count_query(
            config=config,
            selected_ids=[],
            keyword_groups=expand_keyword_groups("医保"),
            keyword_mode="or",
        )

        self.assertIn("SELECT COUNT(*) AS total", selected_query.statement)
        self.assertIn("FROM `数据源`.`商业补充保险`", selected_query.statement)
        self.assertIn("`id` IN", selected_query.statement)
        self.assertIn("`info_id` IN", selected_query.statement)
        self.assertNotIn("LIKE", selected_query.statement)
        self.assertNotIn("LIMIT", selected_query.statement)
        self.assertNotIn("OFFSET", selected_query.statement)
        self.assertEqual(selected_query.params["selected_id_0"], "1")
        self.assertIn("LIKE", keyword_query.statement)
        self.assertTrue(any(str(value).startswith("%医保%") for value in keyword_query.params.values()))

    def test_allows_chinese_table_and_column_identifiers(self):
        from db_reader import quote_identifier, quote_table, validate_column_name, validate_table_name

        self.assertEqual(validate_table_name("temp_商业补充保险_20250523"), "temp_商业补充保险_20250523")
        self.assertEqual(validate_table_name("db_name.temp_商业补充保险_20250523"), "db_name.temp_商业补充保险_20250523")
        self.assertEqual(validate_column_name("地区名称"), "地区名称")
        self.assertEqual(validate_column_name("审核日期"), "审核日期")
        self.assertEqual(quote_table("db_name.temp_商业补充保险_20250523"), "`db_name`.`temp_商业补充保险_20250523`")
        self.assertEqual(quote_identifier("保险类型"), "`保险类型`")

    def test_rejects_dangerous_table_and_column_identifiers(self):
        from db_reader import DbReaderError, validate_column_name, validate_table_name

        dangerous = [
            "table; DROP TABLE user",
            "table name",
            "table--comment",
            "table/*comment*/",
            "table`name",
            "table'name",
            'table"name',
            "table(name)",
            "table+name",
        ]
        for value in dangerous:
            with self.subTest(table=value):
                with self.assertRaises(DbReaderError):
                    validate_table_name(value)
            with self.subTest(column=value):
                with self.assertRaises(DbReaderError):
                    validate_column_name(value)

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
                "--llm-config",
                "config/llm_config.yml",
                "--table-config",
                "config/table_mapping.yml",
                "--no-llm",
            ]
        )

        self.assertEqual(args.config, "config/db_config.yml")
        self.assertEqual(args.field_config, "config/field_mapping.yml")
        self.assertEqual(args.keyword, "医保 报销")
        self.assertEqual(args.keyword_mode, "and")
        self.assertEqual(args.selected_ids, "1,2")
        self.assertEqual(args.llm_format, "legacy")
        self.assertEqual(args.llm_config, "config/llm_config.yml")
        self.assertEqual(args.table_config, "config/table_mapping.yml")
        self.assertTrue(args.no_llm)

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
