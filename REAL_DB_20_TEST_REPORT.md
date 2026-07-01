# DataExtractor 真实数据库 20 条小样本端到端测试报告

## 1. 基本信息

- 测试时间：2026-06-30 13:36:32
- 当前分支：codex/db-to-excel-extractor
- 当前 commit hash：08d0b4cf
- Python 版本：3.14.0 (tags/v3.14.0:ebf955d, Oct 7 2025, MSC v.1944 64 bit AMD64)
- 是否使用真实数据库：是，已连接真实 MySQL 并执行只读随机抽样查询。
- 是否使用真实 LLM：未进入 LLM 阶段；读取阶段被配置化表名安全校验阻断。
- 是否启用 OCR：未启用；试跑命令使用 `--no-ocr`，原因是当前环境未安装 PaddleOCR/paddlepaddle，且先按 3 条样本试跑主流程。
- 是否生成 Excel：否。
- 是否建议合并：暂不建议在真实数据库配置未调整或主逻辑未确认前合并真实库验收结果。

## 2. git 状态

执行命令：

```bash
git branch --show-current
git rev-parse --short HEAD
git status --short
```

输出：

```text
codex/db-to-excel-extractor
08d0b4cf
 M README.md
 M config.py
 M main.py
 M tests/test_configured_db_and_fields.py
?? TEST_REPORT.md
?? config/llm_config.yml
```

说明：以上未提交改动均为上一轮测试修复/报告相关内容，未覆盖或回滚。

## 3. 配置和环境检查

配置文件存在性：

- `config/db_config.yml`：存在。
- `config/field_mapping.yml`：存在。
- `config/table_mapping.yml`：存在。
- `config/llm_config.yml`：存在。

环境变量 / `.env` 检查结果：

- 根目录 `.env`：不存在或未配置 `DATABASE_URL` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`。
- `db_to_excel_extractor/.env`：存在旧式配置，包含 `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_TABLE` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`。
- 未在终端、日志或报告中打印完整数据库连接串、数据库密码或 LLM API Key。

`config/db_config.yml` 当前默认内容中：

- `database.url` 为 `${DATABASE_URL}`。
- `source.table` 为空。
- `source.id_column` 为空。
- `source.info_id_column` 为空。

因此默认配置化数据库读取路径不能直接就绪。为避免修改核心配置文件，本次创建了临时运行配置：

- `logs/real_db_20/db_config.runtime.yml`

该文件只包含 `${DATABASE_URL}` 占位、表名和字段名，不包含数据库密码或 API Key。

## 4. 随机抽取方式

抽取方式：方案 A，使用真实 MySQL 只读 SQL 随机抽取 20 条。

探测结果：

- 表名：`temp_商业补充保险_20250523`
- 主键候选结果：未发现普通 `id` / `info_id` 列；使用存在的 `SourceURL` 作为精确定位列。
- 关键字段存在性：`Title`、`Content`、`AuditTime`、`areaname`、`SourceURL` 均存在。

随机抽样 SQL 逻辑：

```sql
SELECT `SourceURL` AS sid
FROM `temp_商业补充保险_20250523`
WHERE Content IS NOT NULL AND Content <> ''
ORDER BY RAND()
LIMIT 20;
```

随机抽取到的 20 个 `SourceURL`：

