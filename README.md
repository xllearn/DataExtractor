# MySQL/Excel 政策文章结构化抽取

这个项目用于从 MySQL 数据库或本地调试 Excel 读取商业补充保险/医保政策文章，解析正文 HTML、表格、图片 OCR 文本，再调用 OpenAI-compatible 大模型抽取固定 26 列结构化数据，最后写入 xlsx 文件。

项目目标是尽快可用：单进程命令行运行，不包含前端、任务队列、数据库写回或复杂架构。

## 安装依赖

建议先创建虚拟环境，再安装依赖：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`paddleocr` 和 `paddlepaddle` 体积较大，Windows 环境安装可能较慢或失败。初次调试主流程时，可以先临时注释 `requirements.txt` 里的这两行，或运行时加 `--no-ocr`。

开发和测试依赖单独放在 `requirements-dev.txt`：

```bash
pip install -r requirements-dev.txt
pytest
```

当前测试不依赖真实数据库、真实 LLM、真实 OCR 或真实网络；外部调用路径通过 mock/fake 覆盖。Windows 上如果 `python` 命令指向 Microsoft Store shim，可使用：

```powershell
py -m pytest
```

## 配置 .env

复制 `.env.example` 为 `.env`，填写数据库密码和大模型 API Key：

```bash
copy .env.example .env
```

重点配置：

- `DB_NAME=your-db-name`
- `DB_TABLE=your-db-table`
- `LLM_API_KEY=你的大模型 API Key`
- `LLM_BASE_URL=https://api.deepseek.com`
- `LLM_MODEL=deepseek-chat`
- `OCR_ENABLED=true`
- `IMAGE_BASE_URL=`：当 HTML 图片是 `/upload/...` 或其他相对路径时，用这个基础地址拼接下载地址。

不要把数据库密码或 API Key 写入代码。

## 配置化数据库读取

项目支持新的 `config/db_config.yml`。默认文件保留为空表名，因此未配置 `DATABASE_URL` 和表名时会自动回退到旧的 `.env` + `db.py` 读取方式。

`DATABASE_URL` 建议放在 `.env` 或环境变量中，例如：

```text
DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/database?charset=utf8mb4
```

不要把真实账号、密码或 API Key 提交到仓库。`database.url` 支持 `${DATABASE_URL}` 形式：

```yaml
database:
  url: "${DATABASE_URL}"
source:
  table: articles
  id_column: id
  info_id_column: info_id
  title_column: Title
  html_column: Content
  audit_time_column: AuditTime
  region_column: areaname
  source_url_column: SourceURL
  insurance_type_column: insurancetypename
```

常用示例：

```bash
python main.py --config config/db_config.yml --limit 20 --mode merge
python main.py --selected-ids "1,2,3" --limit 20
python main.py --keyword "医保 报销" --keyword-mode or --limit 20
python main.py --keyword "医保 报销" --keyword-mode and --limit 20
```

优先级：`--input-xlsx` 最高，不连接数据库；`--selected-ids` 高于 `--keyword`，两者同时存在时只按指定 ID 读取，并在日志中记录覆盖关系。

读取条数优先级：

```text
命令行 --limit > config/db_config.yml query.default_limit > .env DEFAULT_LIMIT > 内置默认值
```

关键词会按内置同义词扩展后检索，例如 `医保` 会扩展为 `医保 / 医疗保险 / 基本医保 / 医保基金`，`报销` 会扩展为 `报销 / 报付 / 支付 / 补偿 / 待遇`。检索 SQL 使用参数化参数，字段名和表名会做基础合法性校验。

如果没有启用配置化数据库读取，`--keyword` 会直接报错；旧 `db.py` 流程不会静默忽略关键词。

## 模板和样本

如果有固定样式模板，把它放到：

```text
templates/template.xlsx
```

如果模板不存在，程序会自动创建包含固定 26 列表头的新 xlsx。

如果模板存在，程序只会替换/重建目标 sheet：`结果数据`、`采集日志`、`字段证据`、`冲突证据`、`抽取评估`、`失败记录`。模板中的其他 sheet 会被保留，方便继续使用说明页、字典页或人工校验页。

