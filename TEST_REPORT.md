# DataExtractor 测试报告

## 基本信息

- 测试时间：2026-06-30 11:20:21
- 当前分支：codex/db-to-excel-extractor
- 当前 commit：08d0b4cf
- Python 版本：3.14.0 (MSC v.1944 64 bit, AMD64)
- 依赖安装情况：核心测试依赖可用，已确认 pytest 9.1.1、openpyxl、PyYAML、SQLAlchemy、beautifulsoup4、lxml、requests、openai 等已安装；当前环境未安装 paddleocr/paddlepaddle，但测试均通过 mock/fake 路径覆盖 OCR，不依赖真实 OCR。

## 执行命令

```bash
python -m unittest discover -s tests
pytest -q
C:\Users\admin\AppData\Local\Programs\Python\Python314\python.exe -m unittest discover -s tests -v
C:\Users\admin\AppData\Local\Programs\Python\Python314\python.exe -m pytest -q --junitxml logs\pytest-results.xml
C:\Users\admin\AppData\Local\Programs\Python\Python314\python.exe main.py --help
C:\Users\admin\AppData\Local\Programs\Python\Python314\python.exe main.py --input-xlsx "samples/db/新建 XLSX 工作表.xlsx" --limit 1 --mode merge --dry-run --log-dir logs/readme_dry_run
```

说明：`python` 命令在当前 Windows PATH 中指向 Microsoft Store shim，直接运行 `python -m unittest discover -s tests` 返回 9009；随后改用实际解释器路径完成测试。`pytest` 直接命令在 PowerShell 中不可识别，`python -m pytest` 可用。

## 测试统计

| 命令 | 总数 | 通过 | 失败 | 错误 | 跳过 | 结果 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| unittest discover | 58 | 58 | 0 | 0 | 0 | OK |
| pytest -q | 58 | 58 | 0 | 0 | 0 | OK |
| 主流程 dry-run | 1 条输入 | 1 | 0 | 0 | 0 | OK |

失败测试：无。

## 已覆盖功能列表

- 项目结构：核心模块、README、验收清单、开发日志、requirements、tests 目录均存在；已补齐 `config/llm_config.yml`。
- 配置加载：db config、环境变量替换、字段配置、固定 26 列顺序、字段别名、table mapping、strict-config、错误 YAML、缺字段配置。
- 数据库读取：配置化 SQL 构造、旧 db.py 兼容入口、selected_ids 优先 keyword、limit/offset/default_limit、direct_field_columns、安全字段/表名校验、参数化 keyword/selected_ids。
- 关键词与同义词：医保、报销、多关键词、空关键词、or/and SQL 组合相关路径。
- 字段映射：别名归一化、额外字段删除、缺失字段补齐、默认值、固定 26 列顺序。
- HTML 与表格规则：HTML 正文解析、图片 URL、HTML/Markdown 表格、别名表头、多行、重复去重、规则错误收集。
- 正文规则：报销比例、起付标准、补助限额、保险类型、医院类型等常见表达，规则失败不阻塞流程。
- LLM v2：v2 object、旧 array、旧单 object、非法 JSON fallback、raw output 保存、direct_fields 应用、evidence/confidence 转换。
- record_fusion：数据库直接字段、表格规则、正文规则、LLM、默认值优先级，冲突证据、人工复核、数量不一致。
- 置信度与 OCR retry：高/低置信度、无图/有图、no-llm/no-ocr、OCR 成功/失败、retry 取舍、评估日志。
- Excel 多 sheet：结果数据、采集日志、字段证据、冲突证据、抽取评估、失败记录、空数据表头、模板额外 sheet 保留、公式注入清洗。
- CLI：`--config`、`--field-config`、`--table-config`、`--llm-config`、`--keyword`、`--keyword-mode`、`--selected-ids`、`--llm-format`、`--limit`、`--offset`、`--mode`、`--input-xlsx`、`--no-ocr`、`--no-llm`、`--log-dir`、`--dry-run`、`--max-record-errors`、`--fail-fast`、`--strict-config`、`--no-excel`、`--save-intermediate`、`--debug`。
- 安全与稳定性：敏感信息脱敏、数据库 URL 脱敏、Excel 公式注入、配置错误、Excel 写入失败、单条失败记录。
- README 示例：已检查 `python main.py` 系列命令语法，`main.py --help` 可识别 README 涉及参数；本地 Excel dry-run 示例跑通。

## 未覆盖或覆盖不足功能列表

