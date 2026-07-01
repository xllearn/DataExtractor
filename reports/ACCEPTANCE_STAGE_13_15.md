# DataExtractor Stage 13-15 Acceptance Report

## Summary

- Result directory: `C:\Users\admin\Desktop\DataExtractor_test_results_20260630_165827`
- Overall status: passed
- P0/P1: none found in this run
- GitHub push recommendation: yes, after final sensitive scan

## Changed Capabilities

- Added Excel/manual comparison with overall, core-field, field-level, row-level and difference reports.
- Added AI-generated regression cases with fake LLM and baseline comparison.
- Added image import fallback from manual JSON/CSV/XLSX transcript, database test-table import, Excel generation and manual Excel comparison.
- Added real DB smoke/20 scripts and comprehensive acceptance runner.
- Added FastAPI backend and static web UI for querying records, selecting records, generating Excel and downloading results.
- Expanded disease-name recall while preserving long-sentence and generic-term filters.

## Verification Results

| Check | Result |
| --- | --- |
| `py -m unittest discover -s tests -v` | passed, 78 tests |
| `py -m pytest -q` | passed, 78 tests and 30 subtests |
| project `compileall` with ignored-dir excludes | passed |
| AI generated data | passed |
| real DB smoke | passed, 3 result rows |
| real DB 20 | passed, 50 result rows, 22 non-empty disease names |
| image import DB round trip | passed, 104 result rows |
| image/manual Excel comparison | overall `0.961538`, core `1.0` |
| frontend API tests | passed |

## Notes

- Detailed generated artifacts were written to the desktop result directory, not the repository.
- The raw `py -m compileall .` command traverses an ignored legacy virtual environment under `db_to_excel_extractor\.venv`; the acceptance runner excludes ignored runtime/output directories and compiles project code.
- No real `.env`, logs, outputs, original image, manual Excel, database password or API key is included in this report.

## 2026-07-01 Supplemental Web UI Fix

- Overall status: passed.
- Fixed the frontend JSON parse failure caused by plain-text backend 500 responses.
- API errors now return JSON with `detail` and `error_type`.
- `/api/config/status` now includes `config_path`, `database_status_reason` and `safe_to_query` without exposing secrets.
- Frontend disables search, select-all and Excel generation when `safe_to_query=false`.
- Frontend renders article rows with DOM APIs and `textContent`; source links are limited to `http://` and `https://`.
- Image import database writes now default to test-table-only protection.
- Acceptance scripts now support parameterized image/manual Excel paths and skip image import when local samples are not supplied.
- Download URLs now URL-encode Chinese Excel file names.

## 2026-07-01 Verification

| Check | Result |
| --- | --- |
| `py -m unittest discover -s tests -v` | passed, 90 tests |
| `py -m pytest -q` | passed, 90 tests, 33 subtests, 1 deprecation warning |
| project `compileall` with ignored-dir excludes | passed |
| real-config API health/status/articles/extract/download | passed |
| bad-config API JSON error handling | passed |

Manual API result:

- Real config: `logs/real_db_20/db_config.runtime.yml`
- `/api/config/status`: `database_configured=true`, `safe_to_query=true`
- `/api/articles?limit=1&offset=0`: returned 1 item
- `/api/extract`: success with one selected record and `no_llm=true`
- `/api/download/...`: downloaded successfully; workbook contains 6 sheets
- Bad config: `/api/articles?limit=1` returned `400 application/json` with `error_type=DatabaseNotConfigured`

## 2026-07-01 Supplemental Pagination Job OCR Fix

- Overall status: automated checks passed.
- `/api/articles` now returns real pagination metadata: `total`, `limit`, `offset`, `page`, `page_size`, `total_pages`, `has_next`, `has_prev`.
- `/api/extract` now creates a job and returns `job_id`, `status_url`, and `result_page`.
- Added `/api/jobs/{job_id}` and `/api/jobs/{job_id}/preview`; preview returns only the `结果数据` sheet, first 100 rows, without local paths.
- Frontend now has previous/next pagination, page-size selector, total count, cross-page selection, clear selection, job result redirect, and result-page preview.
- `/api/config/status` now reports OCR availability and reason.
- CLI supports external OCR fallback via `--ocr-text-file` and `--ocr-json-file`; field evidence marks `source=external_ocr_text`.
- Image-table risk is explicitly reported when images exist, no HTML table is found, and OCR text is unavailable.
- Disease names in exemption/health notice/cannot-insure contexts are filtered out.
- Person type age ranges remain blocked by the dedicated quality tests.

## 2026-07-01 Supplemental Verification

| Check | Result |
| --- | --- |
| Focused OCR/pagination/job/frontend/disease tests | passed, 20 tests |
| `py -m unittest discover -s tests -v` | passed, 107 tests |
| `py -m pytest -q` | passed, 107 tests, 36 subtests, 1 deprecation warning |
| project `compileall` with ignored-dir excludes | passed |

Real sample verification:

- Sample: `普惠门诊保·如意版2025 保障详情`, `https://mp.weixin.qq.com/s/7meXk1OSTtr9-GTFxFX4HQ`
- No OCR run: passed; disease name, person type and interval stayed empty; collection log recorded OCR skipped and image-table risk.
- External OCR text run: passed; extracted `补助限额=100000元`, `报销比例=80%`, `备注=投保年龄：6-65周岁`; person type and disease name stayed empty; field evidence included `source=external_ocr_text`.

Real-config API smoke:

- `/api/config/status`: passed, `database_configured=true`, `safe_to_query=true`, `ocr_available=false`
- `/api/articles?limit=1&offset=0`: passed, `total=7584`
- `/api/extract` job + `/api/jobs/{job_id}` + `/api/jobs/{job_id}/preview`: passed, job success, preview headers=26, preview rows=1