写入 Excel 前会做基础安全清洗：去除控制字符，限制单元格最大长度，并对以 `=`、`+`、`-`、`@` 开头的文本加前缀，避免被 Excel 当作公式执行。默认占位值 `--` 会保持原样。

调试 Excel 可以放到：

```text
samples/db/新建 XLSX 工作表.xlsx
```

程序也兼容从仓库根目录传入 `samples/db/新建 XLSX 工作表.xlsx`。

人工口径参考样本可以放到：

```text
samples/manual/陕西西安.xlsx
```

这个文件只作为人工参考，不会被程序自动读取。

## 运行方式

默认从 MySQL 读取 1 条，single 模式输出：

```bash
python main.py
```

数据库单条识别：

```bash
python main.py --limit 1 --mode single
```

数据库批量合并识别：

```bash
python main.py --offset 0 --limit 10 --mode merge
```

带 WHERE 条件：

```bash
python main.py --where "province='山东省'" --limit 5 --mode single
```

调试 Excel 模式，不连接数据库：

```bash
python main.py --input-xlsx "samples/db/新建 XLSX 工作表.xlsx" --limit 10 --mode merge
```

关闭 OCR 调试主流程：

```bash
python main.py --input-xlsx "samples/db/新建 XLSX 工作表.xlsx" --limit 1 --mode single --no-ocr
```

默认情况下，程序首轮抽取不会执行 OCR。首轮大模型抽取完成后，程序会先计算置信度；如果 `confidence_score < 70` 且 `ocr_risk_score < 80`，并且未传 `--no-ocr`，才会下载图片、执行 OCR、重新构造 prompt 并二次抽取。二次抽取结果会覆盖首轮结果；如果 OCR 全部失败，则保留首轮结果，并把失败原因写入评估日志。

字段配置路径可用 `--field-config` 指定：

```bash
python main.py --field-config config/field_mapping.yml --limit 5 --mode merge
```

表格规则配置路径可用 `--table-config` 指定：

```bash
python main.py --table-config config/table_mapping.yml --limit 5 --mode merge
```

LLM 配置路径可用 `--llm-config` 指定，默认读取 `config/llm_config.yml`，其中可通过 `${LLM_API_KEY}` 等占位从环境变量读取：

```bash
python main.py --llm-config config/llm_config.yml --limit 5 --mode merge
```

LLM 客户端支持超时、最大重试次数和指数退避。可通过环境变量配置：

```text
LLM_TIMEOUT=60
LLM_MAX_RETRIES=2
LLM_RETRY_BACKOFF=1
```

`LLM_MAX_RETRIES` 表示首次请求失败后的额外重试次数；限流、网络超时和 5xx 服务端错误会重试，API Key 未配置或认证失败会直接报错。日志只记录脱敏后的错误、调用耗时和兼容接口返回的 usage token 统计，不会输出 API Key。

LLM 输出格式默认使用 v2 JSON object，可用 `--llm-format legacy` 回退旧 JSON 数组 prompt：

```bash
python main.py --llm-format v2 --limit 5 --mode merge
python main.py --llm-format legacy --limit 5 --mode merge
```

只使用数据库直接字段、表格规则、正文规则和默认值，不调用 LLM：

```bash
python main.py --no-llm --input-xlsx "samples/db/新建 XLSX 工作表.xlsx" --limit 5 --mode merge
```

`--no-llm` 下不会触发 OCR retry，因为 OCR retry 主要服务于带 OCR 上下文的 LLM 二次抽取。

运行控制参数：

```bash
python main.py --dry-run --input-xlsx "samples/db/新建 XLSX 工作表.xlsx" --limit 5
python main.py --no-excel --save-intermediate --log-dir logs/debug_run --limit 5
python main.py --fail-fast --max-record-errors 1 --limit 20 --mode merge
python main.py --strict-config --config config/db_config.yml --limit 20
```