- 真实生产数据库连接未测，符合“不依赖真实生产数据库”的约束；当前通过 SQL 构造与 mock/fake 路径覆盖。
- 真实 LLM API 未调用，符合“不依赖真实 LLM API”的约束；通过 fake client 覆盖解析与调用路径。
- 真实 PaddleOCR 未调用，符合“不依赖真实 OCR”的约束；当前环境也未安装 paddleocr/paddlepaddle。
- README 中所有数据库示例未做真实执行，因为默认配置没有真实 DATABASE_URL/table，已通过 argparse/help 与配置化路径测试验证语法和参数识别。
- `--llm-config` 已可被 CLI 识别，默认配置文件存在，并已接入运行时 YAML 读取，可覆盖 LLM provider/api_key/base_url/model；测试覆盖参数解析与环境变量占位替换。

## 发现的问题清单

### P2：当前 PATH 的 `python` 命令不可用

- 复现步骤：在项目根目录运行 `python -m unittest discover -s tests`。
- 实际结果：返回 9009，PATH 中 `python.exe` 指向 Microsoft Store shim。
- 影响范围：影响按文档直接复制命令运行测试，不影响代码逻辑。
- 建议修复：本机安装 Python 时启用 PATH，或在 README 测试命令中补充 `py -m ...` / 显式解释器路径说明。
- 状态：尚未修复，属于环境问题。

### P3：`pytest` 直接命令在当前 PowerShell 中不可识别

- 复现步骤：运行 `pytest -q`。
- 实际结果：PowerShell 报 `pytest` 不是可识别命令。
- 影响范围：仅影响本机命令入口；`python -m pytest` 正常，测试通过。
- 建议修复：确保 Scripts 目录在 PATH，或 README 中补充 `python -m pytest -q`。
- 状态：尚未修复，属于环境问题。

### P2：`--llm-config` 原先未被 argparse 识别，`config/llm_config.yml` 原先不存在

- 复现步骤：运行修复前的 `python main.py --llm-config config/llm_config.yml --help` 或检查配置目录。
- 实际结果：参数不存在，配置文件不存在。
- 影响范围：影响用户指定 LLM 配置文件的兼容路径和验收项。
- 建议修复：增加 CLI 参数和默认配置文件，并读取 YAML 覆盖 LLM Settings。
- 状态：已修复；新增 `--llm-config` 参数、默认 `config/llm_config.yml`、运行时 YAML 覆盖逻辑和测试断言。

### P3：`README.md` 原先未包含 `--llm-config` 示例

- 复现步骤：搜索 README 示例命令。
- 实际结果：README 覆盖 `--llm-format`、`--field-config`、`--table-config`，未展示 `--llm-config`。
- 影响范围：文档完整性，不影响运行。
- 建议修复：在 LLM 配置段补充 `python main.py --llm-config config/llm_config.yml --limit 5 --mode merge`。
- 状态：已修复。

## 已修复的问题

- 增加 `config.py` 中 `--llm-config` CLI 参数，默认值为 `config/llm_config.yml`。
- 增加 `config.py` 中 LLM YAML 读取逻辑，支持 `${LLM_API_KEY}` 等环境变量占位并覆盖 provider/api_key/base_url/model。
- 在 `main.py` 接入 `apply_llm_config`，配置错误时以 `llm_config` phase 写入失败日志并返回非 0。
- 新增 `config/llm_config.yml`，使用 `${LLM_PROVIDER}`、`${LLM_API_KEY}`、`${LLM_BASE_URL}`、`${LLM_MODEL}` 占位，避免写入真实密钥。
- 更新 `tests/test_configured_db_and_fields.py`，覆盖 `--llm-config` 参数解析和运行时配置覆盖。
- 更新 `README.md`，补充 `--llm-config` 示例。

## 尚未修复的问题

- 环境 PATH 中 `python`/`pytest` 直接命令不可用。

## 最终结论

可以合并。

当前无 P0/P1 阻塞问题，核心 12 阶段功能路径、异常路径和兼容路径已通过现有测试与补充测试验证；仅剩本机 PATH 中 `python`/`pytest` 直接命令不可用的环境问题。

## 最终确认补充记录

- 确认时间：2026-06-30 13:20:18
- 当前 commit hash：08d0b4cf
- `TEST_REPORT.md` 中关于 `--llm-config` 的矛盾表述已修正：当前结论为 CLI 可识别、默认配置存在、运行时已读取 YAML 并覆盖 LLM provider/api_key/base_url/model。
- git 状态：以下修复文件尚未提交：
  - `README.md`
  - `config.py`
  - `main.py`
  - `tests/test_configured_db_and_fields.py`
  - `TEST_REPORT.md`
  - `config/llm_config.yml`
- 最终非 dry-run input-xlsx 测试命令：

