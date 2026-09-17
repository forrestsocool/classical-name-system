# 拾名 · 微信小程序版

本分支将选名入口迁移到微信小程序。CloudBase 云函数负责微信身份与签名接入；古籍召回、模型审稿、持续入库和 PostgreSQL 全部运行在自有服务器。服务器网页只提供管理后台。

- [改造方案](小程序改造方案.md)：职责边界、队列简化取舍与迁移策略。
- [生产部署说明](部署/生产部署说明.md)：数据库迁移、云函数、小程序、管理与备份。
- [旧版个人版说明](部署/旧版个人版说明.md)：SQLite 和浏览器版的历史资料，不是当前部署入口。

## 运行结构

| 目录 / 入口 | 职责 |
| --- | --- |
| `小程序/` | 发现、固定字/避用字筛选、滑卡、出处、收藏、比较、反馈 |
| `云函数/nameGateway/` | 微信可信身份、动作白名单、HMAC 签名、HTTPS 转发 |
| `后端/小程序服务.py` | 新版 FastAPI；内部业务接入与独立管理 API |
| `后端/持续生产.py` | 常驻生产进程；持久化来源轮换、每日预算、失败退避 |
| `后端/迁移/` | PostgreSQL 资料、历史记录和新业务表 |
| `管理前端/` | 独立管理台，入口 `/admin` |
| `脚本/迁移PostgreSQL.py` | 只读 SQLite 快照 → 空 PostgreSQL，一次事务迁移 |
| `脚本/备份PostgreSQL.py` | 调用 pg_dump 创建自定义格式备份 |

旧的 `前端/`、`后端/起名服务.py`、`后端/候选队列.py` 保留供旧版回归和迁移参考。Docker 和启动脚本均使用新服务，不发布旧页面、浏览器匿名接口或同步模型生成入口。

## 快速启动

先阅读部署说明，再在项目根目录操作：

```sh
cp .env.example .env
# 填入随机数据库密码、独立管理密钥、网关共享密钥和真实小程序 APPID
docker compose build
docker compose up -d postgres
docker compose run --rm migrate
docker compose up -d api producer
```

管理后台：`http://127.0.0.1:8000/admin`。新用户使用微信开发者工具导入项目根目录，填写真实 AppID 与 `小程序/config.js` 的云环境 ID，部署 `nameGateway` 云函数。

迁移默认读取 `构建产物/起名系统.sqlite3`。上线必须使用**生产库的一致性备份**，不要以仓库样本覆盖生产数据。目标 PostgreSQL 已初始化时迁移会拒绝写入。

## 生产行为

生产档案按姓氏和名字长度持久化。初始档案来自 `PRODUCER_SURNAMES`，用户拉卡会登记新的条件档案；离线后档案仍持续生产，管理员可以暂停。固定字和避用字只做库存筛选，不触发专属模型任务。库存永久积累，全天生产受 `PRODUCER_DAILY_BATCHES` 限制，额度按 UTC 日切换且失败调用也计入。

新版本在发卡时记录去重；同一个请求编号重试返回同一批。没有租约、活跃订阅、临时私有池或布隆过滤器。同一微信用户的收藏跨设备同步；旧浏览器匿名收藏只作为历史数据保存，不自动绑定微信用户。

## 测试

```sh
python -m pip install -r 测试/requirements.txt
# 本地 PostgreSQL 测试账户需要 CREATE DATABASE 权限；测试自行创建并删除随机测试库
export TEST_DATABASE_URL=postgresql://postgres:password@127.0.0.1:5432/postgres
python -m unittest discover -s 测试 -p "test*.py" -v
node --test 测试/wechat.test.js
python -m compileall -q 后端 脚本 测试
```

未设置 `TEST_DATABASE_URL` 时新 PostgreSQL 集成测试明确跳过。CI 提供 PostgreSQL 17，并实际执行这些测试。测试使用模拟模型，不产生模型费用。微信开发者工具编译、真机云调用与发布审核需要真实微信配置。