1. `https://ythmb.shie.com.cn/#/?busiDomainCode=YT-YL-10186&agentID=ythmbtoken800001`
2. `https://hmbcity.webao99.com/health/tianjinc/#/healthServiceStaticTj`
3. `http://mp.weixin.qq.com/s?__biz=Mzg2NDI1NTA0Mg==&mid=2247501825&idx=8&sn=48b1b81db88e6405d3bad99eb7aef5fc&chksm=cf2dc3865c024cbe4abc96d3820e4c867ab94fa586d41d6bfb970212f99482cd3555c4b047b7&scene=126&sessionid=1729947555#rd`
4. `https://mp.weixin.qq.com/s/o98QC8N6lRSZ9CKO3IMVeg`
5. `https://mp.weixin.qq.com/s/Eu6G8dBbUi0s7Pr4MBSsqQ`
6. `http://mp.weixin.qq.com/s?__biz=MzkyMDI5NTA0Mg==&mid=2247502636&idx=1&sn=cd0c787cac49be3e05e0747cdab9b6eb&chksm=c19788c1f6e001d751b3eea08e110df4ebdc0a287ec36ba32f7914196f51f01a2ef50f3a808d#rd`
7. `http://mp.weixin.qq.com/s?__biz=Mzk0ODYyMzY5MQ==&mid=2247486603&idx=1&sn=26eff6fc96f589ce5f70dfae0e0dde6a&chksm=c25fc8d251fb1bb30b0d26a523929977308e389d6700de38260ba5619f41e315c9e8d318837f&scene=126&sessionid=1730436799#rd`
8. `https://mp.weixin.qq.com/s/T0PR_eE2MQ-yS15zaL8aTA`
9. `http://mp.weixin.qq.com/s?__biz=MzkwMTIyMzk1NA==&mid=2247503136&idx=1&sn=6ba3fac9bd801b9924921ef169fd9bac&chksm=c0ba8e5df7cd074b5046181269c18f9d31b3ebdc7a916eb74fa6f8b47e66f1d80b06a4b272dd&scene=126&sessionid=1730117107#rd`
10. `http://mp.weixin.qq.com/s?__biz=MzkzOTg2NjczMg==&mid=2247487753&idx=1&sn=53d4fe78198c4f35743fee7629fc7825&chksm=c359a95bb6d5252e6fc787ff003c002c17c41455e9545b2530c521397150181360a653b65d0d&scene=126&sessionid=1740551426#rd`
11. `https://mp.weixin.qq.com/s/fgrcrQCzLjYImNghofZ5qQ`
12. `http://mp.weixin.qq.com/s?__biz=MzkyNjM5NzA4OQ==&mid=2247487188&idx=3&sn=64f9e2e4ed9d76573da6b16eb1abaf70&chksm=c3b336b6e64c4d67751233a9f0f419d5db3a9628cd836315dc47bdee1ce4a8653b36a787b3c3&scene=126&sessionid=1732538335#rd`
13. `https://mp.weixin.qq.com/s?__biz=MzI5NzI1MTc5Mg==&mid=2247485983&idx=1&sn=092e6cb84ed847fbce5ef1ad26711587&source=41#wechat_redirect`
14. `https://mp.weixin.qq.com/s/UzUEbZHpi49RfF0je2ZAPA`
15. `https://mp.weixin.qq.com/s/4eDBu9Mfd7MCagX4ewrP4w`
16. `https://hmb.baoxian72.com/qujing_mobile_2023/index.html?channelCode=yxhb00000001&baosicode=QUJING2023001099&t=1693894962499#/insu-detail`
17. `http://mp.weixin.qq.com/s?__biz=MzU3NjY4NzY1Nw==&mid=2247490233&idx=3&sn=3ab5c637d28992c56c60ad7b9e70323a&chksm=fceed7d3b42043caed487d79151fb1b1f42ed41f88343ebe5541a5784d36d1a91ad39b7ed06e&scene=126&sessionid=1742516110#rd`
18. `http://mp.weixin.qq.com/s?__biz=MzkzMDE3Nzk3OA==&mid=2247523768&idx=2&sn=ffe05b15998844a845a36502c7fe73d8&chksm=c37c5ca4a674c3546645d6bbfeccbbb67122d47b3605e49c9c738ea98f4321d507904ff72b84&scene=126&sessionid=1743100214#rd`
19. `https://ehb.cpiccdn.com/ehb/hmbcms/cms/tk/site/ehb.cpiccdn.com/ehb/cms/cxhb/16363961/static-file/SXYHB/mengze/887412126908416000.html`
20. `http://mp.weixin.qq.com/s?__biz=MzkwODY4NTUwMA==&mid=2247486316&idx=1&sn=6a038ad375fce1d0759b2c78468e0e0a&chksm=c0c772bff7b0fba9d54c62c11e83b4658cbb60a0a2d9cb2acb5e0dac3bf61b47f917dc976e23#rd`

