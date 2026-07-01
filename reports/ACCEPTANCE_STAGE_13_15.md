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

## 2026-07-01 Supplemental Frontend Pagination Cache Acceptance

- Overall status: passed.
- P0/P1: none found.
- Fixed stale browser script execution by versioning `/web/app.js` and `/web/result.js`.
- Fixed frontend pagination normalization so visible rows cannot coexist with `total=0` and `第 0 / 0 页`.
- Fixed API pagination payload consistency for provider responses that include items but return zero total.
- Fixed OCR default behavior: available OCR means do not skip OCR; unavailable OCR remains checked/disabled with an explicit warning.
- Fixed clear selection across pages.
- Guarded result-page download button DOM writes.

## 2026-07-01 Supplemental Verification

| Check | Result |
| --- | --- |
| Focused red/green regression | passed |
| `py -m unittest tests.test_api_server tests.test_web_app_static tests.test_configured_db_and_fields -v` | passed, 38 tests |
| `py -m unittest discover -s tests -v` | passed, 111 tests |
| `py -m pytest -q` | passed, 111 tests, 36 subtests, 1 deprecation warning |
| project `compileall` with ignored-dir excludes | passed |
| AI generated data | passed |
| real DB 20 | passed, result rows 24, fixed 26 headers, 6 sheets |
| frontend browser flow | passed, search/pagination/clear selection/job result/download |

Frontend browser flow details:

- Initial page: `total=7584`, `第 1 / 380 页`, script `/web/app.js?v=20260701_web_fix`.
- Page size 10 + next page: `第 2 / 759 页`, 10 rows.
- Search keyword `医保`: `total=5445`, page reset to 1.
- Selection: selected 5 rows, request used `no_ocr=true`, `no_llm=false`.
- Job result: `job_6a90ee563171`, success, preview headers=26, preview rows=5, download visible.
- Downloaded workbook: 6 sheets, `结果数据` fixed 26 headers.

## 2026-07-01 Supplemental Persistent Job OCR Acceptance

- Overall status: passed.
- P0/P1: none found.
- `/api/config/status` includes `ocr_install_hint`; missing `paddleocr` and missing `paddlepaddle/paddle` are reported separately.
- `/api/articles` regression confirms total is the full filtered count, not the current page length.
- `/api/extract` returns a real `job_YYYYMMDD_HHMMSS_xxxxxxxx` and result page URL; Excel file names are not accepted as job ids.
- Job metadata is persisted to `outputs/web/jobs/<job_id>.json` and does not expose local absolute paths.
- `/api/jobs/{job_id}` and `/api/jobs/{job_id}/preview` work after API restart for completed jobs.
- Result page 404 now displays “任务不存在或已过期，请返回列表重新生成。” instead of raw `Not Found`.
- Real DB browser flow showed `total=7584`, `第 1 / 380 页`, job `job_20260701_114243_49763acb`, 26 preview headers, 1 preview row and a downloadable 6-sheet workbook.

| Check | Result |
| --- | --- |
| focused persistent job regressions | passed, 2 tests |
| focused OCR/result page regressions | passed, 2 tests |
| focused API/OCR/static/config regression | passed, 44 tests |
| `py -m unittest discover -s tests -v` | passed, 114 tests |
| `py -m pytest -q` | passed, 114 tests, 36 subtests, 1 deprecation warning |
| project `compileall` with ignored-dir excludes | passed |
| AI generated data | passed |
| real DB 20 | passed, `reports/web_fix_persistent_job_20260701_113409` |
| frontend browser restart flow | passed |

## 2026-07-01 Supplemental Stale Web Job Flow OCR Acceptance

- Overall status: passed.
- P0/P1: none found.
- Root cause confirmed: port 8000 was still served by an old 09:33 Python process. It lacked `/api/version` and served old JS that could fall back to constructing result URLs from `payload.job_id`.
- Added `/api/version` with `project_root`, `cwd`, `git_commit`, `web_app_version=20260701_job_fix`, and feature flags.
- Startup now prints cwd, project_root, git_commit, config paths and web_app_version.
- Frontend JS cache version is now `20260701_job_fix`.
- List page no longer constructs `result.html?job_id=...`; it requires API `result_page`.
- Result page rejects non-`job_` ids before calling the backend.
- OCR environment configured in `.venv_ocr` with Python 3.11.9; `get_ocr_status()` returns available.

| Check | Result |
| --- | --- |
| `/api/version` regression | passed |
| stale frontend job flow regression | passed |
| OCR environment import/status | passed |
| issue sample OCR-capable run | passed |
| issue sample external OCR fallback | passed |
| frontend real DB flow | passed, `job_20260701_132800_b4b70145` |
| service restart job preview | passed |
| real DB random 20 | passed, `reports/web_fix_persistent_job_20260701_133010` |
| `py -m unittest discover -s tests -v` | passed, 115 tests |
| `py -m pytest -q` | passed, 115 tests, 36 subtests, 1 warning |
| project `compileall` with ignored-dir excludes | passed |
| AI generated data | passed |

Observed frontend state:

- `/api/version`: `20260701_job_fix`.
- `/api/config/status`: `ocr_available=true`, `ocr_engine=paddleocr`.
- Home page: `total=7584`, `第 1 / 380 页`, JS `/web/app.js?v=20260701_job_fix`.
- Result page: success, preview headers=26, preview rows=1, downloadable 6-sheet workbook.

## 2026-07-01 Supplemental Image Table Acceptance

- Overall status: passed.
- P0/P1: none found.
- Added optional OpenAI-compatible vision extraction path and environment-driven `VISION_LLM_*` config.
- External OCR text now has highest priority for image-table articles and can deterministically split the sample into 10 benefit rows.
- PaddleOCR failures now preserve per-image diagnostics for URL, download status, image format, OCR init state and exception message.
- Frontend list page can send pasted external OCR text through `/api/extract`.

| Check | Result |
| --- | --- |
| focused vision/image table/OCR fallback regression | passed, 17 tests |
| `.venv_ocr\Scripts\python.exe -m unittest discover -s tests -v` | passed, 123 tests |
| `py -m pytest -q` | passed, 123 tests, 36 subtests, 1 warning |
| compileall and AI generated data | passed |
| real sample with company LLM env and external OCR text | passed, 10 rows |
| field evidence source | contains `external_ocr_text` |

Final real sample output:

- Workbook: `outputs/real_db_20/image_table_external_20260701_1429/商业补充保险抽取结果_20260701_142756.xlsx`.
- Collection log: `image_count=2`, `external_ocr_used=true`, `vision_enabled=true`, `vision_triggered=false`, `ocr_triggered=false`, `output_rows=10`.
- Key rows: `意外门诊急诊费用补偿` has `100000元`, `免赔额100元`, `80%`; `在线问诊药品费用医疗保险金` has `10000元`, `70%`.
- Public fields: `湖南省`, `中国大陆籍人士`, `普惠门诊保·如意版2025`; disease name remains empty and age range stays in notes.