```bash
C:\Users\admin\AppData\Local\Programs\Python\Python314\python.exe -c "import sys,json; from unittest.mock import patch; import main; payload=json.dumps({'records':[{'Type':'fake'}],'evidence':{},'confidence':{},'need_manual_review':False,'review_reason':''}); FakeLLM=type('FakeLLM',(),{'__init__':lambda self,settings:None,'extract':lambda self,prompt:payload}); sys.argv=['main.py','--input-xlsx','samples/db/新建 XLSX 工作表.xlsx','--limit','1','--mode','merge','--no-ocr','--output-dir','outputs/final_e2e','--log-dir','logs/final_e2e']; p=patch('main.LLMClient', FakeLLM); p.start(); rc=main.main(); p.stop(); raise SystemExit(rc)"
```

- 最终非 dry-run input-xlsx 测试结果：通过，退出码 0，使用 fake LLM，未调用真实外部 LLM/OCR，实际生成 Excel。
- 输出 Excel 路径：`C:\Users\admin\Documents\DataExtractor\outputs\final_e2e\商业补充保险抽取结果_20260630_132017.xlsx`
- Excel sheet 验证命令：

```bash
C:\Users\admin\AppData\Local\Programs\Python\Python314\python.exe -c "from openpyxl import load_workbook; p=r'C:\Users\admin\Documents\DataExtractor\outputs\final_e2e\商业补充保险抽取结果_20260630_132017.xlsx'; wb=load_workbook(p, read_only=True); required=['结果数据','采集日志','字段证据','冲突证据','抽取评估','失败记录']; print(wb.sheetnames); missing=[s for s in required if s not in wb.sheetnames]; raise SystemExit(1 if missing else 0)"
```

- Excel sheet 验证结果：通过，包含且仅包含本次要求确认的 6 个 sheet：`结果数据`、`采集日志`、`字段证据`、`冲突证据`、`抽取评估`、`失败记录`。

## 2026-07-01 Web 前端/API 错误处理修复测试补充

### 修复范围

- API 统一 JSON 错误响应，覆盖未捕获异常、`HTTPException`、数据库未配置和抽取失败。
- `/api/config/status` 增加 `safe_to_query`、`database_status_reason`、`config_path`，并保持敏感信息脱敏。
- 前端 `fetchJson()` 支持非 JSON 响应，不再出现 `Unexpected token 'I'... is not valid JSON`。
- 前端数据库字段渲染改为 DOM API 和 `textContent`，避免 XSS；来源链接仅允许 `http://` / `https://`。
- 图片入库默认保护测试表，非测试表必须显式 `--force-production-table`。
- 综合验收脚本支持 `--image`、`--manual-excel`、`--image-import-table`，没有本地样本时跳过 image import。
- 中文 Excel 文件名下载 URL 已做百分号编码。

### 自动化验证

```powershell
py -m unittest discover -s tests -v
py -m pytest -q
py -m compileall -x "(^|[\\/])(\.git|\.pytest_cache|\.venv|\.venv_ocr|__pycache__|logs|outputs|temp_images|db_to_excel_extractor|tmp_ai_debug)([\\/]|$)" .
```

结果：

- `unittest`：90 tests OK。
- `pytest`：90 passed，33 subtests passed，1 个 FastAPI/Starlette deprecation warning。
- `compileall`：通过，退出码 0。

### 手动 API 验证

真实配置启动：

```powershell
py api_server.py --host 127.0.0.1 --port 8000 --config logs/real_db_20/db_config.runtime.yml --field-config config/field_mapping.yml --llm-config config/llm_config.yml
```

验证结果：

- `/api/health` 返回 `{"ok": true}`。
- `/api/config/status` 返回 `database_configured=true`、`safe_to_query=true`、`config_path=logs/real_db_20/db_config.runtime.yml`。
- `/api/articles?limit=1&offset=0` 返回 1 条记录。
- `/api/extract` 使用 1 条记录、`no_ocr=true`、`no_llm=true` 生成成功。
- 返回的 `download_url` 为 URL 编码路径，例如 `/api/download/%E5%95%86...xlsx`。
- `/api/download/...` 下载成功，下载后的 Excel 包含 6 个 sheet。

错误配置启动在 8010 端口时：

- `/api/config/status` 返回 `database_configured=false`、`safe_to_query=false`、`database_status_reason=source.table 不能为空`。
- `/api/articles?limit=1` 返回 `400 application/json`：

```json
{"detail":"数据库未配置，无法查询文章。请使用 --config 指定可用 db_config.yml：source.table 不能为空","error_type":"DatabaseNotConfigured"}
```

## 病种名称质量修复补充记录