- `--log-dir`：指定运行日志、失败记录、证据日志和中间结果保存目录，默认 `logs/`。
- `--dry-run`：不初始化 LLM，不执行 OCR retry，不写 Excel；适合验证读取、规则抽取、日志和错误处理路径。
- `--no-excel`：执行抽取和日志记录，但不生成 Excel。
- `--save-intermediate`：为每条记录保存解析文本、规则结果、LLM 原始输出、融合结果和评估 payload 到 `log-dir/intermediate/`。
- `--fail-fast`：第一条记录处理失败后立即停止。
- `--max-record-errors`：允许的单条记录失败数，默认 20；达到阈值后停止后续记录。
- `--strict-config`：非 `--input-xlsx` 模式下强制使用配置化数据库读取，缺少 `DATABASE_URL` 或表配置时直接报错。

如果本地没有样本 Excel，可用测试中的临时 workbook 或自建包含 `Title`、`Content`/`Context`、`AuditTime` 的调试 Excel 跑 dry-run；dry-run 不初始化 LLM、不执行 OCR retry、不写 Excel，适合验证读取、规则、日志和摘要路径。

## 输出模式

`single` 是默认模式。每条输入记录生成一个独立 xlsx，文件名类似：

```text
山东省_德州市_德州惠民保2024_20231108_001.xlsx
```

一条文章如果被大模型拆成多行，会写入同一个文件。

`merge` 模式会把多条输入记录合并到一个文件：

```text
商业补充保险抽取结果_yyyyMMdd_HHmmss.xlsx
```

输出目录默认是 `outputs/`，可用 `--output-dir` 修改。

## 固定表头和字段映射

输出 Excel 固定 26 列，顺序由 `config/field_mapping.yml` 校验并控制；配置文件不存在时使用 `utils.EXCEL_HEADERS` 兜底。配置中的 `headers` 必须与固定 26 列完全一致，缺失、重复或顺序错误都会停止运行并给出清晰错误。

最终写入 Excel 前会再次标准化：

- 只保留固定 26 列，多余字段不会写入
- 缺失字段使用 `defaults` 中的默认值，没有默认值则填空字符串
- LLM 返回字段别名会映射到标准字段，例如 `支付比例` -> `报销比例`，`起付线` -> `起付标准`，`最高支付限额` -> `补助限额`
- 数据库配置中的 `direct_field_columns` 会写入 `_direct_fields`，在 LLM 正常返回、空数组、JSON 解析失败 fallback 和规则抽取结果中都会优先覆盖到最终 26 列

默认字段会在模型返回后再次覆盖或补齐，其中：

- `文章时间` 使用 `2025/5/20` 这种日期格式
- `info_id` 保持空白
- `备注` 固定 `--`
- `相关资讯` 保持空白
- `审核状态0待审核1已审核` 固定 `0`
- `执行状态` 默认 `执行中`
- `是否需要手动修改执行状态(1是0否)` 固定 `0`

## 规则抽取

## Phase 2 quality and explainability

This branch now adds a second explainability layer on top of the fixed 26-column result sheet:

- HTML tables are normalized before extraction. `rowspan`/`colspan`, multi-level headers, captions, inherited blank cells, Markdown escaping, and original cell coordinates are preserved.
- Field evidence can include `table_index`, `row_index`, `col_index`, `header`, `header_path`, `cell_text`, `caption`, and `evidence_id`.
- Row fusion aligns table/text-rule/LLM rows by key-field similarity instead of raw row order, and writes row-match evidence.
- Workbooks can include `字段置信度`, `人工复核`, and `行匹配证据` sheets when the pipeline provides those metadata rows.
- Prompt versioning is available with `--prompt-version v3` by default; `--prompt-version v2` keeps the previous v2 prompt text. Collection logs include prompt and response hashes.
- `quality_eval.py` compares a generated workbook with a manually reviewed workbook and writes both xlsx and json reports:

```bash
python quality_eval.py outputs/generated.xlsx samples/manual/reviewed.xlsx --output-xlsx reports/quality_eval.xlsx --output-json reports/quality_eval.json
```

Default thresholds live in `config/quality_thresholds.yml`.

程序会在 LLM 前先执行轻量规则抽取，规则结果会写入证据日志、传给 LLM v2 作为参考，并进入最终融合流程。

表格规则配置在：

```text
config/table_mapping.yml
```

它支持 HTML `<table>`、Markdown 风格表格和简单分隔符类表格文本。表头别名会映射到固定 26 列，例如 `支付比例` -> `报销比例`，`起付线` -> `起付标准`，`最高支付限额` -> `补助限额`。无法映射的表格列会合并到 `备注`。

