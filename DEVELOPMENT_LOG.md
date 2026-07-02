# DataExtractor Development Log

## 2026-07-02

### A1 main.py pipeline boundary

- Cleaned `main.py` pipeline imports to the CLI/API public interfaces: `create_empty_metadata` and `extract_record_rows`.
- Kept local compatibility alias `_empty_metadata = create_empty_metadata`.
- Added import-boundary lint coverage and updated stale tests to import pipeline internals from `pipeline`.
- Verification: `py -m pytest tests/test_import_lint_boundaries.py -q`; affected pytest subset passed.

## 2026-06-30

### 本轮目标

完成阶段 1-3 改造：

- 配置化数据库读取。
- 关键词和同义词检索。
- 字段配置文件和固定 26 列输出标准化。

### 已完成

- 新增 `config_loader.py`，支持 YAML 配置、`${DATABASE_URL}` 环境变量替换、缺省配置和清晰配置错误。
- 新增 `config/db_config.yml`，作为配置化数据库读取样例；默认未填写表名时保留旧 `.env + db.py` 流程。
- 新增 `db_reader.py`，支持配置字段读取、`limit`、`offset`、`selected_ids`、关键词检索、字段/表名合法性校验和参数化 SQL。
- 新增 `keyword_utils.py`，封装医保、报销、门诊、病种、起付标准、补助限额等同义词扩展。
- 新增 `field_mapping.py` 和 `config/field_mapping.yml`，支持固定 26 列校验、默认值、字段别名映射、删除多余字段和补齐缺失字段。
- `main.py` 新增 `--config`、`--field-config`、`--keyword`、`--keyword-mode`、`--selected-ids` 参数。
- `main.py` 保持 `--input-xlsx` 最高优先级；`--selected-ids` 高于 `--keyword`。
- `json_utils.py` 在 LLM JSON 解析后接入字段标准化，并应用数据库 `_direct_fields`。
- `excel_writer.py` 写入前再次按固定 26 列标准化。
- `prompts.py` 优先使用字段配置中的固定表头，并提示 LLM 不输出多余字段。
- `requirements.txt` 增加 `PyYAML`、`SQLAlchemy`。
- `README.md` 增加数据库配置、关键词检索、字段配置、固定 26 列和兼容回退说明。
- 新增 `tests/test_configured_db_and_fields.py`，覆盖配置加载、关键词扩展、查询构造、字段标准化、CLI 参数和 JSON 别名映射。

### 已验证

- `py -m unittest discover -s tests -v`

### 注意事项

- 本机 `python` 命令指向 Windows Store 占位程序，验证使用 `py`。
- 默认 `config/db_config.yml` 不会强制启用配置化读取；需要填写 `DATABASE_URL` 和 `source.table` 后才会使用 `db_reader.py`。

## 2026-06-30 续

### 本轮目标

修补阶段 1-3 遗留问题，并完成阶段 4-6：

- 表格规则抽取。
- 正文键值规则抽取。
- LLM v2 JSON object 输出格式。

### 已完成

- 修复 `query.default_limit` 未生效问题：配置化数据库读取时，未显式传 `--limit` 会使用 `db_config.yml` 的 `query.default_limit`。
- 新增 `field_mapping.apply_direct_fields`，确保 `_direct_fields` 在 LLM 正常返回、空数组、JSON 解析失败 fallback 和后续规则结果中都稳定覆盖固定 26 列。
- 旧 `db.py` 模式下传 `--keyword` 时改为清晰报错，不再静默忽略。
- 新增 `extraction_types.py`，提供 `RuleExtractionResult` 公共结构。
- 新增 `table_extractor.py` 和 `config/table_mapping.yml`，支持 HTML table、Markdown table、简单类表格文本、表头别名映射、未映射列写入备注，以及字段证据生成。
- 新增 `rule_extractor.py`，支持正文键值规则抽取，包括报销比例、起付标准、补助限额、保险类型、人员类型、医院类型、类型、标化类型等。
- 新增 `prompts_v2.py`，默认要求 LLM 返回 JSON object，并把规则抽取结果和字段证据作为参考传给 LLM。
- 新增 `llm_extractor.py`，支持 v2 object、旧版 JSON array、旧版单 record object，解析失败时保存原始输出并返回 fallback。
- `main.py` 接入表格规则抽取、正文规则抽取、字段证据日志、LLM v2 默认路径和 `--llm-format v2|legacy`。
- README 补充 `query.default_limit` 优先级、direct fields fallback、规则抽取、字段证据日志、LLM v2 格式和 CLI 示例。
- 新增 `tests/test_rule_extractors.py`、`tests/test_llm_v2.py`，并扩展 `tests/test_configured_db_and_fields.py`。

### 已验证

- `py -m unittest -v tests.test_configured_db_and_fields`
- `py -m unittest -v tests.test_rule_extractors`
- `py -m unittest -v tests.test_llm_v2`
- `py -m unittest -v tests.test_configured_db_and_fields tests.test_rule_extractors tests.test_llm_v2 tests.test_confidence_retry`
- `py -m unittest discover -s tests -v`
- `py -m compileall main.py config.py config_loader.py db.py db_reader.py keyword_utils.py field_mapping.py json_utils.py excel_writer.py prompts.py prompts_v2.py llm_extractor.py table_extractor.py rule_extractor.py extraction_types.py input_xlsx.py utils.py tests`
- `py main.py --help`

## 2026-06-30 续 2

### 本轮目标

修补阶段 4-6 遗留问题，并完成阶段 7-9：

- 规则结果与 LLM 结果融合。
- OCR retry 接入融合结果评估和二次融合。
- Excel 输出增强为多 sheet 可追溯 workbook。

### 已完成

- `table_extractor.py` 和 `rule_extractor.py` 支持传入当前 `FieldMapping`，不再忽略 `--field-config`。
- 表格抽取增加按主要字段组合去重，避免 HTML table 与其 Markdown 转写重复生成规则记录。
- `llm_extractor.py` 新增 `llm_result_to_field_evidence`，把 LLM v2 evidence/confidence 转成统一字段证据。
- `extraction_types.py` 新增 `FusionResult`。
- 新增 `record_fusion.py`，实现融合优先级：数据库直接字段 > 表格规则 > 正文规则 > LLM > 默认值。
- 融合支持多行记录、顺序对齐、LLM 追加行、冲突证据、`need_manual_review` 和 `review_reason`。
- `main.py` 改为输出融合后的 rows；OCR retry 基于融合结果评估，OCR 后重新调用 LLM、重新融合、重新评估。
- `main.py` 收集 `collection_logs`、`field_evidence`、`conflict_evidence`、`extract_evaluations`、`failed_records`。
- `excel_writer.py` 新增 `write_extraction_workbook`，输出 `结果数据`、`采集日志`、`字段证据`、`冲突证据`、`抽取评估`、`失败记录` 多 sheet。
- 新增 CLI：`--table-config`、`--no-llm`。
- `--no-llm` 下跳过 LLM 调用和 OCR retry，仅使用直接字段、规则结果和默认值。
- README 补充融合优先级、冲突证据、OCR 融合、多 sheet 输出、`--table-config` 和 `--no-llm` 示例。
- 新增 `tests/test_record_fusion.py`、`tests/test_excel_multisheet.py`、`tests/test_no_llm_flow.py`，并扩展规则和 LLM v2 测试。

### 已验证

- `py -m unittest discover -s tests -v`

## 2026-06-30 续 3

### 本轮目标

继续修补阶段 1-9 的遗留问题，并完成阶段 10-12：

- 补齐采集日志、OCR retry 选择、冲突证据兼容字段和模板 sheet 保留。
- 增加 CLI 运行控制参数。
- 增强稳定性、安全脱敏和 Excel 写入防护。
- 补充 README 与验收清单。

