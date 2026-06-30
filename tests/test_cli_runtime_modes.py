import tempfile
import unittest
from pathlib import Path
import sys
import logging
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class CliRuntimeModeTests(unittest.TestCase):
    def test_new_runtime_args_are_parsed(self):
        from config import build_arg_parser, load_settings

        args = build_arg_parser(load_settings()).parse_args(
            [
                "--log-dir",
                "custom_logs",
                "--dry-run",
                "--max-record-errors",
                "3",
                "--fail-fast",
                "--strict-config",
                "--no-excel",
                "--save-intermediate",
            ]
        )

        self.assertEqual(args.log_dir, "custom_logs")
        self.assertTrue(args.dry_run)
        self.assertEqual(args.max_record_errors, 3)
        self.assertTrue(args.fail_fast)
        self.assertTrue(args.strict_config)
        self.assertTrue(args.no_excel)
        self.assertTrue(args.save_intermediate)

    def test_should_stop_processing_respects_fail_fast_and_max_errors(self):
        from main import should_stop_processing

        self.assertTrue(should_stop_processing(record_error_count=1, max_record_errors=20, fail_fast=True))
        self.assertFalse(should_stop_processing(record_error_count=2, max_record_errors=3, fail_fast=False))
        self.assertTrue(should_stop_processing(record_error_count=3, max_record_errors=3, fail_fast=False))

    def test_dry_run_runtime_options_skip_llm_ocr_and_excel(self):
        from main import resolve_runtime_flags

        flags = resolve_runtime_flags(dry_run=True, no_llm=False, no_ocr=False, no_excel=False)

        self.assertTrue(flags["no_llm"])
        self.assertTrue(flags["no_ocr"])
        self.assertTrue(flags["no_excel"])

    def test_save_intermediate_writes_json_file(self):
        from main import save_intermediate_result

        with tempfile.TemporaryDirectory() as tmp:
            path = save_intermediate_result(
                Path(tmp),
                record_index=1,
                source_id="https://example.com/a",
                info_id="A-001",
                payload={"llm_raw_output": "raw", "fused_records": [{"报销比例": "80%"}]},
            )

            text = path.read_text(encoding="utf-8")

        self.assertIn("llm_raw_output", text)
        self.assertIn("A-001", path.name)

    def test_single_mode_excel_write_failure_returns_nonzero_and_masks_error(self):
        from config import Settings
        import main as main_module

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            logs_dir = tmp_path / "logs"
            settings = Settings(
                db_host="127.0.0.1",
                db_port=3306,
                db_name="db",
                db_user="user",
                db_password="secret",
                db_table="articles",
                llm_provider="test",
                llm_api_key="",
                llm_base_url="",
                llm_model="",
                ocr_enabled=False,
                image_base_url="",
                output_dir=tmp_path / "outputs",
                default_mode="single",
                default_limit=1,
                default_offset=0,
            )
            argv = [
                "main.py",
                "--mode",
                "single",
                "--no-llm",
                "--log-dir",
                str(logs_dir),
                "--output-dir",
                str(tmp_path / "outputs"),
                "--limit",
                "1",
            ]
            record = {"Title": "测试", "SourceURL": "https://example.com/a", "Content": "<p>test</p>"}

            with (
                patch.object(sys, "argv", argv),
                patch("main.load_settings", return_value=settings),
                patch("main.fetch_records", return_value=[record]),
                patch("main.extract_record_rows", return_value=[{"备注": "--"}]),
                patch("main.write_extraction_workbook", side_effect=RuntimeError("password=secret")),
            ):
                result = main_module.main()

            failed_text = (logs_dir / "failed_records.jsonl").read_text(encoding="utf-8")
            run_log_text = (logs_dir / "run.log").read_text(encoding="utf-8")
            logging.shutdown()
            logger = logging.getLogger("db_to_excel_extractor")
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()

        self.assertEqual(result, 1)
        self.assertIn("excel_write", failed_text)
        self.assertNotIn("password=secret", failed_text)
        self.assertNotIn("password=secret", run_log_text)


if __name__ == "__main__":
    unittest.main()
