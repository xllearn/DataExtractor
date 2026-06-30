# DataExtractor Acceptance Checklist

## Phase 10-12 Runtime Controls

- [x] `--log-dir` can redirect run logs, failed records, evidence logs and intermediate files.
- [x] `--dry-run` disables LLM initialization, OCR retry and Excel output.
- [x] `--no-excel` runs extraction and logging without writing workbooks.
- [x] `--save-intermediate` writes per-record JSON payloads under `log-dir/intermediate/`.
- [x] `--fail-fast` stops after the first record-level failure.
- [x] `--max-record-errors` stops processing after the configured failure count.
- [x] `--strict-config` rejects DB mode when `DATABASE_URL` or configured DB tables are missing.

## Traceability

- [x] Collection logs include `input_mode` for `input-xlsx`, `configured-db` and `legacy-db` paths.
- [x] Collection logs include `initial_confidence_score`, `ocr_retry_confidence_score`, `ocr_improved` and `final_attempt`.
- [x] `--no-llm` collection logs use `llm_format=none`, `ocr_triggered=false` and a review reason that says LLM/OCR was skipped.
- [x] Conflict evidence keeps legacy fields and also includes `source_a`, `value_a`, `source_b`, `value_b`, `chosen_source`, `chosen_value` and `reason`.

## Excel Output

- [x] Template workbooks preserve non-target sheets.
- [x] Only target sheets are replaced: `结果数据`, `采集日志`, `字段证据`, `冲突证据`, `抽取评估`, `失败记录`.
- [x] Excel formula-like values are escaped before writing cells.
- [x] Control characters are removed and cell values are limited to Excel's maximum text length.
- [x] Single and merge Excel write failures return a non-zero exit code and write failed-record logs.

## Stability and Security

- [x] Database URLs are masked before logging.
- [x] Common secret patterns such as API keys, passwords and tokens are masked before logging.
- [x] Table YAML syntax errors raise a clear `TableMappingError`.
- [x] Table mapping confidence values are clamped to `0..1`.
- [x] OCR retry output is selected by confidence comparison, not unconditional replacement.

## Verification

- [x] Unit tests cover CLI runtime flags, dry-run flag resolution, intermediate saving and failure thresholds.
- [x] Unit tests cover no-LLM behavior, collection log metadata and OCR skip behavior.
- [x] Unit tests cover conflict evidence generic fields.
- [x] Unit tests cover template sheet preservation and Excel formula sanitization.
- [x] Unit tests cover secret masking, strict config and table config validation.
