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
