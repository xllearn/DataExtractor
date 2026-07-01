import json
import tempfile
import unittest
from pathlib import Path


class RunSummaryTests(unittest.TestCase):
    def test_run_summary_writes_summary_failed_records_and_retry_ids(self):
        from run_summary import RunSummary

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.xlsx"
            summary = RunSummary(input_mode="input-xlsx", total_records=2, log_dir=Path(tmp))
            summary.record_success(output_rows=3, manual_review=True, ocr_triggered=True, ocr_failed=False)
            summary.record_failure(
                {
                    "record_index": 2,
                    "source_id": "source-2",
                    "info_id": "",
                    "Title": "失败",
                    "SourceURL": "https://example.com/2",
                    "phase": "process_record",
                    "error": "boom",
                }
            )
            summary.add_output_path(output)
            summary.write_artifacts()

            payload = json.loads((Path(tmp) / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["input_mode"], "input-xlsx")
            self.assertEqual(payload["total_records"], 2)
            self.assertEqual(payload["success_records"], 1)
            self.assertEqual(payload["failed_records"], 1)
            self.assertEqual(payload["output_rows"], 3)
            self.assertEqual(payload["ocr_triggered_records"], 1)
            self.assertEqual(payload["manual_review_records"], 1)
            self.assertEqual(payload["output_excel_path"], str(output))

            failed_lines = (Path(tmp) / "failed_records.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(failed_lines), 1)
            failed = json.loads(failed_lines[0])
            self.assertEqual(failed["run_id"], payload["run_id"])
            self.assertEqual(failed["source_id"], "source-2")

            retry_ids = (Path(tmp) / "retry_ids.txt").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(retry_ids, ["source-2"])


if __name__ == "__main__":
    unittest.main()
