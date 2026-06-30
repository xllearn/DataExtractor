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

LLM 输出格式默认使用 v2 JSON object，可用 `--llm-format legacy` 回退旧 JSON 数组 prompt：

```bash
python main.py --llm-format v2 --limit 5 --mode merge
python main.py --llm-format legacy --limit 5 --mode merge
```

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

程序会在 LLM 前先执行轻量规则抽取，结果暂时只写日志和传给 LLM v2 作为参考，不直接融合覆盖最终输出。

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

## 日志

运行日志：

```text
logs/run.log
```

失败记录：

```text
logs/failed_records.jsonl
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

## 常见问题

### 图片相对路径无法下载怎么办？

配置 `.env` 的 `IMAGE_BASE_URL`。例如图片是 `/upload/a.jpg`，站点域名是 `https://example.com`，则设置：

```text
IMAGE_BASE_URL=https://example.com
```

如果 `IMAGE_BASE_URL` 为空，程序会记录日志并跳过相对路径图片。

### PaddleOCR 安装失败怎么办？

先用 `--no-ocr` 跑通主流程。后续再按本机 Python、CUDA/CPU 环境安装 PaddleOCR 和 PaddlePaddle。代码中的 OCR 已封装在 `image_ocr.py`，后续可以替换成其他 OCR 服务。即使开启 OCR，程序首轮也不会 OCR，只有低置信度且图片风险较高时才会重跑。

### 大模型返回 JSON 解析失败怎么办？

程序会自动去掉 ```json 代码块、截取第一个 JSON 数组或对象。如果仍失败，原始输出会保存到 `logs/failed_llm_outputs/`，该记录会生成一行兜底数据，基础字段仍会写入 Excel。

### 数据库没有主键导致分页不稳定怎么办？

当前按 `AuditTime DESC, SourceURL ASC` 排序。如果数据库在分页期间持续新增数据，且多条记录的 `AuditTime + SourceURL` 仍相同，分页仍可能不稳定。后续最好补充稳定唯一字段或先落临时快照表。

### 抽取结果比人工少怎么办？

优先检查正文 HTML、表格和 OCR 是否完整，再查看 prompt 和 `logs/run.log`。如果图片里有关键待遇表，确认 OCR 已开启且图片可下载。必要时把人工样本中的拆分口径补充到提示词示例中。
