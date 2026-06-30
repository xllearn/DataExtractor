# DataExtractor Development Log

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