## 5. 正式运行前 3 条 smoke test

按要求先用 3 条真实数据试跑真实 LLM 前置验证。命令通过进程内加载 `db_to_excel_extractor/.env` 并构造 `DATABASE_URL` 环境变量，未打印完整连接串。

脱敏后的命令形态：

```bash
C:\Users\admin\AppData\Local\Programs\Python\Python314\python.exe -c "加载 db_to_excel_extractor/.env，进程内设置 DATABASE_URL，然后执行 main.py --config logs/real_db_20/db_config.runtime.yml --field-config config/field_mapping.yml --table-config config/table_mapping.yml --llm-config config/llm_config.yml --selected-ids '<前3个SourceURL>' --mode merge --limit 3 --output-dir outputs/real_db_20/smoke --log-dir logs/real_db_20/smoke --save-intermediate --no-ocr"
```

实际结果：失败，退出码 1，失败发生在读取输入阶段，未进入 LLM、HTML 解析、规则抽取、融合、Excel 输出阶段。

失败日志：

```json
{"phase": "read_input", "error": "source.table 只允许普通表名或 schema.table: temp_商业补充保险_20250523"}
```

## 6. 20 条正式测试结果

未执行 20 条正式主流程。原因：3 条 smoke test 已确认配置化数据库读取阶段被当前表名安全校验阻断。继续执行 20 条会得到同样失败，且不会产生有效 Excel。

- 输入记录数：0（项目主流程未读取成功）
- 输出结果行数：0
- 成功记录数：0
- 失败记录数：读取阶段 1 个致命失败
- 人工复核记录数：0
- OCR 触发记录数：0
- 平均 confidence_score：无
- 最低 confidence_score：无
- 字段证据数量：0
- 冲突证据数量：0

## 7. 输出验证

- `outputs/real_db_20/*.xlsx`：未生成。
- Excel 6 个 sheet 验证：未执行，原因是 Excel 未生成。
- `logs/real_db_20/smoke/run.log`：已生成。
- `logs/real_db_20/smoke/failed_records.jsonl`：已生成。
- `logs/real_db_20/smoke/extract_eval.jsonl`：未生成，原因是未进入抽取评估阶段。
- `logs/real_db_20/smoke/field_evidence.jsonl`：未生成，原因是未进入规则/LLM 证据阶段。
- `logs/real_db_20/smoke/intermediate/`：未生成，原因是未进入单条记录处理阶段。

## 8. 5 条人工抽查结论

未执行。原因：读取阶段阻断，未生成 Excel 和中间抽取文件，无法对照原文抽查结果质量。

## 9. 安全脱敏检查

执行了日志目录敏感关键词搜索：

```powershell
Select-String / grep 等价检查：password, api_key, token, secret, sk-, DATABASE_URL, LLM_API_KEY, Authorization
```

结果：

- `logs/real_db_20/db_config.runtime.yml` 命中 `${DATABASE_URL}` 占位，不是实际连接串。
- `logs/real_db_20/smoke/run.log` 命中 `ythmbtoken800001`，这是随机抽取 SourceURL 查询参数中的业务 URL 字符串，不是数据库密码、API Key 或 Authorization token。
- 未发现完整 DATABASE_URL、数据库密码、LLM_API_KEY、`sk-` API Key、Authorization、password、secret 泄露。

安全结论：本次日志和报告未发现敏感凭据明文泄露。

## 10. 失败记录详情

| source_id / info_id | 标题 | phase | error | 是否影响整体任务 | 是否需要修复代码 |
| --- | --- | --- | --- | --- | --- |
| 无，读取阶段未返回记录 | 无 | read_input | `source.table 只允许普通表名或 schema.table: temp_商业补充保险_20250523` | 是，阻断真实数据库主流程，Excel 未生成 | 需要确认修复方案 |

## 11. 问题清单

### P1：配置化数据库读取不支持当前真实表名