### 已完成

- `config.py` 新增 `--log-dir`、`--dry-run`、`--max-record-errors`、`--fail-fast`、`--strict-config`、`--no-excel`、`--save-intermediate`。
- `main.py` 新增运行时 flag 归一化：`--dry-run` 会跳过 LLM、OCR retry 和 Excel；`--no-llm` 会同步跳过 OCR retry。
- `main.py` 增加 `input_mode` 采集日志字段，覆盖 `input-xlsx`、`configured-db`、`legacy-db`，失败记录也会保留该字段。
- OCR retry 改为比较首轮与重试置信度，记录 `initial_confidence_score`、`ocr_retry_confidence_score`、`ocr_improved`、`final_attempt`，重试明显变差时保留首轮结果。
- `--no-llm` 下不初始化 LLM，不触发 OCR retry，采集日志记录 `llm_format=none`、`ocr_triggered=false`，人工复核原因标注跳过 LLM/OCR。
- `record_fusion.py` 的冲突证据保留旧字段，并新增 `source_a`、`value_a`、`source_b`、`value_b`、`chosen_source`、`chosen_value`、`reason`。
- `excel_writer.py` 只替换目标 sheet，保留模板中的其他 sheet；写入前会清理控制字符、限制长度并转义公式型文本。
- 新增 `security_utils.py`，提供数据库 URL、敏感文本和 Excel 单元格安全清洗工具。
- `table_extractor.py` 对 YAML 解析错误给出清晰 `TableMappingError`，并将置信度裁剪到 `0..1`。
- `main.py` 对输入读取、单条处理和 Excel 写入错误做敏感信息脱敏；single 与 merge Excel 写入失败都会返回非 0。
- 新增 `ACCEPTANCE_CHECKLIST.md`，记录阶段 10-12 的验收点。
- README 补充运行控制参数、日志目录、模板保留、Excel 安全清洗、OCR retry 选择和冲突证据通用字段说明。
- 新增/扩展测试：`tests/test_cli_runtime_modes.py`、`tests/test_stability_and_security.py`、`tests/test_confidence_retry.py`、`tests/test_no_llm_flow.py`、`tests/test_record_fusion.py`、`tests/test_excel_multisheet.py`。

### 已验证

- `py -m unittest discover -s tests -v`
- `py -m unittest -v tests.test_cli_runtime_modes tests.test_confidence_retry`

### 注意事项

- 本机继续使用 `py` 运行测试和脚本。
- 推送仍需用 Python `dulwich`，避免 Git for Windows HTTPS helper 问题。

## 2026-06-30 续 4

### 本轮目标

修复真实数据测试发现的 P0/P1 问题：`病种名称` 被正文规则和融合优先级错误放大为长句或泛化描述。

### 已完成

- 保留 TRAE 本地改动并继续在其基础上修改：`--llm-config`、中文表名/字段名校验、真实测试报告和临时 LLM 配置模板均未回滚。
- 确认本地 ignored `.env` 使用用户指定的 DeepSeek key；新增根目录 ignored `.env` 供当前根目录代码读取，真实 key 不提交。
- 修复 `.env` UTF-8 BOM 导致 `DATABASE_URL` 读取为空的问题：`config.py` 与 `config_loader.py` 加载 dotenv 时使用 `utf-8-sig` 并关闭 dotenv 插值。
- `rule_extractor.py` 新增 `normalize_disease_name`、`is_valid_disease_name`，收紧 `病种名称` 正文规则，只从强上下文或明确核心疾病词抽取。
- 过滤宣传语、费用说明、人物/地名/时间长句、国家/机构/分类片段，以及 `大病`、`既往症`、`慢性病`、`特殊病` 等泛化词。
- `record_fusion.py` 对 `病种名称` 增加特殊融合：正文规则长句 vs LLM 核心疾病名时采用 LLM；双方均不可信时清空并人工复核；冲突证据记录 `source_a/value_a/source_b/value_b/chosen_source/chosen_value/reason`。
- `field_mapping.py` 和 `config/field_mapping.yml` 增加病种名称别名：`疾病名称`、`特定病种`、`保障病种`、`纳入病种`、`病种范围`。
- `prompts_v2.py` 增强病种名称约束和正反例，要求 LLM 不把宣传语、费用场景或泛化类别写入病种名称。
- 新增 `tests/test_disease_name_quality.py`，覆盖规则清洗、无效泛化词、融合择优、表格明确病种表头和 prompt 约束。
- `REAL_DB_20_TEST_REPORT.md` 追加病种名称质量问题修复记录与最终 3 条 smoke / 20 条真实数据验证结果。

### 已验证

- `python -m unittest discover -s tests`：本机命令不可用，按任务说明改用 `py`。
- `py -m unittest discover -s tests -v`：69 个测试通过。
- `py -m pytest -q`：69 passed，30 subtests passed。
- `py -m compileall main.py config.py config_loader.py db.py db_reader.py keyword_utils.py field_mapping.py json_utils.py excel_writer.py prompts.py prompts_v2.py llm_extractor.py table_extractor.py rule_extractor.py record_fusion.py extraction_types.py input_xlsx.py utils.py security_utils.py tests`：通过。
- 3 条真实 smoke：通过，生成 `outputs/real_db_20/disease_fix_smoke/商业补充保险抽取结果_20260630_150917.xlsx`，`病种名称` 无已知错误长句和泛化词。
- 20 条真实数据：通过，生成 `outputs/real_db_20/disease_fix_20/商业补充保险抽取结果_20260630_151622.xlsx`，结果数据 27 行，`病种名称` 无已知错误长句、泛化词和本轮观察到的国家/参保/高价自费类坏片段。

### 注意事项

- 真实数据运行使用 `--no-ocr`，因为当前环境仍未安装 PaddleOCR/paddlepaddle。
- `logs/`、`outputs/`、根目录 `.env` 和旧目录 `.env` 均为 ignored，本轮不提交真实数据库连接串、真实 LLM key 或真实输出 Excel。

## 2026-06-30 续 5

### 本轮目标

继续完成阶段 13-15：质量评估、AI 生成数据回归、图片数据入库和人工 Excel 对比、Web API/前端页面、综合验收脚本，并按用户要求把生成的测试结果写入桌面新目录。

### 已完成

- 扩展 `rule_extractor.py` 的病种识别核心词，新增 `类风湿性关节炎`、`慢性阻塞性肺疾病`、`尿毒症`、`心力衰竭`、`系统性红斑狼疮` 等常见病种/后缀识别，同时保留泛化词过滤。
- 新增 `quality_metrics.py` 与 `excel_compare.py`，支持固定 26 列对比、空值/百分号/金额归一、模糊匹配、整体相似度、核心字段相似度、字段指标、行匹配和差异明细报告。
- 新增 `samples/ai_generated/` 与 `tests/test_ai_generated_cases.py`，使用 fake LLM 完成稳定回归，不调用真实 LLM。
- 新增 `image_data_loader.py` 与 `scripts/import_image_data_to_db.py`，支持图片 OCR 路径和 JSON/CSV/XLSX 手工转录 fallback，入库使用 SQLAlchemy 参数化 SQL、事务、测试表和 batch 标记。
- 新增 `scripts/run_image_import_test.py`，完成图片样本/人工 Excel fallback、写入数据库测试表、从数据库重新读取、生成 Excel、与人工 Excel 对比的端到端验收。
- 新增 `api_server.py`、`app.py`、`web/index.html`、`web/app.js`、`web/style.css`，提供本机 Web 页面、文章查询、勾选生成 Excel 和下载接口。
- 新增 `scripts/run_real_db_smoke.py`、`scripts/run_real_db_20.py`、`scripts/run_real_db_compare.py`、`scripts/run_acceptance_all.py`，综合验收默认可写入桌面结果目录。
- 修复 `table_extractor.py` 表格去重键过粗的问题，保留仅 `区间` 等核心字段不同的待遇行，同时继续合并 HTML/markdown 的重复表格行。
- 更新 `.gitignore`，忽略 `samples/` 下图片原件，避免误提交真实图片样本。
- README 与验收清单补充阶段 13-15 使用说明和安全注意事项。

