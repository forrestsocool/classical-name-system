# 1996—2026 高考状元姓名来源

这一路来源收录各省（含直辖市、自治区）1996—2026 年公开汇总的高考状元姓名。1996—2019 年主要是文科、理科；2020 年后同时保留原表中的物理类、历史类、综合等新高考类别，2026 年补充最新公开汇总中有明确姓名的记录。当前选择“状元”口径，是因为公开网络资料无法稳定提供每个省份每年的前 100 名完整名单；数据模型保留并列状元、学校、分数（若原表有）和原始行号。

## 来源与复现

- 原始页面：[Pastebin 汇总页](https://pastebin.com/z3XiLUfa)
- 原始表格：[Pastebin 原文](https://pastebin.com/raw/z3XiLUfa)
- 原始文件：`raw_data/pastebin-z3XiLUfa.txt`
- 原始文件哈希：`0de07e0163fe6612a5a2dca005700f06bc759b6e200f7e63ecdc440ddcfa33cd`
- 清洗结果：`data/gaokao_champions_1996_2026.json`
- 审阅报告：`data/review_report.md`（覆盖统计、类别归类、2026 明确姓名记录、拒绝项和复核建议）

执行以下命令可重新下载和清洗。清洗不会覆盖规则外的记录到候选池：

```powershell
python scripts/crawler.py --download
python scripts/crawler.py --normalize
python scripts/build_review_report.py
```

清洗结果当前为 1947 条记录、1560 个一字或两字名，覆盖 31 个省级地区。当前公开快照没有 2024、2025 的可复用结构化行，`manifest.missing_years` 会明确列出年份空档；后续补充来源后可直接重新清洗。空姓名、脱敏姓名、无法拆成一字或两字名的记录只计入 `manifest.rejected`，不会进入小程序；各条记录的 `subject` 保留原始类别，方便区分年份、文科/理科与新高考类别。

## 入库

```powershell
python 脚本/导入高考状元来源.py
python 脚本/导入高考状元来源.py --apply
```

导入前停止持续生产进程并备份 PostgreSQL。导入使用共享的单字名、双字名档案，来源名为“历年高考状元”，原始年份、省份、文理科、姓名和学校保存在卡片 payload；来源标记为 `高考状元`，不会被模型生产器重复消费。

这是网络二次汇总资料，来源状态保持“待核验”。上线前如需更高可信度，应按省份和年份补充教育考试院、地方志或主流媒体的一手页面，并逐条替换或复核原表记录。