- 复现步骤：使用临时配置 `source.table: temp_商业补充保险_20250523` 运行配置化数据库读取。
- 实际结果：`db_reader.validate_table_name` 拒绝包含中文字符的真实表名。
- 影响范围：当前真实数据库表无法通过配置化数据库主流程读取，导致真实 20 条端到端测试无法继续，Excel 未生成。
- 严重程度：P1，影响核心真实库验收路径。
- 建议方案：不要直接放宽到任意表名；可在确认安全边界后扩展 `validate_table_name`，支持 MySQL 合法 Unicode 标识符，仍禁止反引号、分号、空白、SQL 注释和多语句；或将真实数据同步/建视图到 ASCII 安全表名后再验收。
- 本次处理：未修改核心数据库读取主逻辑，等待确认。

### P2：默认 `config/db_config.yml` 未配置真实库表名和 ID 字段

- 复现步骤：直接使用 `config/db_config.yml` 运行配置化数据库读取。
- 实际结果：`source.table`、`source.id_column`、`source.info_id_column` 为空，无法直接配置化读取。
- 影响范围：需要临时运行配置或补充正式配置。
- 建议方案：在不提交敏感信息的前提下，维护环境专用配置模板或本地忽略配置文件。
- 本次处理：使用 `logs/real_db_20/db_config.runtime.yml` 临时配置，不包含密钥。

### P3：当前根目录 `.env` 缺少真实运行必需环境变量

- 复现步骤：检查根目录 `.env` 或环境变量。
- 实际结果：`DATABASE_URL` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 均未在根目录环境中直接配置。
- 影响范围：需要从 `db_to_excel_extractor/.env` 加载旧式配置并在进程内构造 `DATABASE_URL`。
- 建议方案：按 README 准备根目录 `.env`，但不要提交真实密钥。

## 12. 修复后复测记录

- 复测时间：2026-06-30 13:58:00
- 当前 commit hash：08d0b4cf
- P1 是否已修复：已修复。`db_reader.py` 的标识符校验已安全支持中文、英文字母、数字、下划线；表名支持普通表名和单个 `schema.table`；字段名支持中文字段。仍拒绝空格、分号、引号、反引号、注释符、括号、运算符等危险输入。
- 新增测试：覆盖中文表名、`db_name.temp_商业补充保险_20250523`、中文字段名，以及危险表名/字段名拒绝。
- 单元测试：`unittest discover` 60 个通过；`pytest` 60 个通过、18 个 subtests 通过。
- 3 条 smoke test：通过，配置化数据库读取成功，真实 LLM 调用成功，生成 Excel。
- smoke Excel 路径：`C:\Users\admin\Documents\DataExtractor\outputs\real_db_20\smoke\商业补充保险抽取结果_20260630_134557.xlsx`
- 20 条真实数据测试：已重新执行，配置化数据库读取成功读取 20 条，并进入 HTML 解析、规则抽取、真实 LLM 抽取、融合和置信度评估；但正式 20 条未完整生成 Excel。
- 20 条未完整通过原因：真实 LLM API 在第 9、10 条附近返回 RPM 429 限流：`rate limit reached for RPM`。这是新的真实环境/额度问题，不是本次表名校验 P1。
- 是否生成 20 条 Excel：否。
- 20 条 Excel 路径：无。
- 结果数据行数：无，因 20 条 Excel 未生成。
- 失败记录数：至少 2 条 LLM 429 失败记录已写入 `logs/real_db_20/failed_records.jsonl`。
- 人工复核数：20 条正式 Excel 未生成，无法统计最终 sheet；运行日志中 LLM 失败记录 fallback 标记为需人工复核。
- 是否发现新的 P0/P1：发现新的 P1，真实 LLM RPM 限流导致 20 条验收未能完整完成并生成 Excel。
- git status：

```text
 M README.md
 M config.py
 M db_reader.py
 M main.py
 M tests/test_configured_db_and_fields.py
?? REAL_DB_20_TEST_REPORT.md
?? TEST_REPORT.md
?? config/llm_config.yml
```