### 已验证

- 桌面结果目录：`C:\Users\admin\Desktop\DataExtractor_test_results_20260630_165827`。
- `py -m unittest discover -s tests -v`：78 个测试通过。
- `py -m pytest -q`：78 passed，30 subtests passed。
- `py -m compileall -x <ignored_dirs> .`：通过；原始 `py -m compileall .` 会递归 ignored 旧目录 `db_to_excel_extractor\.venv` 的第三方包，因此综合验收排除了 `.git/.venv/.venv_ocr/logs/outputs/temp_images/db_to_excel_extractor/tmp_ai_debug`。
- AI 生成数据测试：通过，满足 `overall_similarity >= 0.85`、`core_field_similarity >= 0.90`。
- 真实数据库 3 条 smoke：通过，结果 3 行，6 个 sheet，固定 26 列，无已知病种错误长句。
- 真实数据库 20 条：通过，结果 50 行，`病种名称` 非空 22 行，无已知病种错误长句或泛化词。
- 图片导入测试：通过，图片/人工 Excel fallback 解析 1 条文章记录，写入数据库测试表，从数据库读回生成 104 行 Excel。
- 图片导入对比：`overall_similarity=0.961538`，`core_field_similarity=1.0`。
- 前端 API 测试：通过，覆盖 health、config status、articles、extract、download、路径穿越拒绝、空选择和超限选择。

### 注意事项

- 详细测试产物、真实输出 Excel、图片导入中间 JSON 和对比报告均写到桌面结果目录，不提交到 GitHub。
- 仓库报告只保留脱敏汇总，不包含真实数据库密码、真实 API Key、真实图片原件或人工 Excel。

## 2026-07-01 续 6

### 本轮目标

修复 Web 前端实际使用时出现的 `Unexpected token 'I', "Internal S"... is not valid JSON`，并增强 API 错误 JSON 化、前端安全渲染、图片入库测试表保护和综合验收脚本参数化。

### 已完成

- `api_server.py` 增加统一 JSON 错误处理：`ApiError`、`HTTPException` 和未捕获 `Exception` 均返回 JSON，不再返回裸文本 `Internal Server Error`。
- `/api/config/status` 增加 `config_path`、`database_status_reason`、`safe_to_query`，不返回数据库 URL、密码、API Key 或 token。
- `/api/articles` 在默认数据库配置不可用时提前返回 400 JSON，错误类型为 `DatabaseNotConfigured`。
- `/api/extract` 对空选择、超过 50 条、非法 mode、配置错误和 runner 异常返回 JSON；错误内容经过脱敏。
- `/api/extract` 返回的 `download_url` 对中文 Excel 文件名做 URL 编码，修复中文文件名下载失败。
- `web/app.js` 修复 `fetchJson()`：先检查 `content-type`，非 JSON 响应包装为友好错误，不再抛 JSON parse 错误。
- `web/app.js` 移除数据库字段渲染中的 `innerHTML`，改用 `document.createElement()` 和 `textContent`；来源链接仅允许 `http://` / `https://`。
- 数据库 `safe_to_query=false` 时，前端禁用搜索、全选和生成 Excel，保留刷新按钮并显示空状态。
- `scripts/import_image_data_to_db.py` 默认只允许写测试表：`image_import_articles`、`test_*`、`*_test`；非测试表必须传 `--force-production-table`。
- `scripts/run_acceptance_all.py` 增加 `--image`、`--manual-excel`、`--image-import-table`；未提供图片和人工 Excel 时跳过 image import 并写明原因。
- `scripts/run_image_import_test.py` 增加 `--manual-excel` 别名和 `--force-production-table`。
- 新增/更新测试：API JSON 错误、配置状态脱敏、前端静态安全检查、图片入库表保护、验收脚本参数解析、中文下载 URL 编码。
- 更新 `README.md`、`TEST_REPORT.md`、`reports/ACCEPTANCE_STAGE_13_15.md` 和 `reports/acceptance_stage_13_15.json`。

### 已验证

- `py -m unittest discover -s tests -v`：90 tests OK。
- `py -m pytest -q`：90 passed，33 subtests passed，1 个 FastAPI/Starlette deprecation warning。
- `py -m compileall -x "..." .`：通过，退出码 0。
- 手动启动真实运行配置：`py api_server.py --host 127.0.0.1 --port 8000 --config logs/real_db_20/db_config.runtime.yml --field-config config/field_mapping.yml --llm-config config/llm_config.yml`。
- 手动接口验证：`/api/config/status` 显示 `safe_to_query=true`，`/api/articles?limit=1` 返回 1 条，`/api/extract` 使用 `no_llm=true/no_ocr=true` 生成 Excel 成功，编码后的 `/api/download/...` 可下载，下载文件包含 6 个 sheet。
- 错误配置验证：默认 `config/db_config.yml` 启动在 8010 端口时，`safe_to_query=false`，`/api/articles` 返回 400 JSON：`error_type=DatabaseNotConfigured`。

### 注意事项

- 本轮生成的 `outputs/web/manual_api_download_check.xlsx`、API 运行日志和真实输出 Excel 均在 ignored 目录内，不提交。
- 未跟踪的 `Q57D2088.tmp` 在本轮开始前已存在，未纳入提交。

## 2026-07-01 续 7

### 本轮目标

修正“区间”字段语义：`区间` 只表示报销金额区间、费用区间或赔付金额区间，例如 `50000元-400000元`，不能再写入 `6-65周岁`、`18-60周岁` 等年龄范围；同时继续保证年龄范围不会进入 `人员类型`。

### 已完成

- 新增 `field_cleaners.py`，集中提供年龄范围识别、人员类型清洗、报销金额区间识别和备注追加工具。
- `rule_extractor.py`：
  - `人员类型`、`适用人群`、`参保人群` 等别名后若出现年龄范围或纯数字，不再写入 `人员类型`。
  - 年龄范围转入 `备注`，格式为 `年龄区间：6-65周岁`；纯数字人员类型原值转入备注，避免进入最终字段。
  - 新增 `区间`、`报销区间`、`费用区间`、`医疗费用区间`、`赔付区间`、`金额区间` 的金额区间抽取，支持 `50000元-400000元`、`0-1000元`、`5万元以上` 等。
- `table_extractor.py`：
  - 表格列为 `人员类型` 时，年龄范围或纯数字不会写入 `人员类型`。
  - 表格列为 `区间` 时，年龄范围不会写入 `区间`，改写入 `备注`。
  - 报销金额区间仍正常保留在 `区间`。
- `record_fusion.py`：
  - 融合阶段对 `人员类型` 和 `区间` 做最终清洗，即使 LLM 或数据库直出提供年龄范围，也不会写入最终 Excel 字段。
  - 清洗动作写入冲突证据，`chosen_source=cleaner`，并触发人工复核标记。
  - 当有效人员类型与 LLM 年龄范围冲突时，保留有效人员类型，把年龄范围写入备注。
- `prompts_v2.py` 增加 LLM 约束：不要把年龄范围填入 `人员类型` 或 `区间`，`区间只用于报销金额区间`。
- `field_mapping.py`、`config/field_mapping.yml`、`config/table_mapping.yml` 增加报销金额区间相关别名。
- 新增/更新测试覆盖正文规则、表格规则、融合清洗和 LLM prompt 约束。