- 确认时间：2026-06-30 15:16:22
- 当前修复范围：正文规则 `病种名称` 清洗、融合阶段病种特殊择优、LLM v2 prompt 约束、字段/表格病种名称别名、UTF-8 BOM `.env` 读取。
- 新增测试文件：`tests/test_disease_name_quality.py`。
- 自动化测试：
  - `python -m unittest discover -s tests`：本机 `python` 命令不可用，改用 `py`。
  - `py -m unittest discover -s tests -v`：69 个测试通过。
  - `py -m pytest -q`：69 passed，30 subtests passed。
  - `py -m compileall ...`：通过。
- 真实 smoke：3 条真实数据通过，输出 `outputs/real_db_20/disease_fix_smoke/商业补充保险抽取结果_20260630_150917.xlsx`。
- 真实 20 条：通过，输出 `outputs/real_db_20/disease_fix_20/商业补充保险抽取结果_20260630_151622.xlsx`；结果数据 27 行，`病种名称` 非空 12 行。
- 病种名称检查：附件列出的错误长句、`大病/既往症/慢性病/特殊病` 泛化词，以及本轮观察到的国家/参保/高价自费类坏片段均无命中。
- 安全检查要求：`logs/`、`outputs/`、`.env` 均不提交；`config/llm_config.yml` 保持环境变量占位，不写真实 key。

## 2026-07-01 OCR、分页和结果页修复补充

### 修复范围

- `/api/config/status` 增加 `ocr_available`、`ocr_status_reason`、`ocr_engine`，并继续脱敏。
- `/api/articles` 返回真实分页字段：`total`、`limit`、`offset`、`page`、`page_size`、`total_pages`、`has_next`、`has_prev`。
- `/api/extract` 改为 job 模式，返回 `job_id`、`status_url`、`result_page`。
- 新增 `/api/jobs/{job_id}` 和 `/api/jobs/{job_id}/preview`，preview 只返回 `结果数据` sheet 前 100 行。
- 前端新增分页 UI、跨页选择、清空已选择、生成后跳转结果页和结果页 Excel 预览。
- CLI 新增 `--ocr-text-file`、`--ocr-json-file` 外部 OCR fallback，字段证据标记 `source=external_ocr_text`。
- 图片表格未识别风险会写入抽取评估和采集日志相关字段。
- 免责/健康告知/不能投保/除外责任中的疾病不会进入 `病种名称`。
- `6-65周岁`、`18-70岁`、`出生满30天-65周岁` 不会进入 `人员类型`。

### 新增/更新测试

- `tests/test_api_server.py`：分页、job、preview、下载、非法/未完成 job JSON 错误。
- `tests/test_web_app_static.py`：分页状态、结果页文件、preview API 调用和安全 DOM 渲染。
- `tests/test_ocr_status_and_image_risk.py`：OCR 状态、图片表格风险、外部 OCR 文本进入 prompt 和字段证据。
- `tests/test_person_type_quality.py`：人员类型年龄范围清洗。
- `tests/test_disease_name_quality.py`：免责上下文疾病过滤。

### 自动化验证

- `py -m unittest tests.test_api_server tests.test_web_app_static tests.test_ocr_status_and_image_risk tests.test_person_type_quality tests.test_disease_name_quality.DiseaseNameRuleTests.test_exemption_context_diseases_are_not_treated_as_covered_diseases -v`：20 tests OK。
- `py -m unittest discover -s tests -v`：107 tests OK。
- `py -m pytest -q`：107 passed，36 subtests passed，1 个 FastAPI/Starlette deprecation warning。
- `py -m compileall -q -x "..." .`：通过，退出码 0。

### 真实样本复测

- 样本：`普惠门诊保·如意版2025 保障详情`，`https://mp.weixin.qq.com/s/7meXk1OSTtr9-GTFxFX4HQ`。
- 无 OCR 运行：生成成功；`病种名称`、`人员类型`、`区间` 均为空；采集日志 `ocr_triggered=true`、`ocr_skipped_reason=用户选择跳过 OCR`，并写入图片表格未识别风险。
- 外部 OCR 文本运行：生成成功；`补助限额=100000元`、`报销比例=80%`、`备注=投保年龄：6-65周岁`；`人员类型` 和 `病种名称` 为空；字段证据包含 `source=external_ocr_text`。

### 真实配置 API smoke

- 启动：`py api_server.py --host 127.0.0.1 --port 8012 --config logs/real_db_20/db_config.runtime.yml --field-config config/field_mapping.yml --llm-config config/llm_config.yml`。
- 验证：`/api/config/status`、`/api/articles?limit=1&offset=0`、`/api/extract` job、`/api/jobs/{job_id}`、`/api/jobs/{job_id}/preview`。
- 结果：通过；`database_configured=true`、`safe_to_query=true`、`ocr_available=false`、`total=7584`、job success、preview headers=26、preview rows=1。
