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
