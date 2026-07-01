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
