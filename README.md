# 古籍智能起名系统

基于古籍典故、音形义、五行八字、受控随机和大语言模型的中文起名网站。

## 项目能力

- 从《论语》《礼记》《尚书》《楚辞》《周易》《孟子》《庄子》《诗经》《周礼》中检索典故。
- 汇总中国、朝鲜半岛、越南、日本历史年号，支持年号搜索和详情查看。
- 支持单姓、复姓、单字名、双字名、固定字、避用字和名字排除。
- 支持温润君子、胸怀天下、智慧通达、坚毅担当、自由洒脱、文采气质、安宁福泽七个方向。
- 支持出生时间、时区和日界规则计算四柱及五行统计。
- 支持指定喜用五行，也支持不输入出生信息的纯典故起名。
- 使用随机种子保证同一条件下可复现，并支持“换一批”。
- 支持收藏、比较、反馈、历史任务和管理复核流程。
- 支持兼容 OpenAI 接口的大语言模型；模型输出必须通过本地名字、字符、典故和方向校验。
- 支持就绪检查、健康检查、请求限流、质量统计、数据库备份和反向代理。

## 技术栈

- 前端：原生 HTML、CSS、JavaScript
- 后端：Python、FastAPI、Uvicorn
- 数据库：SQLite
- 历法：`lunar-python`
- 拼音：`pypinyin`
- 模型接口：兼容 OpenAI `chat/completions` 的 JSON 接口
- 部署：Caddy 或其他反向代理

## 快速运行

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r 后端/requirements.txt
$env:起名管理密钥 = "请替换为至少16位ASCII密钥"
python 脚本/部署检查.py
python -m uvicorn 后端.起名服务:应用 --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000`。

也可以执行：

```powershell
$env:起名管理密钥 = "请替换为至少16位ASCII密钥"
.\启动服务.ps1
```

`起名管理密钥`必须至少 16 个字符，并且只能使用 ASCII 字符。不要把真实密钥写入 Git。

## 配置

`.env.example` 是配置模板。当前服务通过环境变量读取配置，PowerShell 示例：

```powershell
$env:起名管理密钥 = "替换为随机生成的长密钥"
$env:起名每分钟上限 = "60"
$env:起名模型地址 = "https://api.openai.com/v1/chat/completions"
$env:起名模型密钥 = ""
$env:起名模型名称 = ""
```

模型配置说明：

- 未设置模型密钥或模型名称时，使用本地规则候选。
- 设置模型地址、模型密钥和模型名称后，服务调用兼容接口生成补充候选。
- 模型只能提供建议和解释，不能绕过本地出处校验。
- 模型候选会记录调用状态、耗时、令牌数和估算成本；管理接口不会返回密钥。

## 目录结构

```text
前端/                         网页界面
后端/                         起名服务、八字计算、候选生成、缓存、模型接口
古籍与东亚年号参考资料/       古籍文本和东亚历史年号文本
资料配置/                     初始典故词组、核验片段、汉字五行配置
构建产物/                     SQLite 数据库、审计报告、复核清单、诗经结构和周易字形清单
脚本/                         审计、建库、复核、备份、部署检查
部署/                         Caddy 配置、健康检查、生产部署说明
测试/                         Python 自动化测试
起名系统方案.md               完整设计方案和开发状态
启动服务.ps1                  Windows 启动脚本
```

## 参考资料和数据库

原始资料位于 `古籍与东亚年号参考资料/`，原文不直接覆盖。数据库文件为 `构建产物/起名系统.sqlite3`，主要表包括：

- `sources`、`books`、`passages`：来源、古籍、古籍片段
- `eras`：中国、朝鲜半岛、越南、日本历史年号，含来源行、记录类型和人物字段
- `directions`、`direction_keywords`：文化方向和关键词
- `candidate_phrases`：典故候选词组
- `characters`、`character_elements`：汉字、拼音和五行规则
- `audit_issues`：资料审计问题
- `name_runs`、`candidates`：起名任务和候选名字
- `model_candidates`、`model_metrics`：模型候选和调用指标
- `favorites`、`feedback`：收藏、比较和反馈

重新审计、建库和生成复核清单：

```powershell
python 脚本/审计参考资料.py
python 脚本/生成复核清单.py
python 脚本/生成诗经篇章结构.py
python 脚本/核验周易字形.py
python 脚本/建立资料数据库.py
```

备份数据库：

```powershell
python 脚本/备份数据库.py
```

备份文件放在 `构建产物/数据库备份/`，该目录不会提交到 Git。

当前数据库基线：9 部古籍、8554 个古籍片段、2099 条历史年号、10 个典故词组、5829 个汉字记录。

`构建产物/诗经篇章结构.json` 已按原始行号整理出 305 篇、30 个分区和正式篇名。正式篇名配置位于 `资料配置/诗经正式篇名.json`，六篇有题无辞的笙诗只保留目录说明，不伪造正文。

`构建产物/周易字形核验.json` 逐字记录 79 个“干”字的语境建议，已完成“乾”与“干”的语境分类。`构建产物/展示资料/周易-规范化展示.txt` 只应用高置信“乾”字建议，原始正文仍保留，避免把“干事”“干城”等不同义项误改。

生产发布使用 `部署/prometheus.yml` 抓取 `/metrics`，`部署/起名系统告警.yml` 提供目标不可用、错误率和耗时告警。发布前执行 `python 脚本/生产压测.py --地址 http://127.0.0.1:8000 --请求数 30 --并发数 5`，脚本会验证健康、就绪、检索、起名四类请求，并清理压测任务。