- 安全检查：未发现完整 DATABASE_URL、数据库密码、LLM_API_KEY、`sk-` API Key 或 Authorization 明文泄露；临时执行脚本中的变量名命中已清理，`db_config.runtime.yml` 仅保留 `${DATABASE_URL}` 占位。

## 13. 修复后最终结论

- 是否成功随机抽取真实 20 条：是。
- 表名安全校验 P1 是否修复：是。
- 是否完整跑完 3 条 smoke test：是，已生成 smoke Excel。
- 是否完整跑完 20 条真实数据：否，20 条流程越过读取阶段后被真实 LLM RPM 429 限流阻断，未生成正式 Excel。
- 是否可以认为真实数据库 20 条验收通过：否。当前只能认为“中文表名/字段名安全校验 P1 已修复且 3 条真实 smoke 通过”；20 条完整验收需在 LLM 额度/限流问题处理后重跑。
- 是否建议合并：不建议以“真实数据库 20 条验收通过”的名义合并；若本次只验收 P1 表名校验修复和 smoke，通过。

## 14. 病种名称质量问题修复记录

### 14.1 问题原因

真实数据测试发现 `病种名称` 被正文规则错误抽成长句，例如 `澄迈县的李女士去年帕金森病`；同时融合优先级固定为 `数据库直接字段 > 表格规则 > 正文规则 > LLM > 默认值`，导致正文规则长句压过 LLM 给出的核心疾病名 `帕金森病`。

进一步复测还发现弱上下文规则会在长条款中扫描 `癌`、`瘤`、`综合征` 后缀，误保留国家/机构/费用场景类片段。修复后这些片段不再进入 `病种名称`。

### 14.2 修复文件

- `rule_extractor.py`：新增 `normalize_disease_name`、`is_valid_disease_name`，收紧正文规则，只保留强上下文或核心疾病词。
- `record_fusion.py`：为 `病种名称` 增加特殊融合逻辑，正文规则长句与 LLM 核心疾病名冲突时优先 LLM，双方均不可信时清空并人工复核。
- `field_mapping.py`、`config/field_mapping.yml`：增加 `疾病名称`、`特定病种`、`保障病种`、`纳入病种`、`病种范围` 等别名。
- `prompts_v2.py`：补充病种名称正反例与泛化词/费用场景禁止规则。
- `config.py`、`config_loader.py`：修复 UTF-8 BOM `.env` 读取问题，避免根目录 `.env` 中 `DATABASE_URL` 不能展开。
- `tests/test_disease_name_quality.py`、`tests/test_configured_db_and_fields.py`：新增回归测试。
- `README.md`、`DEVELOPMENT_LOG.md`、`REAL_DB_20_TEST_REPORT.md`：补充说明和验证记录。

### 14.3 新增测试

- 正文规则把 `澄迈县的李女士去年帕金森病加重` 清洗为 `帕金森病`。
- `旨在减轻被保险人因患大病`、`特药范围以及覆盖的疾病病`、`了解症`、`妥妥的花小钱保大病`、`医保定点医药机构发生的大病`、`中国居民营养与慢性病`、`合理自费费用`、`高额医疗费用`、`既往症`、`大病`、`慢性病`、`特殊病` 不进入 `病种名称`。
- `text_rule 病种名称=澄迈县的李女士去年帕金森病` 与 `llm 病种名称=帕金森病` 冲突时最终选择 LLM。
- `text_rule` 和 `llm` 均不可信时清空 `病种名称`，并记录人工复核原因 `病种名称规则和LLM均不可信`。
- 表格明确表头 `疾病名称` 时仍可映射为 `病种名称`。
- Prompt 中包含 `病种名称` 具体疾病约束和错误/正确示例。
- `.env` 带 UTF-8 BOM 时仍能读取 `DATABASE_URL`。

### 14.4 修复前错误样例

```text
澄迈县的李女士去年帕金森病
旨在减轻被保险人因患大病
特药范围以及覆盖的疾病病
了解症
妥妥的花小钱保大病
医保定点医药机构发生的大病
中国居民营养与慢性病
合理自费费用
高额医疗费用
```