正文键值规则会识别常见表达，例如：

```text
报销比例：80%
起付标准为500元
年度最高支付限额为15万元
居民医保报销比例为60%
三级医院支付比例70%
```

当前支持抽取起付标准、补助限额、报销比例、人员类型、保险类型、医院类型、病种名称、类型和标化类型等字段。规则失败不会中断单条记录处理。

“病种名称”正文规则会做额外清洗：优先从 `病种名称`、`疾病名称`、`特定病种`、`保障病种`、`纳入病种`、`病种范围` 等强上下文抽取；普通正文只保留明确核心疾病词，例如 `帕金森病`、`高血压`、`糖尿病`、`恶性肿瘤` 等。宣传语、费用描述、人物/地名/时间长句，以及 `大病`、`既往症`、`慢性病`、`特殊病` 等泛化词不会直接写入病种名称。

## 规则和 LLM 融合

程序会把数据库直接字段、表格规则、正文规则和 LLM 结果融合为最终输出。融合优先级固定为：

```text
数据库直接字段 > 表格规则 > 正文规则 > LLM > 默认值
```

LLM 主要用于补充规则没有抽到的字段。规则和 LLM 对同一字段给出不同值时，程序保留高优先级值，生成冲突证据，并标记 `need_manual_review=true`。如果规则记录数和 LLM 记录数不一致，程序会尽量按顺序对齐或追加 LLM 记录，同时标记人工复核。

“病种名称”有特殊融合规则：如果正文规则给出明显长句，而 LLM 给出其中的核心疾病名且通过校验，则优先采用 LLM；如果正文规则和 LLM 都不可信，则清空病种名称并标记人工复核。表格中明确表头为 `病种名称`、`疾病名称`、`特定病种` 等时仍作为高置信来源。

OCR retry 现在基于融合后的结果做置信度评估。首轮融合结果低置信度且存在图片风险时才 OCR；OCR 成功后会用 OCR 文本重新调用 LLM v2、重新融合、重新评估。程序会比较首轮和 OCR retry 的置信度：retry 解析失败、没有结果或置信度明显下降时保留首轮，否则采用 OCR retry。日志会记录 OCR 触发原因、成功/失败图片数、OCR 前后置信度、是否改善和最终采用 attempt。

## LLM v2 输出格式

默认 `--llm-format v2` 要求模型返回 JSON object：

```json
{
  "records": [
    {
      "报销比例": "80%"
    }
  ],
  "evidence": {
    "报销比例": "原文证据片段"
  },
  "confidence": {
    "报销比例": 0.85
  },
  "need_manual_review": false,
  "review_reason": ""
}
```

解析时会强制只保留固定 26 列，补齐缺失字段，删除多余字段，`confidence` 会裁剪到 0-1，`need_manual_review` 会转换为 bool。旧版 JSON array 和单 record object 仍兼容。

## Excel 多 sheet 输出

`single` 和 `merge` 模式现在都会输出可追溯 workbook，包含以下 sheet：

- `结果数据`：固定 26 列，严格按 `field_mapping.headers` 输出
- `采集日志`：每篇文章的输入、OCR、LLM、人工复核和输出状态
- `字段证据`：数据库直接字段、表格规则、正文规则、LLM 证据，含 `chosen` 标记
- `冲突证据`：规则与 LLM 冲突时的保留值、冲突值和原因，同时保留通用字段 `source_a`、`value_a`、`source_b`、`value_b`、`chosen_source`、`chosen_value`、`reason`
- `抽取评估`：复用置信度评估 payload
- `失败记录`：单条记录失败信息

旧的 `write_rows_to_workbook` 仍保留兼容，内部会写只有 `结果数据` 的 workbook。

## 日志

运行日志：

```text
logs/run.log
```

可通过 `--log-dir` 改到其他目录。程序写入日志前会对常见敏感文本做脱敏，包括数据库 URL 密码、API Key、password、token 和 secret。

失败记录：

```text
logs/failed_records.jsonl
```

每次运行结束后还会生成运行摘要和重跑文件：

```text
logs/summary.json
logs/retry_ids.txt
```

