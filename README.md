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

## 固定表头

输出 Excel 固定 26 列，顺序由程序内置常量控制。缺失字段统一填 `--`。默认字段会在模型返回后再次覆盖或补齐，其中：

- `文章时间` 使用 `2025/5/20` 这种日期格式
- `info_id` 保持空白
- `备注` 固定 `--`
- `相关资讯` 保持空白
- `审核状态0待审核1已审核` 固定 `0`
- `执行状态` 默认 `执行中`
- `是否需要手动修改执行状态(1是0否)` 固定 `0`

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
