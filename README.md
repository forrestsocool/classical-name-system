# 好名书中来 · 微信小程序版

本分支将选名入口迁移到微信小程序。小程序通过 HTTPS 访问 `name.wxapp.655567.xyz`，经已有 EdgeOne CDN 回源到 `name.sensen.li`；服务器用微信登录码换取可信身份并签发会话。古籍召回、模型审稿、持续入库和 PostgreSQL 均运行在自有服务器。服务器网页提供管理后台。

- [划卡改造方案](千千嘉名划卡改造方案.md)：打开即划卡、共享队列和曝光迁移。
- [生产部署说明](部署/生产部署说明.md)：数据库迁移、云函数、小程序、管理与备份。
- [当前环境体验与复核](部署/当前环境体验与复核.md)：线上入口、首次导入、测试号与云环境关联、已修复问题和验证边界。
- [唐诗、宋词来源](古籍与东亚年号参考资料/诗词来源/README.md)：选集原文、来源记录与增量导入流程。
- [旧版个人版说明](部署/旧版个人版说明.md)：SQLite 和浏览器版的历史资料，不是当前部署入口。

## 运行结构

| 目录 / 入口 | 职责 |
| --- | --- |
| `小程序/` | 单双字切换、滑卡、出处、收藏、比较、反馈 |
| `后端/HTTPS接入.py` | 正式 HTTPS 入口、微信可信身份、短期会话和动作鉴权 |
| `云函数/nameGateway/` | 保留旧版客户端的兼容入口；新版不调用 |
| `后端/小程序服务.py` | 新版 FastAPI；内部业务接入与独立管理 API |
| `后端/持续生产.py` | 常驻生产进程；单双字队列轮换、可选预算、失败退避 |
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

管理后台：`http://127.0.0.1:8000/admin`。小程序使用正式 AppID `wx3d9171fa1ecde642`，通过 `wx.login` 获取登录码，再使用 `wx.request` 调用 `https://name.wxapp.655567.xyz/api/v1/dispatch`。服务器必须配置 `WECHAT_APP_SECRET` 和会话签名密钥 `GATEWAY_SECRET`；两者均不进入小程序包。公众平台 request 合法域名须包含该 HTTPS 域名，开发者工具保持域名校验。原 AppID + OpenID 派生用户编号不变，已有收藏与偏好继续使用。实际部署与体验版状态见体验文档。

`https://<envId>.api.tcloudbasegateway.com/v1/ai/cloudbase` 是 CloudBase AI 模型的 Base URL，不是业务云函数入口；环境 API Key 只允许放在服务器或云函数环境变量中。

迁移默认读取 `构建产物/起名系统.sqlite3`。上线必须使用**生产库的一致性备份**，不要以仓库样本覆盖生产数据。目标 PostgreSQL 已初始化时迁移会拒绝写入。

## 生产行为

生产器只维护单字名、双字名两份共享库存，与用户是否在线无关；管理员可以分别暂停。`PRODUCER_DAILY_BATCHES=0` 表示持续生产，正数表示 UTC 日批次上限，失败调用也计入。候选经过模型审稿，公开发卡要求评分不低于 85，并排除完整年号资料。

名字详情支持通过微信发送给朋友或群聊。分享链接只含随机标识，不携带发送人的姓氏或筛选条件；收件人可直接查看出处和释义，点击收藏后该出处才写入自己的投递与收藏。朋友圈分享需另做无需登录的单页展示，当前版本未开启。

新版本按 OPENID 派生的用户编号和名字记录曝光；同一个请求编号重试返回同一批。没有租约、活跃订阅、临时私有池或布隆过滤器。同一微信用户的收藏跨设备同步；旧浏览器匿名收藏只作为历史数据保存，不自动绑定微信用户。

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