`summary.json` 包含 `run_id`、起止时间、耗时、输入模式、总记录数、成功/失败数、输出行数、LLM 解析失败数、OCR 触发/失败数、人工复核数、输出 Excel 路径和日志目录。`failed_records.jsonl` 每行包含同一个 `run_id`、记录索引、`source_id`、`info_id`、标题、来源 URL、失败阶段和脱敏错误。`retry_ids.txt` 每行一个可用于后续 `--selected-ids` 的 ID，优先级为 `info_id`、`_source_id`、`SourceURL`。

重跑失败记录示例：

```powershell
$ids = (Get-Content logs\retry_ids.txt) -join ","
py main.py --config config/db_config.yml --selected-ids $ids --mode merge
```

抽取置信度评估：

```text
logs/extract_eval.jsonl
```

规则字段证据：

```text
logs/field_evidence.jsonl
```

规则抽取错误：

```text
logs/rule_extract_errors.jsonl
```

冲突证据：

```text
logs/conflict_evidence.jsonl
```

每条模型输出行都会记录内部评估字段：

- `confidence_score`：0-100 整数
- `confidence_level`：`high` / `medium` / `low`
- `confidence_reason`：简要扣分原因
- `should_retry_with_ocr`：是否建议 OCR 重跑
- `ocr_trigger_reason`：触发 OCR 原因，未触发为 `--`

这些评估字段不会写入最终 Excel，Excel 仍保持固定 26 列。传 `--debug` 时，评估详情也会输出到控制台日志。

大模型 JSON 解析失败的原始输出：

```text
logs/failed_llm_outputs/
```

单条记录失败不会中断整个批次。

## 阶段 13-15：质量评估、图片导入和 Web 页面

### Excel 相似度对比

使用 `excel_compare.py` 对比系统生成 Excel 和人工 Excel：

```powershell
py excel_compare.py --generated outputs/result.xlsx --manual samples/manual/人工.xlsx --output reports/compare_report.xlsx
```

对比会读取 `结果数据` sheet，按固定 26 列输出：

- `overall_similarity`：整体相似度，范围 `0..1`
- `core_field_similarity`：核心字段相似度，核心字段包括 `病种名称`、`报销比例`、`起付标准`、`补助限额`、`人员类型`、`保险类型`
- 字段级准确率/相似度、行级匹配和差异明细

比较逻辑支持空值匹配、百分号归一、金额归一和文本模糊匹配，例如 `80%` 与 `80％`、`15万元` 与 `150000元` 可视为一致。

### AI 生成数据回归

模拟数据位于 `samples/ai_generated/`：

```powershell
py -m unittest tests.test_ai_generated_cases -v
```

测试不调用真实 LLM，而是使用 fake LLM 返回可控 JSON，覆盖表格、正文、图片占位、强/弱上下文、无病种、泛化病种、多病种和多待遇类型。验收阈值为：

```text
overall_similarity >= 0.85
core_field_similarity >= 0.90
```

### 图片数据导入与人工 Excel 对比

如果本机 OCR 可用，可直接从图片 OCR；如果没有 OCR，可提供人工转录 JSON/CSV/XLSX 作为 fallback。当前脚本支持把人工 Excel 转成一条数据库文章记录，写入测试表，再从数据库重新读取并生成 Excel：

```powershell
py scripts\run_image_import_test.py --result-dir "$env:USERPROFILE\Desktop\DataExtractor_test_results" --target-table image_import_articles
```

导入脚本使用 SQLAlchemy 参数化 SQL 和事务，默认创建/写入测试表 `image_import_articles`，并写入 `source=image_import`、`batch_id=image_import_YYYYMMDD_HHMMSS`。不要直接写生产主表；如果必须写真实表，需要保留 batch 标记便于清理。

图片解析中间结果、生成 Excel、对比报告默认写到传入的结果目录。真实图片原件、人工 Excel、`logs/`、`outputs/` 和 `.env` 不应提交。

### 真实数据库分层测试

真实数据脚本会从 `.env` / `config/llm_config.yml` 读取数据库和 LLM 配置，不会把密钥写入报告：

