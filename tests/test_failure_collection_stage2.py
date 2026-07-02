import json


def test_retry_ids_skip_source_url_only_failures(tmp_path):
    from run_summary import RunSummary

    summary = RunSummary(input_mode="configured-db", total_records=1, log_dir=tmp_path)
    summary.record_failure({"record_index": 1, "SourceURL": "https://example.com/a", "phase": "llm", "error": "boom"}, count_record_failure=False)
    summary.write_artifacts()

    assert (tmp_path / "failed_records.jsonl").read_text(encoding="utf-8").strip()
    assert (tmp_path / "retry_ids.txt").read_text(encoding="utf-8") == ""


def test_summary_preserves_midrun_failures_and_llm_parse_count(tmp_path):
    from run_summary import RunSummary

    summary = RunSummary(input_mode="input-xlsx", total_records=1, log_dir=tmp_path)
    summary.record_failure({"record_index": 1, "source_id": "S1", "phase": "llm", "error": "parse failed"}, count_record_failure=False)
    summary.record_success(output_rows=1, llm_parse_failed=True)
    payload = summary.write_artifacts()

    failed = [json.loads(line) for line in (tmp_path / "failed_records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert payload["failed_records"] == 0
    assert payload["llm_parse_failed_records"] == 1
    assert failed[0]["source_id"] == "S1"
    assert (tmp_path / "retry_ids.txt").read_text(encoding="utf-8").strip() == "S1"