### 已验证

- 聚焦回归：6 个新增用例先在旧实现下失败，修复后全部通过。
- 最小样例验证：
  - `人员类型：6-65周岁；区间：50000元-400000元` 输出 `人员类型=""`、`区间="50000元-400000元"`、`备注` 包含 `年龄区间：6-65周岁`。
  - 表格中 `人员类型=6-65周岁`、`区间=18-60周岁` 均不会进入最终字段，备注保留年龄信息。
- `py -m unittest discover -s tests -v`：96 tests OK。
- `py -m pytest -q`：96 passed，33 subtests passed，1 个 FastAPI/Starlette deprecation warning。
- `py -m compileall -q -x "..." .`：通过，退出码 0。

### 注意事项

- 本轮使用用户提供的 `商业补充保险抽取结果_20260701_094411.xlsx` 复现到 `人员类型=6` 和 `人员类型=6-65周岁` 问题；该 Excel 仅用于定位，不提交到 GitHub。
- 未跟踪的 `Q57D2088.tmp` 在本轮开始前已存在，未纳入提交。

## 2026-07-01 续 8

### 本轮目标

继续修复 `DataExtractor` 的前端分页、生成后结果页、OCR 不可用诊断、外部 OCR 文本 fallback、图片表格风险提示、病种名称免责条款过滤，以及人员类型年龄范围清洗专项测试。

### 已完成

- `/api/config/status` 返回 `ocr_available`、`ocr_status_reason`、`ocr_engine`，不暴露本地路径、数据库连接串、API Key 或 token。
- `image_ocr.py` 新增 `get_ocr_status()`，API、CLI 和采集日志复用 OCR 可用性判断。
- `confidence.py` 对“有图片、无 HTML 表格、无 OCR 文本”的记录追加风险提示：`图片表格未识别，抽取结果可能缺失保障责任、保额、保费、等待期、赔付比例等字段`。
- `main.py` 新增 `--ocr-text-file`、`--ocr-json-file`，支持本机 OCR 不可用时注入外部 OCR 文本；字段证据标记 `source=external_ocr_text`。
- 采集日志新增 `ocr_available`、`ocr_status_reason`、`ocr_skipped_reason`、`ocr_failure_reason`、`external_ocr_used`。
- `rule_extractor.py` 增加免责/责任免除/健康告知/不能投保/除外责任等负向上下文过滤，避免把免责条款里的 `高血压、糖尿病、慢性肝炎、女性更年期综合征、男性更年期综合征` 写入 `病种名称`。
- `/api/articles` 返回真实分页元数据：`total`、`limit`、`offset`、`page`、`page_size`、`total_pages`、`has_next`、`has_prev`。
- `db_reader.py` 新增安全参数化 count query，用于默认配置化数据库读取的真实 total。
- `/api/extract` 切换为轻量 job 模式，返回 `job_id`、`status_url`、`result_page`；新增 `/api/jobs/{job_id}` 和 `/api/jobs/{job_id}/preview`。
- Excel preview 只读取 `结果数据` sheet，最多返回前 100 行，不返回服务器本地真实路径。
- `web/index.html`、`web/app.js`、`web/style.css` 实现上一页、下一页、页码、每页 10/20/50、总数、跨页保留选择、清空已选择和 OCR 不可用提示。
- 新增 `web/result.html`、`web/result.js`，结果页轮询 job 状态、展示预览、提供下载和返回列表。
- 新增/更新测试：`tests/test_ocr_status_and_image_risk.py`、`tests/test_person_type_quality.py`、`tests/test_api_server.py`、`tests/test_web_app_static.py`、`tests/test_disease_name_quality.py`。
- 更新 `README.md`、`TEST_REPORT.md`、`REAL_DB_20_TEST_REPORT.md`、`reports/ACCEPTANCE_STAGE_13_15.md` 和 `reports/acceptance_stage_13_15.json`。

### 已验证

- 聚焦测试：`py -m unittest tests.test_api_server tests.test_web_app_static tests.test_ocr_status_and_image_risk tests.test_person_type_quality tests.test_disease_name_quality.DiseaseNameRuleTests.test_exemption_context_diseases_are_not_treated_as_covered_diseases -v`，20 tests OK。
- 全量 `unittest`：`py -m unittest discover -s tests -v`，107 tests OK。
- `py -m pytest -q`：107 passed，36 subtests passed，1 个 FastAPI/Starlette deprecation warning。
- `py -m compileall -q -x "..." .`：通过，退出码 0。
- 真实样本无 OCR：`普惠门诊保·如意版2025 保障详情` 生成成功；`病种名称`、`人员类型`、`区间` 均为空；采集日志 `ocr_triggered=true`、`ocr_skipped_reason=用户选择跳过 OCR`，review reason 写入图片表格未识别风险。
- 真实样本外部 OCR fallback：同一 URL 使用 `--ocr-text-file` 生成成功；`补助限额=100000元`、`报销比例=80%`、`备注=投保年龄：6-65周岁`，`人员类型` 和 `病种名称` 为空，字段证据包含 `source=external_ocr_text`。
- 真实配置 API smoke：`/api/config/status`、`/api/articles?limit=1&offset=0`、`/api/extract` job、`/api/jobs/{job_id}`、`/api/jobs/{job_id}/preview` 通过；返回 `total=7584`、preview headers=26、preview rows=1。

### 注意事项

- 本轮功能仍不提交 `.env`、`logs/`、`outputs/`、真实数据库连接串、真实 API Key 或真实样本 Excel。
- 未跟踪的 `Q57D2088.tmp` 在本轮开始前已存在，仍未纳入提交。

## 2026-07-01 续 9

### 本轮目标

继续修复截图中前端仍显示 `Cannot set properties of null (setting 'hidden')`、分页 `第 0 / 0 页` 但表格有数据、清空已选择和 OCR 默认状态不准确的问题；修复后完成自动化测试、AI 生成数据测试、真实数据库 20 条测试、前端实际页面验证，并推送 GitHub。

### 已完成

- `web/index.html`、`web/result.html` 的脚本地址加入版本参数，避免浏览器继续执行旧的 `/web/app.js`，从根因上规避旧脚本访问已删除 `downloadLink.hidden`。
- `web/app.js` 新增分页规范化逻辑：当后端返回 rows 但 `total/total_pages` 缺失或异常时，至少按 `offset + items.length` 兜底；`currentPage` 有数据时保持从 1 开始。
- `api_server.py` 的分页响应也增加一致性兜底，避免 provider 返回 items 但 total=0 时传给前端错误状态。
- OCR 可用时前端默认取消“跳过 OCR”；OCR 不可用时默认勾选并禁用，同时显示“请安装 OCR 依赖或提供外部 OCR 文本”的明确提示。
- `clearSelection()` 抽成显式函数，清空跨页选择、当前页 checkbox 和全选状态。
- `web/result.js` 对结果页下载按钮和文本节点增加空元素保护，不再直接对可能不存在的节点写 `.hidden`。
- `web/style.css` 使用真实存在的 `#downloadBtn` 样式，去掉旧 `#downloadLink` 选择器。
- 新增/更新回归测试：分页 rows/total 一致性、count SQL 参数化、脚本缓存版本、OCR 默认使用逻辑、清空选择函数和结果页下载按钮防空。

### 已验证