```powershell
py scripts\run_real_db_smoke.py --result-dir "$env:USERPROFILE\Desktop\DataExtractor_test_results"
py scripts\run_real_db_20.py --result-dir "$env:USERPROFILE\Desktop\DataExtractor_test_results"
```

脚本会检查退出码、6 个 sheet、固定 26 列、已知 `病种名称` 错误长句和 LLM 429。遇到 429 不算通过。

### Web API 和前端页面

启动后端：

```powershell
py api_server.py --host 127.0.0.1 --port 8000
```

打开：

```text
http://127.0.0.1:8000/
```

页面支持数据库状态查看、关键词查询、勾选记录、`no_ocr` / `no_llm` 选项、生成 Excel 和下载 Excel。接口包括：

- `GET /api/health`
- `GET /api/version`
- `GET /api/config/status`
- `GET /api/articles?keyword=医保&limit=20&offset=0`
- `POST /api/extract`
- `GET /api/jobs/<job_id>`
- `GET /api/jobs/<job_id>/preview`
- `GET /api/download/<file_id>`

`/api/articles` 返回真实分页信息：`total`、`page`、`page_size`、`total_pages`、`has_next`、`has_prev`。前端支持上一页、下一页、每页 10/20/50、总数显示、搜索后回到第一页、跨页保留已选记录和清空已选择。

`/api/extract` 创建后台 job 并返回 `job_id`、`status_url` 和 `result_page`。前端会自动跳转到 `/web/result.html?job_id=...`，结果页轮询 job 状态，成功后调用 preview API 预览 `结果数据` sheet 前 100 行，并提供下载按钮。job metadata 会写入 `outputs/web/jobs/<job_id>.json`，服务重启后已完成任务仍可查询和预览。下载接口只允许下载 `outputs/web/` 下由系统生成的 xlsx 文件，并防止路径穿越。当前页面没有登录权限系统，仅建议在本机或内网受控环境使用。

`/api/version` 用于确认当前后端是不是本仓库当前版本，会返回 `project_root`、`cwd`、`git_commit`、`web_app_version` 和功能开关，不返回数据库连接串、API Key 或密码。启动 API 时终端也会打印这些信息，方便排查是否仍在运行旧目录、旧分支或旧进程。

首页和结果页脚本使用版本参数加载，例如 `/web/app.js?v=20260701_job_fix` 和 `/web/result.js?v=20260701_job_fix`，用于避免浏览器继续执行旧版脚本造成 DOM id 不匹配或把 Excel 文件名当作 job_id。若页面曾打开过旧版本，请先重启后端，再用 `Ctrl+F5` 强制刷新；如果浏览器仍加载旧 JS，可清缓存或用无痕窗口打开。

### 综合验收

综合验收结果建议写到桌面新目录：

```powershell
py scripts\run_acceptance_all.py --result-dir "$env:USERPROFILE\Desktop\DataExtractor_test_results_YYYYMMDD_HHMMSS"
```

脚本会运行 unittest、pytest、项目源码 compileall、AI 生成数据测试、前端 API 测试、真实数据库 3 条 smoke、真实数据库 20 条、图片导入和人工 Excel 对比。详细日志和生成文件写在桌面结果目录；仓库内只提交脱敏汇总文档。

## 常见问题

### 图片相对路径无法下载怎么办？

配置 `.env` 的 `IMAGE_BASE_URL`。例如图片是 `/upload/a.jpg`，站点域名是 `https://example.com`，则设置：

```text
IMAGE_BASE_URL=https://example.com
```

如果 `IMAGE_BASE_URL` 为空，程序会记录日志并跳过相对路径图片。

图片下载默认只允许 `http`/`https`，拒绝 `localhost`、`127.0.0.1`、`0.0.0.0`、`::1`、私有网段、link-local 和 metadata 地址（如 `169.254.169.254`）。下载使用 streaming，默认最大 10MB，优先要求响应 `Content-Type` 为 `image/*`，并在写入后用 Pillow 验证图片可打开。可通过环境变量调整：

```text
IMAGE_DOWNLOAD_TIMEOUT=20
IMAGE_MAX_BYTES=10485760
```

下载失败、非图片响应或图片验证失败会作为单张图片错误写入 OCR 诊断，不会中断整批记录处理。

### PaddleOCR 安装失败怎么办？