### 14.5 修复后结果

- `澄迈县的李女士去年帕金森病加重` 会归一化为 `帕金森病`。
- 上述宣传语、费用说明、普通句子和泛化词不再直接写入 `病种名称`。
- 真实 20 条结果中出现的具体病种包括 `帕金森病`、`乳腺癌`、`肝癌`、`甲状腺癌`、`卵巢癌`、`高血压`、`罕见病` 等；未出现附件列出的错误长句。
- 本轮观察到的国家/机构/费用场景坏片段，如 `美国国家综合癌`、`参保群众一旦患了癌`、`高价自费癌`，最终检查无命中。

### 14.6 自动化测试结果

- `python -m unittest discover -s tests`：本机 `python` 命令不可用，按任务说明改用 `py`。
- `py -m unittest discover -s tests -v`：69 个测试通过。
- `py -m pytest -q`：69 passed，30 subtests passed。
- `py -m compileall main.py config.py config_loader.py db.py db_reader.py keyword_utils.py field_mapping.py json_utils.py excel_writer.py prompts.py prompts_v2.py llm_extractor.py table_extractor.py rule_extractor.py record_fusion.py extraction_types.py input_xlsx.py utils.py security_utils.py tests`：通过。

### 14.7 3 条 smoke 数据验证结果

- 命令：使用 `logs/real_db_20/db_config.runtime.yml`、`config/llm_config.yml`、`--selected-ids` 前 3 条、`--mode merge`、`--limit 3`、`--save-intermediate`、`--no-ocr`。
- 运行结果：通过，退出码 0，真实数据库读取成功，真实 LLM 调用成功，生成 Excel。
- 输出 Excel：`outputs/real_db_20/disease_fix_smoke/商业补充保险抽取结果_20260630_150917.xlsx`
- 结果检查：3 行结果，`病种名称` 均为空；附件列出的错误长句和 `大病/既往症/慢性病/特殊病` 泛化词无命中。

### 14.8 20 条真实数据验证结果

- 命令：使用 `logs/real_db_20/db_config.runtime.yml`、`config/llm_config.yml`、`--selected-ids` 20 条、`--mode merge`、`--limit 20`、`--save-intermediate`、`--no-ocr`。
- 运行结果：通过，退出码 0，真实数据库读取 20 条，真实 LLM 调用完成，未遇到 RPM 429，生成 Excel。
- 输出 Excel：`outputs/real_db_20/disease_fix_20/商业补充保险抽取结果_20260630_151622.xlsx`
- 结果数据：27 行，`病种名称` 非空 12 行。
- 已知错误检查：附件列出的错误长句无命中；`大病`、`既往症`、`慢性病`、`特殊病` 未作为完整 `病种名称` 出现；本轮观察到的 `美国国家综合癌`、`加拿大国立癌`、`英国癌`、`欧洲癌`、`参保群众一旦患了癌`、`高价自费癌` 等坏片段无命中。
- 字段证据：347 行。
- 冲突证据：18 行，包含病种名称特殊择优/清空原因。

### 14.9 P0/P1 结论

- 当前未发现仍阻断提交的 P0/P1。
- 20 条真实数据完整验收已经通过；此前记录的 RPM 429 限流问题本轮未复现。
- 建议可以继续提交并推送本次病种名称质量修复；后续如要继续提高质量，建议扩大样本前先补充更多人工标注样例，尤其是超长疾病责任条款中的多病种拆分口径。

### 14.10 安全说明

- 根目录 `.env` 与 `db_to_excel_extractor/.env` 均为 `.gitignore` 忽略文件，不提交真实数据库连接串或真实 LLM key。
- `config/llm_config.yml` 仅使用 `${LLM_API_KEY}` 等占位。
- 本轮提交前会再次执行敏感信息扫描；包含真实数据的 `logs/`、`outputs/` 不提交。

## 15. 2026-07-01 OCR、分页和结果页补充

### 15.1 本轮真实样本问题