- 聚焦红绿回归：新增 3 个失败用例先失败，修复后通过。
- 局部回归：`py -m unittest tests.test_api_server tests.test_web_app_static tests.test_configured_db_and_fields -v`：38 tests OK。
- 全量 `unittest`：`py -m unittest discover -s tests -v`：111 tests OK。
- `pytest`：`py -m pytest -q`：111 passed，36 subtests passed，1 个 FastAPI/Starlette deprecation warning。
- `compileall`：`py -m compileall -q -x "..." .`：通过，退出码 0。
- AI 生成数据测试：`py -m unittest tests.test_ai_generated_cases -v`：1 test OK。
- 真实数据库 20 条：`py scripts\run_real_db_20.py --result-dir reports\web_fix_real_20_20260701_105540`：`passed=True`；生成 Excel 包含 6 个 sheet，`结果数据` 固定 26 列，未遇到 429。
- 前端实际页面验证：
  - API 启动在 `http://127.0.0.1:8014/`，首页显示 `database_configured=true`、LLM 已配置、OCR 不可用。
  - 首页脚本为 `/web/app.js?v=20260701_web_fix`，总数 `7584`，初始 `第 1 / 380 页`，无 `0/0` 错误。
  - 搜索“医保”后回到第 1 页，总计 `5445` 条；每页 10 后可翻到 `第 2 / 759 页`。
  - 跨页选择保留计数，清空已选择后恢复 `已选择 0 条`。
  - 选择 5 条生成 Excel 后跳转 `/web/result.html?job_id=job_6a90ee563171`；结果页 `生成成功`、preview headers=26、preview rows=5、下载按钮可见，无控制台错误。
  - 下载验证：下载的 Excel 有 6 个 sheet，`结果数据` 表头 26 列。

### 注意事项

- 真实数据库测试产物位于 `reports/web_fix_real_20_20260701_105540/`，包含真实 URL、日志和 Excel，仅作本地验收证据，不提交。
- 前端服务验证产物位于 ignored 的 `logs/web_fix_frontend/`、`outputs/web_fix_frontend/`，不提交。
- 未跟踪的 `Q57D2088.tmp` 在本轮开始前已存在，仍未纳入提交。

## 2026-07-01 续 10

### 本轮目标

继续修复截图中的三个核心问题：OCR 状态仍不清晰、真实库分页 total 不能退化为 20、生成 Excel 后结果页显示 `Not Found` 或把文件名当作 job_id。

### 已完成

- `image_ocr.py` 的 `get_ocr_status()` 现在分别检测 `paddleocr` 和 `paddlepaddle/paddle`，返回 `available`、`engine`、`reason`、`install_hint`，导入失败不会影响 API 启动。
- `/api/config/status` 增加 `ocr_install_hint`，前端可明确提示安装 PaddleOCR 或使用外部 OCR 文本 fallback。
- `/api/extract` 改为生成稳定的 `job_YYYYMMDD_HHMMSS_xxxxxxxx`，不再把 Excel 文件名当作 job_id。
- job 创建、运行、成功、失败都会写入 `outputs/web/jobs/<job_id>.json`，metadata 只保存前端需要的公开字段，不包含本地绝对路径。
- `/api/jobs/{job_id}` 先查内存，再查 metadata 文件；服务重启后仍可查询已完成 job。
- `/api/jobs/{job_id}/preview` 根据 metadata 中的 `file_id` 定位 Excel，仍只预览 `结果数据` sheet 的固定 26 列和最多 100 行。
- 结果页 404 时显示“任务不存在或已过期，请返回列表重新生成。”，不再裸露 `Not Found`。
- 新增回归测试覆盖：真实 total 不等于当前页长度、非法文件名 job_id 404、job metadata 跨 app 重建可用、OCR 安装提示和结果页 404 文案。
- `.gitignore` 增加 `reports/web_fix_persistent_job_*/`，真实库验收产物继续仅保留本地。

### 已验证

- 聚焦回归：`py -m unittest tests.test_api_server.ApiServerTests.test_articles_total_is_full_count_not_current_page_length tests.test_api_server.ApiServerTests.test_successful_job_metadata_survives_app_recreation -v`，2 tests OK。
- OCR/结果页聚焦：`py -m unittest tests.test_ocr_status_and_image_risk.OcrStatusAndImageRiskTests.test_get_ocr_status_reports_missing_dependencies_without_raising tests.test_web_app_static.WebAppStaticTests.test_result_page_calls_job_and_preview_apis -v`，2 tests OK。
- 局部回归：`py -m unittest tests.test_api_server tests.test_ocr_status_and_image_risk tests.test_web_app_static tests.test_configured_db_and_fields -v`，44 tests OK。
- 全量 `unittest`：`py -m unittest discover -s tests -v`，114 tests OK。
- `pytest`：`py -m pytest -q`，114 passed，36 subtests passed，1 个 FastAPI/Starlette deprecation warning。
- `compileall`：`py -m compileall -q -x "..." .`，通过，退出码 0。
- AI 生成数据测试：`py -m unittest tests.test_ai_generated_cases -v`，1 test OK。
- 真实数据库 20 条：`py scripts\run_real_db_20.py --result-dir reports/web_fix_persistent_job_20260701_113409`，`passed=True`。
- 前端真实页面验证：
  - API 启动在 `http://127.0.0.1:8015/`。
  - 首页显示数据库和 LLM 已配置、OCR 不可用；初始 `total=7584`，`第 1 / 380 页`，20 行数据，不再是 `总计 20 条`。
  - 选择 1 条生成 Excel 后跳转到 `/web/result.html?job_id=job_20260701_114243_49763acb`。
  - 结果页显示 `生成成功`，preview headers=26，preview rows=1，下载按钮可用，控制台无错误。
  - 重启 API 后同一 job_id 仍可通过 metadata 查询，结果页仍显示成功并能预览。
  - 下载的 Excel 包含 6 个 sheet，`结果数据` 表头 26 列。

### 注意事项

- 本轮未发现阻断推送的 P0/P1。
- 本轮不提交 `.env`、`logs/`、`outputs/`、真实数据库连接串、真实 API Key 或真实测试 Excel。
- 真实库验收目录 `reports/web_fix_persistent_job_20260701_113409/` 已被忽略，不纳入提交。
- 未跟踪的 `Q57D2088.tmp` 在本轮开始前已存在，仍未纳入提交。

## 2026-07-01 续 11

### 本轮目标

修复用户截图中结果页仍显示 `job_id: 商业补充保险抽取结果_20260701_131048` 的问题，确认是否为旧进程/旧前端资源导致；新增后端版本确认接口；配置 OCR 环境；使用真实数据库数据完成验证后推送。

### 根因定位

- 当前代码已经返回 `job_YYYYMMDD_HHMMSS_xxxxxxxx`，但 8000 端口仍由 09:33 启动的旧 Python 进程占用。
- 旧进程的 `/api/version` 返回 404，`/api/config/status` 未包含 `ocr_install_hint` 和 `web_app_version`，并且其 `/web/app.js` 仍包含 `payload.result_page || ...` fallback。
- 因此截图中的文件名式 job_id 来自旧运行进程或旧缓存前端逻辑，不是当前已提交代码的 `/api/extract` 返回值。

### 已完成

- 新增 `WEB_APP_VERSION=20260701_job_fix`。
- 新增 `GET /api/version`，返回 `project_root`、`cwd`、`git_commit`、`web_app_version` 和功能开关，不暴露数据库连接串、API Key 或密码。
- `api_server.py main()` 启动时打印 cwd、project_root、git_commit、config、field_config、llm_config 和 web_app_version，方便识别旧进程。
- `web/index.html` 和 `web/result.html` 脚本版本改为 `20260701_job_fix`。
- `web/app.js` 在配置状态旁显示版本号，并且生成后只使用后端返回的 `payload.result_page`；如果后端返回的 job_id 不是 `job_`，直接报错，不再自行拼接结果页 URL。
- `web/result.js` 对 URL 中非 `job_` 开头的 job_id 直接提示“任务编号格式不正确，请返回列表重新生成。”，不再调用 `/api/jobs/{file_name}`。
- 使用 Python 3.11 创建 `.venv_ocr`，安装 `requirements.txt`、`paddleocr` 和 `paddlepaddle`；`get_ocr_status()` 返回 OCR 可用。