先用 `--no-ocr` 跑通主流程。后续再按本机 Python、CUDA/CPU 环境安装 PaddleOCR 和 PaddlePaddle。代码中的 OCR 已封装在 `image_ocr.py`，后续可以替换成其他 OCR 服务。即使开启 OCR，程序首轮也不会 OCR，只有低置信度且图片风险较高时才会重跑。

CPU 版本示例：

```powershell
pip install paddleocr
pip install paddlepaddle
```

如果 PaddleOCR 在当前 Windows 或 Python 版本无法安装，建议使用 Python 3.10/3.11 创建单独环境，或先使用外部 OCR 文本 fallback。

Windows 上 Python 3.14 可能没有稳定的 PaddleOCR/PaddlePaddle wheel，建议使用 Python 3.11 单独环境：

```powershell
py -3.11 -m venv .venv_ocr
.\.venv_ocr\Scripts\python.exe -m pip install --upgrade pip
.\.venv_ocr\Scripts\python.exe -m pip install -r requirements.txt
.\.venv_ocr\Scripts\python.exe -c "from image_ocr import get_ocr_status; print(get_ocr_status())"
```

用 OCR 环境启动 Web API：

```powershell
.\.venv_ocr\Scripts\python.exe api_server.py --host 127.0.0.1 --port 8000 --config logs/real_db_20/db_config.runtime.yml --field-config config/field_mapping.yml --llm-config config/llm_config.yml
```

此时前端 `/api/config/status` 应显示 `ocr_available=true`，页面显示 `OCR：可用`，并且“跳过 OCR”默认不勾选。

`/api/config/status` 会返回 `ocr_available`、`ocr_status_reason`、`ocr_install_hint` 和 `ocr_engine`。如果 OCR 可用，前端默认不勾选“跳过 OCR”；如果 OCR 不可用，前端会默认勾选并禁用“跳过 OCR”，并提示 `OCR 不可用，图片型表格可能无法抽取。请安装 OCR 依赖或提供外部 OCR 文本。`。当文章存在图片、没有 HTML 表格且 OCR 不可用或失败时，采集日志和抽取评估会写入：

```text
图片表格未识别，抽取结果可能缺失保障责任、保额、保费、等待期、赔付比例等字段
```

如果本机 OCR 不可用，可以使用外部 OCR 文本 fallback：

```powershell
py main.py --config logs/real_db_20/db_config.runtime.yml --field-config config/field_mapping.yml --llm-config config/llm_config.yml --selected-ids "https://mp.weixin.qq.com/s/7meXk1OSTtr9-GTFxFX4HQ" --ocr-text-file local\ocr_text.txt --mode merge
```

也可以按 source id 或 URL 提供 JSON 映射：

```json
{
  "https://mp.weixin.qq.com/s/7meXk1OSTtr9-GTFxFX4HQ": "外部 OCR 识别出的图片表格文本..."
}
```

对应参数：

```powershell
py main.py --ocr-json-file local\ocr_text_by_source.json
```

外部 OCR 文本会进入 LLM v2 prompt，并在字段证据中标记 `source=external_ocr_text`。

图片表格文章会先判断是否存在 HTML table。若没有 HTML table 但存在图片，处理顺序为：

```text
外部 OCR 文本（如果提供）
→ vision LLM（如果配置且可用）
→ PaddleOCR
→ 规则抽取 + LLM v2 融合
```

`config/llm_config.yml` 支持可选 vision 配置，所有值都通过环境变量注入，不要把 API Key 写入文件：

```yaml
vision:
  enabled: "${VISION_LLM_ENABLED}"
  provider: "${VISION_LLM_PROVIDER}"
  api_key: "${VISION_LLM_API_KEY}"
  base_url: "${VISION_LLM_BASE_URL}"
  model: "${VISION_LLM_MODEL}"
  timeout_seconds: 120
```

vision 模型需支持 OpenAI-compatible `chat.completions` 的 `image_url` 或 base64 data URL 内容块，例如 GPT-4o、GPT-4.1、Qwen-VL 或其他兼容多模态模型。DeepSeek 文本模型、`deepseek-chat` 等文本模型只适合文本抽取，不等于图片识别模型；图片表格必须配置 vision 模型、PaddleOCR，或提供外部 OCR 文本。