样本文章：`普惠门诊保·如意版2025 保障详情`，URL `https://mp.weixin.qq.com/s/7meXk1OSTtr9-GTFxFX4HQ`。此前结果显示图片数量为 2、OCR 触发但失败，导致图片型保障责任表未抽取；同时免责/健康告知中的疾病曾被误写入 `病种名称`。

### 15.2 修复覆盖

- OCR 状态统一通过 `get_ocr_status()` 输出，API、CLI 和采集日志复用。
- OCR 不可用时，系统会在 status、前端和采集日志中明确提示，不再静默保留首轮结果。
- 有图片、无 HTML 表格、无 OCR 文本时，抽取评估会写入图片表格未识别风险。
- 支持 `--ocr-text-file` 和 `--ocr-json-file` 外部 OCR 文本 fallback，适合本机无法安装 PaddleOCR 时复测图片型表格。
- 免责/健康告知/不能投保/除外责任中的疾病不再进入 `病种名称`。
- `人员类型` 年龄范围清洗由 `tests/test_person_type_quality.py` 覆盖。

### 15.3 当前自动化验证

- 聚焦测试：20 tests OK，覆盖 OCR status、图片表格风险、外部 OCR 文本、分页、job、preview、结果页静态检查、人员类型年龄范围和免责病种过滤。
- 全量 `unittest`：107 tests OK。

### 15.4 待复测命令模板

无外部 OCR 文本时：

```powershell
py main.py --config logs/real_db_20/db_config.runtime.yml --field-config config/field_mapping.yml --table-config config/table_mapping.yml --llm-config config/llm_config.yml --selected-ids "https://mp.weixin.qq.com/s/7meXk1OSTtr9-GTFxFX4HQ" --mode merge --limit 1 --output-dir outputs/real_db_20/ocr_status_sample --log-dir logs/real_db_20/ocr_status_sample --save-intermediate --no-ocr
```

提供外部 OCR 文本时：

```powershell
py main.py --config logs/real_db_20/db_config.runtime.yml --field-config config/field_mapping.yml --table-config config/table_mapping.yml --llm-config config/llm_config.yml --selected-ids "https://mp.weixin.qq.com/s/7meXk1OSTtr9-GTFxFX4HQ" --mode merge --limit 1 --output-dir outputs/real_db_20/external_ocr_sample --log-dir logs/real_db_20/external_ocr_sample --save-intermediate --ocr-text-file local\ocr_text.txt
```

验收重点：`病种名称` 不应填入免责条款疾病，`人员类型` 不应出现 `6-65周岁`，图片表格未识别风险应写入采集日志和抽取评估；提供外部 OCR 文本后，字段证据应包含 `source=external_ocr_text`。

### 15.5 本轮复测结果

无 OCR 复测：

- 命令：使用上述 URL、`--mode merge`、`--limit 1`、`--save-intermediate`、`--no-ocr`。
- 运行结果：通过，退出码 0，真实数据库读取 1 条，真实 LLM 调用成功，生成 Excel。
- 输出目录：`outputs/real_db_20/ocr_status_sample/`。
- 结果检查：`病种名称`、`人员类型`、`区间` 均为空；未把免责条款疾病写入 `病种名称`，未把 `6-65周岁` 写入 `人员类型`。
- 采集日志：`ocr_available=false`、`ocr_triggered=true`、`ocr_skipped_reason=用户选择跳过 OCR`，`review_reason` 包含图片表格未识别风险。

外部 OCR 文本复测：

- 命令：同一 URL，提供包含 `投保年龄：6-65周岁`、`意外门诊急诊费用补偿：100000`、`免赔额100元`、`给付比例80%` 的 `--ocr-text-file`。
- 运行结果：通过，退出码 0，真实数据库读取 1 条，真实 LLM 调用成功，生成 Excel。
- 输出目录：`outputs/real_db_20/external_ocr_sample/`。
- 结果检查：`补助限额=100000元`、`报销比例=80%`、`备注=投保年龄：6-65周岁`；`人员类型` 和 `病种名称` 为空。
- 字段证据：包含 `source=external_ocr_text`。