### 已验证

- TDD 红绿：新增 `/api/version`、前端禁止 fallback 拼 job_id、脚本版本号、结果页非法 job_id 拦截测试；先失败后修复通过。
- OCR 环境：`.venv_ocr` 使用 Python 3.11.9，`paddle=3.3.1`，`paddleocr` 可导入，`get_ocr_status()` 返回 `available=True`。
- 真实样本 OCR 环境运行：`普惠门诊保·如意版2025 保障详情` 读取真实数据库 1 条，生成 Excel 成功，6 个 sheet、26 列；OCR 可用但首轮置信度 medium，当前策略未触发 OCR retry。
- 真实样本外部 OCR fallback：同一 URL 使用外部 OCR 文本生成成功；`补助限额=100000元`、`报销比例=80%`、`备注=投保年龄：6-65周岁`，`人员类型`、`病种名称`、`区间` 均为空；字段证据包含 `source=external_ocr_text`。
- 前端真实库验证：关闭旧 8000 进程后用 `.venv_ocr` 重启，`/api/version` 返回 `20260701_job_fix`，`/api/config/status` 返回 `ocr_available=true`。
- 浏览器验证：首页加载 `/web/app.js?v=20260701_job_fix`，显示 `total=7584`、`第 1 / 380 页`，OCR 可用且“跳过 OCR”默认未勾选。
- 前端生成验证：选择 1 条真实记录后跳转 `/web/result.html?job_id=job_20260701_132800_b4b70145`，结果页成功，preview headers=26、rows=1，下载 Excel 6 个 sheet、26 列。
- 服务重启验证：重启后同一 job 仍可查询和预览，结果页刷新后仍显示成功，不再出现 `Not Found`。
- 随机 20 条真实数据库验收：`py scripts\run_real_db_20.py --result-dir reports/web_fix_persistent_job_20260701_133010`，`passed=True`。
- 全量 `unittest`：`py -m unittest discover -s tests -v`，115 tests OK。
- `pytest`：`py -m pytest -q`，115 passed，36 subtests passed，1 个 FastAPI/Starlette deprecation warning。
- `compileall`：`py -m compileall -q -x "..." .`，通过，退出码 0。
- AI 生成数据测试：`py -m unittest tests.test_ai_generated_cases -v`，1 test OK。

### 注意事项

- `.venv_ocr/`、`logs/`、`outputs/`、真实数据库报告产物均不提交。
- 8000 端口当前由新启动的 Python 3.11 API 服务占用，前端地址为 `http://127.0.0.1:8000/`。
- 未跟踪的 `Q57D2088.tmp` 在本轮开始前已存在，仍未纳入提交。

## 2026-07-01 续 12

### 本轮目标

修复 `普惠门诊保·如意版2025 保障详情` 这类关键保障责任表在图片中的文章只输出 1 行的问题；接入可选 vision 模型、增强 PaddleOCR 失败诊断、完善外部 OCR 文本 fallback，并使用真实数据库样本复测后推送。

### 根因定位

- 该样本没有 HTML table，保障责任表在图片中。
- 旧流程先基于正文和文本 LLM 抽取，只有低置信度时才重跑 OCR；图片 OCR 全部失败时只保留首轮稀疏结果。
- 外部 OCR 文本之前只作为普通正文进入规则/LLM，无法稳定拆成多条保障责任。

### 已完成

- 新增 `vision_client.py`、`vision_extractor.py`，支持 OpenAI-compatible vision `image_url`/base64 调用；配置通过 `VISION_LLM_*` 环境变量读取，不写死 key。
- 新增 `ocr_table_parser.py` 和 `image_table_pipeline.py`，在“无 HTML 表 + 有图片”时前置图片表格识别；外部 OCR 文本优先，其次 vision，最后 PaddleOCR。
- 外部 OCR 文本现在能直接解析“保障项目 / 累计保险金额 / 等待期、免赔额、给付比例”文本，拆成多行保障责任。
- `image_ocr.py` 的 `OcrSummary` 增加逐图错误诊断：图片 URL、下载状态、图片格式、OCR 初始化状态和异常信息。
- 采集日志新增 `vision_enabled`、`vision_triggered`、`vision_success_count`、`vision_failure_count`、`vision_model`、`vision_error`。
- 多行图片表格场景下，正文规则只补公共字段，避免把某一行的 `免赔额0元` 错配到第一条保障责任。
- 泛化地区直字段 `国家/全国/中国` 不再覆盖 OCR/正文中更具体的 `湖南省`。
- 前端新增“外部 OCR 文本”输入框，并随 `/api/extract` 传入 `external_ocr_text`。
- README 补充 DeepSeek 文本模型、vision 模型、PaddleOCR 和外部 OCR fallback 的区别与配置方式。

### 已验证

- 公司网关 `http://192.168.34.97/v1/models` 可访问，`elian-GLM5` 可通过 OpenAI-compatible `chat.completions` 调用；真实 key 只用于运行时环境变量，未写入仓库或日志。
- vision 消息格式探测请求返回 HTTP 200，但当前 `elian-GLM5` 回复未体现可靠图像理解；本样本采用外部 OCR 文本作为最高优先级兜底。
- 真实样本最终运行：`outputs/real_db_20/image_table_external_20260701_1429/商业补充保险抽取结果_20260701_142756.xlsx`。
- 真实样本结果：输出 10 行；`地区名称=湖南省`，`人员类型=中国大陆籍人士`，`保险类型=普惠门诊保·如意版2025`；`病种名称` 为空；`6-65周岁` 写入备注；字段证据包含 `source=external_ocr_text`。
- 关键责任：`意外门诊急诊费用补偿` 抽出 `补助限额=100000元`、`起付标准=免赔额100元`、`报销比例=80%`；`在线问诊药品费用医疗保险金` 抽出 `补助限额=10000元`、`报销比例=70%`。
- 公司 LLM 接口调用成功但未返回严格 JSON，系统保留规则解析的 10 行结果，不再退化为 1 行。
- 全量 `unittest`：`.venv_ocr\Scripts\python.exe -m unittest discover -s tests -v`，123 tests OK。
- `pytest`：`py -m pytest -q`，123 passed，36 subtests passed，1 个 FastAPI/Starlette deprecation warning。
- `compileall`：`py -m compileall -q -x "..." .`，通过，退出码 0。
- AI 生成数据测试：`py -m unittest tests.test_ai_generated_cases -v`，1 test OK。
- 裸 `python -m unittest ...` 和 `python -m pytest ...` 在当前环境直接退出 1 且无输出；本机可用解释器为 `py` 和 `.venv_ocr\Scripts\python.exe`。

### 注意事项

- 本轮不提交 `.env`、`logs/`、`outputs/`、真实数据库连接串、真实 API Key 或真实测试 Excel。
- 未跟踪的 `Q57D2088.tmp` 在本轮开始前已存在，仍未纳入提交。

## 2026-07-01 Round 13

### Goal

Fix DB articles whose benefit tables are stored in images so they no longer collapse to a single row. Re-test the target real DB sample, then randomly test 5 more DB records and compare the generated Excel against the original article/image evidence before pushing.

### Root Cause

- The target article has no HTML table; the benefit table is embedded in article images.
- The local OCR path was triggered, but PaddleOCR 3.7.0 failed with `PaddleOCR.predict() got an unexpected keyword argument 'cls'`.
- Retrying without `cls` exposed a Paddle/PIR oneDNN runtime failure on the real image.
- The configured company OpenAI-compatible endpoint accepted requests, but its image understanding was not reliable enough for this specific table, so deterministic OCR remained necessary.