## 主要接口

### 用户接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 查看服务和资料数量 |
| GET | `/api/ready` | 检查数据库完整性和可生成片段 |
| GET | `/metrics` | 输出 Prometheus 请求指标 |
| POST | `/api/bazi` | 计算四柱和五行统计 |
| GET | `/api/model/status` | 查看模型是否已配置 |
| GET | `/api/search` | 搜索古籍片段 |
| GET | `/api/directions` | 获取文化方向 |
| GET | `/api/eras` | 搜索历史年号 |
| GET | `/api/eras/{id}` | 查看年号详情 |
| GET | `/api/passages/{id}` | 查看古籍出处详情 |
| GET | `/api/characters/{char}` | 查看汉字、拼音和五行 |
| POST | `/api/name-runs` | 创建起名任务 |
| GET | `/api/name-runs` | 查看任务历史 |
| GET | `/api/name-runs/{id}` | 查看任务详情 |
| DELETE | `/api/name-runs/{id}` | 删除任务及关联数据 |
| POST | `/api/name-runs/{id}/model-candidates` | 生成模型补充候选 |
| GET | `/api/name-runs/{id}/model-candidates` | 查看模型候选 |
| POST | `/api/favorites` | 收藏候选 |
| GET | `/api/favorites` | 查看收藏 |
| DELETE | `/api/favorites/{id}` | 删除收藏 |
| POST | `/api/favorites/compare` | 比较收藏名字 |
| POST | `/api/feedback` | 提交候选反馈 |

### 管理接口

管理接口必须携带 `X-Admin-Key` 请求头：

- `GET /api/admin/review-queue`：古籍片段复核队列
- `POST /api/admin/passages/{id}/review`：复核古籍片段
- `GET /api/admin/element-queue`：汉字五行复核队列
- `POST /api/admin/characters/{char}/element-review`：复核汉字五行
- `GET /api/admin/audit-queue`：资料审计问题队列
- `POST /api/admin/audit-issues/{id}/review`：处理审计问题
- `GET /api/admin/metrics`：查看反馈、模型调用和成本统计

## 起名流程

```text
用户输入
  -> 八字计算和五行统计
  -> 方向、字数、固定字、避用字和五行约束
  -> SQLite 检索已核验典故
  -> 本地候选生成和受控随机排序
  -> 音形义、五行、出处和禁用条件校验
  -> 可选的大语言模型补充
  -> 本地引用校验
  -> 候选、出处、解释和任务记录
```

八字只作为可选的文化参考。系统会展示计算规则和五行统计，不将结果表述为科学预测或确定性结论。

## 部署

单机部署：

```powershell
$env:起名管理密钥 = "替换为随机生成的长密钥"
.\启动服务.ps1 -绑定地址 127.0.0.1 -端口 8000 -工作进程 1
```

生产环境建议：

1. 使用防火墙限制应用端口，只开放反向代理端口。
2. 使用 `部署/Caddyfile` 将外部请求代理到 `127.0.0.1:8000`。
3. 使用 `部署/健康检查.ps1` 定期检查 `/api/ready`。
4. 使用 `脚本/备份数据库.py` 做定期备份，并把备份复制到独立存储。
5. SQLite 模式固定使用一个工作进程；扩展并发前应先迁移到服务型数据库。

健康检查：

```powershell
.\部署\健康检查.ps1 -地址 http://127.0.0.1:8000
```

## 测试和质量检查

本地测试：

```powershell
python -m unittest discover -s 测试 -p "test*.py" -v
python -m compileall -q 后端 脚本 测试
node --check 前端/app.js
$env:起名管理密钥 = "ci-test-admin-key-2026"
python 脚本/部署检查.py
```

GitHub Actions 工作流位于 `.github/workflows/测试.yml`，会在推送和拉取请求时执行 Python 测试、前端语法检查和数据库部署检查。

本地轻量压测：

```powershell
python 脚本/压测服务.py --地址 http://127.0.0.1:8000 --模式 检索 --请求数 30 --并发数 5
python 脚本/压测服务.py --地址 http://127.0.0.1:8000 --模式 起名 --请求数 10 --并发数 3
```

起名模式会在完成后删除本轮任务。服务启动后可将 `/metrics` 接入 Prometheus；指标只记录方法、归一化路径、状态和耗时，不记录查询参数、请求正文或出生资料。

## 安全和隐私

- 出生时间只用于当前任务的八字计算，接口返回结果会隐去原始时间。
- 服务不记录真实管理密钥和模型密钥。
- 管理接口使用 ASCII 密钥和常量时间比较。
- 接口包含基本安全响应头、请求限流和输入长度限制。
- `.env`、Python 缓存和数据库备份已加入 `.gitignore`。
- 发布前应检查日志、数据库、配置文件和 Git 提交，确认没有真实密钥和真实个人信息。

## 当前限制

- 古籍文本、篇章边界、错字和出处仍需继续人工抽样复核。
- 汉字五行是可替换规则数据，不同流派之间可能存在差异。
- 八字计算需要用户确认出生时间、时区、历法和日界规则。
- 模型接口需要用户自行提供兼容服务和密钥。
- 当前 SQLite 适合单机或低并发场景，尚未完成生产压力测试和完整监控接入。

## 开发状态

当前版本已完成首版网页、SQLite 数据库、资料导入、典故候选、八字五行、模型适配、收藏反馈、历史任务、管理复核、部署检查、健康检查和 GitHub 自动测试。

后续重点是扩大人工核验范围、完善汉字五行数据、增加压力测试和接入生产监控。