前端列表页提供“外部 OCR 文本”输入框。选择记录后粘贴图片表格 OCR 文本再生成 Excel，后端会通过 `/api/extract` 的 `external_ocr_text` 注入同一条抽取链路，结果页会显示“使用了外部 OCR 文本”。

### 大模型返回 JSON 解析失败怎么办？

程序会自动去掉 ```json 代码块、截取第一个 JSON 数组或对象。如果仍失败，原始输出会保存到 `logs/failed_llm_outputs/`，该记录会生成一行兜底数据，基础字段仍会写入 Excel。

### 数据库没有主键导致分页不稳定怎么办？

当前按 `AuditTime DESC, SourceURL ASC` 排序。如果数据库在分页期间持续新增数据，且多条记录的 `AuditTime + SourceURL` 仍相同，分页仍可能不稳定。后续最好补充稳定唯一字段或先落临时快照表。

### 抽取结果比人工少怎么办？

优先检查正文 HTML、表格和 OCR 是否完整，再查看 prompt 和 `logs/run.log`。如果图片里有关键待遇表，确认 OCR 已开启且图片可下载。必要时把人工样本中的拆分口径补充到提示词示例中。

## 2026-07-01 Web API 和前端错误处理补充

默认 `config/db_config.yml` 是模板配置，通常没有真实表名。直接运行 `py api_server.py --host 127.0.0.1 --port 8000` 时，如果没有配置好 `.env` 和 `config/db_config.yml`，页面会显示数据库未配置，并禁用搜索、全选和生成 Excel。

真实使用前请指定可用配置：

```powershell
py api_server.py --host 127.0.0.1 --port 8000 --config logs/real_db_20/db_config.runtime.yml --field-config config/field_mapping.yml --llm-config config/llm_config.yml
```

打开：

```text
http://127.0.0.1:8000/
```

API 错误统一返回 JSON，例如数据库未配置时 `/api/articles` 返回：

```json
{
  "detail": "数据库未配置，无法查询文章。请使用 --config 指定可用 db_config.yml：source.table 不能为空",
  "error_type": "DatabaseNotConfigured"
}
```

前端会先检查响应 `content-type`，后端即使返回非 JSON 文本也会显示友好错误，不再抛出 `Unexpected token 'I'... is not valid JSON`。文章表格使用 DOM API 和 `textContent` 渲染数据库字段，来源链接仅允许 `http://` 和 `https://`。

当前 `/api/extract` 已切换为轻量 job 模式，单次最多 50 条。页面生成后会跳转结果页，结果页展示 queued/running/success/failed 状态、Excel 预览和下载链接。

`人员类型` 只保留人群身份或参保类别；`6-65周岁`、`18-70岁`、`出生满30天-65周岁` 等年龄范围会从 `人员类型` 清空并转入 `备注`。`区间` 只用于报销金额区间、费用区间或赔付金额区间，例如 `50000元-400000元`；年龄范围不会进入 `区间`。

病种名称抽取增加免责条款过滤。出现在 `免责`、`责任免除`、`投保须知`、`健康告知`、`既往症`、`不能投保`、`除外责任` 等上下文中的疾病，不会作为保障病种写入 `病种名称`；只有 `病种名称`、`疾病名称`、`保障病种`、`纳入病种`、`病种范围` 等强上下文才会抽取。

图片导入脚本默认只允许写入测试表：`image_import_articles`、`test_*`、`*_test`。如果确需写非测试表，必须显式传入：

```powershell
py scripts\import_image_data_to_db.py --image local\sample.jpeg --transcript local\manual.xlsx --target-table prod_articles --force-production-table
```

综合验收脚本的图片和人工 Excel 样本不再强依赖仓库内固定路径。需要跑 image import 时显式传入：

```powershell
py scripts\run_acceptance_all.py --result-dir "$env:USERPROFILE\Desktop\DataExtractor_test_results_YYYYMMDD_HHMMSS" --image local\sample.jpeg --manual-excel local\manual.xlsx --image-import-table image_import_articles
```

如果没有提供 `--image` 和 `--manual-excel`，综合验收会跳过 image import，并在报告中写明 skipped reason。