### Completed

- Pinned the local OCR runtime to `paddleocr==2.10.0` and `paddlepaddle==2.6.2`, which successfully reads the real target images.
- Made `image_ocr.py` compatible with both PaddleOCR 2.x legacy tuple/list results and PaddleOCR 3.x dict/predict-style results.
- Added automatic retry when an OCR engine rejects the `cls` argument.
- Added fragmented OCR table reconstruction in `ocr_table_parser.py` for rows split across multiple OCR text lines.
- Prevented standalone years such as `2025` from being treated as insurance amounts.
- Added focused regression tests for OCR compatibility and fragmented image-table parsing.
- Created random-5 real DB validation artifacts under `C:\Users\admin\Desktop\DataExtractor_random5_test_20260701_152440`.

### Verification

- Focused OCR compatibility tests: `.venv_ocr\Scripts\python.exe -m unittest tests.test_image_ocr_compat` passed, 3 tests.
- Focused fragmented parser tests: `.venv_ocr\Scripts\python.exe -m unittest tests.test_ocr_table_parser_fragmented` passed, 2 tests.
- Target real sample `https://mp.weixin.qq.com/s/7meXk1OSTtr9-GTFxFX4HQ` processed with automatic image OCR: 2 images succeeded, 0 failed, and generated 6 benefit rows instead of 1.
- Target real sample Excel: `outputs/real_db_20/auto_ocr_20260701_152155/商业补充保险抽取结果_20260701_152257.xlsx`.
- Random 5 DB validation generated Excel and comparison report in `C:\Users\admin\Desktop\DataExtractor_random5_test_20260701_152440`.
- Random 5 run processed 5 records with 0 record-level failures. One image in one record returned HTTP 502, while the record still completed with a fallback row.
- Original `mp.weixin.qq.com` URLs timed out during browser/requests screenshot attempts, so comparison used the DB-saved HTML plus downloaded source images/contact sheets from the OCR run.
- Random-5 comparison result: close enough for push. Record 1 split a real benefit table into 7 rows; records 2-5 were marketing/news/service articles without stable detailed benefit tables and were correctly marked/reviewed as summary rows.
- Full suite: `.venv_ocr\Scripts\python.exe -m unittest discover -s tests` passed, 128 tests.

### Notes

- No API keys, `.env`, generated Excel files, downloaded article images, desktop reports, `logs/`, or `outputs/` are committed.
- The pre-existing untracked `Q57D2088.tmp` remains untracked and is not part of this task.
- Known limitation: PaddleOCR may still miss repeated amounts in merged image-table cells, but the target DB sample no longer collapses to one row and extracted key benefit amounts/deductibles/ratios match the source image evidence.

## 2026-07-01 Round 14

### Goal

Polish the lightweight Web frontend after reviewing the current list page and result page screenshots, using a Canva visual draft as direction, then push the frontend refresh.

### Completed

- Created a Canva visual draft for the two core screens: article list workbench and extraction result preview.
- Reworked `web/index.html` into a quieter data workbench layout:
  - top title and subtitle,
  - compact database/LLM/OCR/config/version status chips,
  - command panel for search, OCR/LLM options and Excel generation,
  - collapsed external OCR text panel,
  - selected-record status bar,
  - framed article table with sticky header styling.
- Reworked `web/result.html` into a result-detail layout:
  - job id header,
  - result status badge,
  - preview metadata chip,
  - download action,
  - dedicated scrollable preview table.
- Rebuilt `web/style.css` around a restrained workbench visual system: light background, white panels, clear status colors, blue primary actions, readable table spacing and responsive fallbacks.
- Updated `web/app.js` to populate the new status chips and style safe source links without changing safe DOM rendering.
- Updated `web/result.js` to show preview column/row metadata and success/error badge classes while keeping job polling and preview loading unchanged.
- Added static frontend regression checks for the new workbench components and result table readability constraints.

### Verification

- TDD red/green for the new static layout checks:
  - New tests first failed against the old markup.
  - After implementation, the focused tests passed.
- Frontend static regression: `py -m unittest tests.test_web_app_static -v`, 9 tests OK.
- Local browser verification on a temporary API server at `http://127.0.0.1:8016/`:
  - Home page rendered the new workbench layout with no browser error logs.
  - Default unconfigured database state still disabled query/generate actions as expected.
  - Result page unknown-job state rendered as an error badge with no browser error logs.
  - A temporary success job metadata/workbook verified the result preview path: status `生成成功`, download button visible, preview metadata populated, horizontal table scroll active, and preview table headers computed as `white-space: nowrap`.
- Temporary verification server, logs, metadata and workbook were removed after checking.

### Notes

- This round does not change backend extraction behavior or API contracts.
- No `.env`, `logs/`, `outputs/`, generated Excel files, database credentials, API keys or browser screenshots are committed.
- The pre-existing untracked `Q57D2088.tmp` remains untracked and is not part of this task.

## 2026-07-01 Round 15

### Goal

Complete the first-stage repository optimization on `codex/db-to-excel-extractor`: stabilize the current CLI without changing business field semantics or the fixed 26-column Excel output order.

### Completed

- Added `requirements-dev.txt` and `pytest.ini` for explicit development dependency and test configuration.
- Added focused tests for LLM timeout/retry/detail responses, OCR image download security, run summaries, and runtime/pipeline module exports.
- Split runtime helpers into `runtime.py` and single-record extraction orchestration into `pipeline.py`; `main.py` now coordinates CLI/config/input/batch/output while preserving old helper imports for compatibility.
- Added `run_summary.py` to write `summary.json`, normalized `failed_records.jsonl`, and `retry_ids.txt` under `--log-dir`.
- Extended `LLMClient` with `extract_detail()`, typed response metadata, timeout, max retries, exponential backoff, error classification, elapsed-time logging, usage capture, and sensitive text masking.
- Hardened OCR image downloads: http/https only, localhost/private/link-local/metadata IP rejection, streaming download, byte limit, status and content-type checks, Pillow validation, and masked errors.
- Updated README with development dependency installation, test commands, dry-run notes, run summary/retry usage, LLM retry environment variables, and OCR download safety limits.

### Verification

- Focused new tests: `py -m pytest tests/test_llm_client.py tests/test_image_download_security.py tests/test_run_summary.py tests/test_runtime_pipeline_split.py -q` passed, 15 tests.
- Full pytest after implementation: `py -m pytest -q` passed with the existing FastAPI/Starlette deprecation warning.
- Compile check: `py -m compileall -q -x "..." .` passed.
- CLI dry-run: `py main.py --dry-run --input-xlsx "samples/db/新建 XLSX 工作表.xlsx" --limit 5 --log-dir logs/stage1_dry_run` passed; `summary.json`, `failed_records.jsonl`, and `retry_ids.txt` were generated under the dry-run log directory.

### Notes

- The fixed Excel business headers and main result sheet order were not changed.
- No `.env`, API keys, database credentials, generated Excel files, `logs/`, `outputs/`, or `temp_images/` are committed.
- The pre-existing untracked `Q57D2088.tmp` remains untracked and is not part of this task.

## 2026-07-02 Round 16

### Goal

Continue optimization on `codex/db-to-excel-extractor`: start the project first, close the first-stage leftovers, then implement phase-2 quality, explainability, prompt-versioning, and regression-reporting work before pushing.

### Completed

- Started the local API server at `http://127.0.0.1:8000/`; `/api/health` returned `{"ok":true}`.
- Unified final failure artifacts through `RunSummary.record_failure()`. LLM runtime errors now go to `llm_errors.jsonl` plus metadata collection, and final `failed_records.jsonl` is written by `RunSummary.write_artifacts()`.
- Changed `retry_ids.txt` generation to use only rerunnable `info_id`, `source_id`, or `_source_id`; `SourceURL` is no longer used as a retry id fallback.
- Removed private pipeline imports from `main.py` while keeping local compatibility aliases for older tests.
- Hardened OCR image download SSRF protections with DNS resolution, private/link-local/loopback/multicast/unspecified/reserved address rejection, redirect rejection with target revalidation, and signed URL masking in diagnostics.
- Added `table_normalizer.py` for normalized table cells/tables with spans, multi-level headers, captions, inherited blanks, Markdown escaping, original coordinates, and header paths.
- Updated HTML parsing and table extraction to use normalized tables first and emit coordinate-rich field evidence.
- Added `record_alignment.py` and integrated similarity-based row alignment into fusion, with row-match evidence written to metadata and Excel.
- Added `field_confidence.py`, workbook sheets `字段置信度`, `人工复核`, and `行匹配证据`, and pipeline metadata generation for field confidence and review rows.
- Added `prompt_registry.py`, `--prompt-version`, default v3 prompt text, and prompt/response hashes in collection logs.
- Added `quality_eval.py` and `config/quality_thresholds.yml` for generated-vs-manual workbook comparison reports.
- Added focused regression tests for failure collection, import boundaries, table normalization/extraction coordinates, row alignment, field confidence, Excel review sheets, prompt registry, quality evaluation, and OCR DNS/redirect/masking safety.

### Verification

- New phase-2 focused tests: `py -m pytest tests/test_failure_collection_stage2.py tests/test_import_lint_boundaries.py tests/test_table_normalizer.py tests/test_table_extractor_coordinates.py tests/test_record_alignment.py tests/test_field_confidence.py tests/test_excel_writer_review.py tests/test_prompt_registry.py tests/test_quality_eval_cli.py tests/test_image_ocr_security.py -q` passed, 24 tests.
- Compatibility regression for previously failing areas: `py -m pytest tests/test_excel_multisheet.py tests/test_image_table_extraction_flow.py tests/test_ocr_status_and_image_risk.py tests/test_person_type_quality.py tests/test_record_fusion.py tests/test_record_alignment.py -q` passed.
- Full regression: `py -m pytest -q` passed with the existing FastAPI/Starlette deprecation warning.

### Notes

- No `.env`, API keys, database credentials, generated Excel files, `logs/`, `outputs/`, or `temp_images/` are committed.
- The pre-existing untracked `Q57D2088.tmp` remains untracked and is not part of this task.

## 2026-07-02 A2

- Fixed row-alignment match fields to use the authoritative fixed headers for `标化类型` and `就诊地域`.
- Added configurable alignment thresholds in `config/quality_thresholds.yml` and row-match evidence labels for strong, weak, and below-threshold matches.
- Verification: `py -m pytest tests/test_record_alignment.py tests/test_record_fusion.py -q` passed, 17 tests.

## 2026-07-02 A3

- Enhanced field confidence scoring with collection-log deductions, final-attempt row-match evidence, source/table text corroboration, and human-confirmed review status bonus.
- Expanded `字段置信度` and `人工复核` sheet metadata, including match level, review status, evidence id, attempt, reviewed value/comment placeholders, and exact review headers.
- Pipeline now passes the final attempt's row-match evidence plus source/table text into confidence and review generation without changing the 26-column result sheet order.
- Red TDD check: `py -m pytest tests/test_field_confidence.py tests/test_excel_writer_review.py -q` failed as expected with missing `review_status`, unsupported `row_match_evidence`, and old sheet headers.
- Verification: `py -m pytest tests/test_field_confidence.py tests/test_excel_writer_review.py tests/test_record_alignment.py tests/test_record_fusion.py -q` passed, 22 tests.

## 2026-07-02 A4

- Added `quality_eval.py` CLI compatibility for both legacy positional arguments and the named `--generated/--manual` form.
- Added `--output` as the xlsx output alias and `--json-output` as the JSON output alias; named input paths intentionally override positional paths when both are provided.
- Updated README to recommend the named CLI form while documenting legacy positional compatibility.
- Red TDD check: `py -m pytest tests/test_quality_eval_cli.py -q` failed as expected with 3 failures for unsupported named/alias arguments and unclear missing-manual handling.
- Verification: `py -m pytest tests/test_quality_eval_cli.py -q` passed, output `..... [100%]`.

## 2026-07-02 Phase 3 Task 1

- Added `services` with `JobStore`, `RunContext`, and `ExtractionService`.
- `JobStore` now owns safe job metadata create/update/read/list/delete/archive with atomic JSON writes, safe job ids, relative public paths, and sensitive text filtering.
- `ExtractionService` runs selected-id configured DB extraction without FastAPI request/response objects, supports fake provider/pipeline/writer injection, calls `pipeline.extract_record_rows`, writes workbook output, and writes `RunSummary` artifacts.
- `/api/extract` now defaults to the service path when no runner is injected; the legacy subprocess runner remains available through `use_subprocess_runner=True` or explicit `extract_runner`.
- Added `GET /api/jobs` basic recent-job listing backed by `JobStore`; `GET /api/jobs/{job_id}` and preview recover public metadata through `JobStore`.
- Red TDD check: `py -m pytest tests/test_job_store.py tests/test_extraction_service.py tests/test_api_server.py -q` failed as expected with 6 failures caused by missing `services` imports.
- Verification: `py -m pytest tests/test_job_store.py tests/test_extraction_service.py tests/test_api_server.py -q` passed, output `.................. [100%]` with the existing FastAPI/Starlette deprecation warning.

## 2026-07-02 Phase 3 Task 2

- Added persisted job progress fields for current title/source URL, success/failed/manual-review counts, and per-record progress callbacks in `ExtractionService`.
- Added service cancellation checks between records and a cancelled summary/log path; API cancellation keeps queued/running jobs in `cancelled` even if a fallback runner returns later.
- Added job-level APIs for logs, summary, download, and cancel with tail limits, level filtering, path-bound reads, and sensitive text/query masking.
- Red TDD check: `py -m pytest tests/test_job_store.py tests/test_extraction_service.py tests/test_api_server.py -q` failed as expected on missing progress fields, progress/cancel service hooks, and missing job logs/download/cancel endpoints.
- Verification: `py -m pytest tests/test_job_store.py tests/test_extraction_service.py tests/test_api_server.py -q` passed, output `....................... [100%]` with the existing FastAPI/Starlette deprecation warning.

## 2026-07-02 Phase 3 Task 3

- Upgraded the native HTML/CSS/JS workbench without adding a frontend framework.
- Added extraction settings for `mode`, `no_ocr`, `no_llm`, and `prompt_version`; `prompt_version` now flows from the UI through `/api/extract`, `ExtractionRequest`, and the pipeline call while retaining the default `v3`.
- Home page now creates a job through `/api/extract`, stays on the workbench, polls `/api/jobs/{job_id}`, tails `/logs`, reads `/summary`, exposes job-level `/download`, links to the result page, and supports `/cancel`.
- Added recent job history through `GET /api/jobs` with status, progress, preview/result, summary, download, and cancel actions.
- Result page now shows progress/current title, live logs, summary, cancel, job-level download, and the existing workbook preview.
- Red TDD check: `py -m pytest tests/test_web_app_static.py -q` failed as expected with 6 failures for missing task 3 workbench DOM, job polling/action endpoints, result job panels, version bump, and workbench CSS classes.
- Verification: `py -m pytest tests/test_web_app_static.py tests/test_api_server.py tests/test_extraction_service.py -q` passed, output `................................. [100%]` with the existing FastAPI/Starlette deprecation warning.
