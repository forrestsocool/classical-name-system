"""持久化物料池、按书生产、可回收投递与精确曝光去重。网络不占用数据库事务。"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sqlite3
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Event, Lock, Thread

from .智能筛选 import 批量召回, 模型筛选单批, 补充解释
from .模型接口 import 读取环境配置, 模型已配置, 验证模型地址


def 编码(值):
    return json.dumps(值, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def 摘要(值):
    return hashlib.sha256(值.encode()).hexdigest()


class 布隆过滤器:
    字节数 = 16384

    def __init__(self, 数据=None):
        self.位 = bytearray(数据 if 数据 is not None else b"\0" * self.字节数)

    def 位置(self, 名字):
        数据 = hashlib.sha256(名字.encode()).digest()
        return [int.from_bytes(数据[i:i+4], "big") % (self.字节数 * 8) for i in range(0, 24, 4)]

    def 包含(self, 名字):
        return all(self.位[i // 8] & (1 << (i % 8)) for i in self.位置(名字))

    def 添加(self, 名字):
        for i in self.位置(名字):
            self.位[i // 8] |= 1 << (i % 8)


class 候选队列:
    def __init__(self, 路径, 自动生产=True):
        self.路径 = str(路径)
        self.停止 = Event()
        self.锁 = Lock()
        self.在途 = set()
        self.线程 = None
        self.执行器 = ThreadPoolExecutor(max_workers=8, thread_name_prefix="按书生产")
        self.高水位 = max(12, int(os.getenv("起名队列库存", "72")))
        self.每日上限 = max(0, int(os.getenv("起名每日生产批次", "480")))
        self.临时秒数 = max(30, int(os.getenv("起名临时队列秒数", "300")))
        self.活跃秒数 = 90
        self.租期 = 300
        with self.连接() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript("""
                CREATE TABLE IF NOT EXISTS feed_pools (
                    id TEXT PRIMARY KEY, conditions TEXT NOT NULL, private INTEGER NOT NULL,
                    touched REAL NOT NULL, cursor INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS feed_materials (
                    pool TEXT NOT NULL, name TEXT NOT NULL, book TEXT NOT NULL,
                    payload TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(pool,name));
                CREATE INDEX IF NOT EXISTS feed_material_books ON feed_materials(pool,book);
                CREATE TABLE IF NOT EXISTS feed_subscribers (
                    pool TEXT NOT NULL, owner TEXT NOT NULL, touched REAL NOT NULL,
                    PRIMARY KEY(pool,owner));
                CREATE TABLE IF NOT EXISTS feed_exposures (
                    owner TEXT NOT NULL, name TEXT NOT NULL, book TEXT NOT NULL,
                    shown REAL NOT NULL, PRIMARY KEY(owner,name));
                CREATE INDEX IF NOT EXISTS feed_recent ON feed_exposures(owner,shown);
                CREATE TABLE IF NOT EXISTS feed_blooms (owner TEXT PRIMARY KEY, bits BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS feed_leases (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, pool TEXT NOT NULL,
                    name TEXT NOT NULL, book TEXT NOT NULL, card TEXT NOT NULL,
                    expires REAL NOT NULL, UNIQUE(owner,name));
                CREATE TABLE IF NOT EXISTS feed_receipts (
                    owner TEXT NOT NULL, request TEXT NOT NULL, pool TEXT NOT NULL,
                    payload TEXT NOT NULL, expires REAL NOT NULL, PRIMARY KEY(owner,request));
                CREATE TABLE IF NOT EXISTS feed_deliveries (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                    book TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS feed_attempts (
                    pool TEXT NOT NULL, book TEXT NOT NULL, name TEXT NOT NULL,
                    PRIMARY KEY(pool,book,name));
                CREATE TABLE IF NOT EXISTS feed_sources (
                    pool TEXT NOT NULL, book TEXT NOT NULL, retry REAL NOT NULL DEFAULT 0,
                    failures INTEGER NOT NULL DEFAULT 0, batches INTEGER NOT NULL DEFAULT 0,
                    accepted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(pool,book));
                CREATE TABLE IF NOT EXISTS feed_budget (day TEXT PRIMARY KEY, batches INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS feed_errors (
                    pool TEXT NOT NULL, book TEXT NOT NULL, category TEXT NOT NULL,
                    updated REAL NOT NULL, PRIMARY KEY(pool,book));
                CREATE TABLE IF NOT EXISTS run_owners (run_id TEXT PRIMARY KEY, owner TEXT NOT NULL);
            """)
        if 自动生产:
            self.线程 = Thread(target=self.调度循环, name="名字库存调度", daemon=True)
            self.线程.start()

    @contextmanager
    def 连接(self):
        c = sqlite3.connect(self.路径, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            with c:
                yield c
        finally:
            c.close()

    def 关闭(self):
        self.停止.set()
        if self.线程:
            self.线程.join(timeout=3)
        self.执行器.shutdown(wait=True, cancel_futures=True)

    def 身份(self, 会话, 指纹):
        # 指纹是设备标识，不是认证密钥。不能凭猜测指纹访问另一收藏夹。
        return 摘要(会话 + ":" + 指纹)

    def 清理(self, c, 现在):
        c.execute("DELETE FROM feed_leases WHERE expires < ?", (现在,))
        c.execute("DELETE FROM feed_receipts WHERE expires < ?", (现在,))
        c.execute("DELETE FROM feed_deliveries WHERE created < ?", (现在-30*86400,))
        c.execute("DELETE FROM feed_subscribers WHERE touched < ?", (现在-self.活跃秒数,))
        过期 = c.execute("SELECT id FROM feed_pools WHERE (private=1 AND touched<?) OR touched<?",
                       (现在-self.临时秒数, 现在-7*86400)).fetchall()
        for 池 in 过期:
            for 表 in ("feed_materials", "feed_attempts", "feed_sources", "feed_subscribers", "feed_leases", "feed_receipts", "feed_errors"):
                c.execute(f"DELETE FROM {表} WHERE pool=?", (池[0],))
            c.execute("DELETE FROM feed_pools WHERE id=?", (池[0],))

    def 拉取(self, 会话, 指纹, 条件, 请求号, 数量=8):
        现在 = time.time()
        所有者 = self.身份(会话, 指纹)
        私有 = bool(条件.get("必须包含") or 条件.get("关键词"))
        池号 = 摘要(编码(条件) + (所有者 if 私有 else ""))
        with self.连接() as c:
            c.execute("BEGIN IMMEDIATE")
            self.清理(c, 现在)
            if not c.execute("SELECT 1 FROM feed_pools WHERE id=? AND touched>?", (池号, 现在-self.活跃秒数)).fetchone():
                if c.execute("SELECT COUNT(*) FROM feed_pools WHERE touched>?", (现在-self.活跃秒数,)).fetchone()[0] >= 32:
                    raise ValueError("当前准备中的条件较多，请稍后再试")
            c.execute("INSERT INTO feed_pools(id,conditions,private,touched) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET touched=excluded.touched",
                      (池号, 编码(条件), int(私有), 现在))
            c.execute("INSERT INTO feed_subscribers VALUES(?,?,?) ON CONFLICT(pool,owner) DO UPDATE SET touched=excluded.touched", (池号, 所有者, 现在))
            旧 = c.execute("SELECT payload,pool FROM feed_receipts WHERE owner=? AND request=?", (所有者, 请求号)).fetchone()
            if 旧:
                if 旧["pool"] != 池号:
                    raise ValueError("请求编号不能用于不同条件")
                响应 = json.loads(旧["payload"])
                响应["卡片"] = [卡 for 卡 in 响应["卡片"] if c.execute(
                    "SELECT 1 FROM feed_leases WHERE id=? AND owner=?", (卡["投递编号"], 所有者)).fetchone()
                    and c.execute("SELECT 1 FROM name_runs WHERE id=?", (卡["任务编号"],)).fetchone()]
                return 响应
            已租 = c.execute("SELECT name,book FROM feed_leases WHERE owner=?", (所有者,)).fetchall()
            已租名 = {x["name"] for x in 已租}
            数量 = min(数量, max(0, 36-len(已租)))
            位行 = c.execute("SELECT bits FROM feed_blooms WHERE owner=?", (所有者,)).fetchone()
            布隆 = 布隆过滤器(位行[0] if 位行 else None)
            材料 = c.execute("""SELECT m.name,m.book,m.payload FROM feed_materials m JOIN passages p
                ON p.id=json_extract(m.payload,'$.来源片段编号') WHERE m.pool=? AND p.status IN ('已核验','待核验')""", (池号,)).fetchall()
            可选 = []
            for x in 材料:
                if x["name"] in 已租名:
                    continue
                # 布隆误判只能增加一次查询，绝不能误丢可用物料。
                if 布隆.包含(x["name"]) and c.execute("SELECT 1 FROM feed_exposures WHERE owner=? AND name=?", (所有者, x["name"])).fetchone():
                    continue
                可选.append(json.loads(x["payload"]))
            最近 = c.execute("SELECT name,book FROM feed_exposures WHERE owner=? ORDER BY shown DESC LIMIT 36", (所有者,)).fetchall()
            书次数 = Counter(x["book"] for x in [*最近, *已租])
            最近名 = [x["name"][len(条件["姓氏"]):] for x in 最近[:8]]
            上书 = 最近[0]["book"] if 最近 else None
            random.SystemRandom().shuffle(可选)
            选中 = []
            本批书 = Counter()
            while 可选 and len(选中) < 数量:
                # 首批只有一个来源先完成时最多交付两张，留空间给仍在生产的书籍。
                范围 = [x for x in 可选 if 本批书[x["书名"]] < 2]
                if not 范围:
                    break
                def 分值(x):
                    重字 = sum(len(set(x["名字"]) & set(n)) for n in 最近名[-8:])
                    return (书次数[x["书名"]], x["书名"] == 上书, 重字, -x["基础分"])
                项 = min(范围, key=分值)
                可选.remove(项)
                选中.append(项)
                上书 = 项["书名"]
                本批书[上书] += 1
                书次数[上书] += 1
                最近名.append(项["名字"])
            卡片 = self.保存投递(c, 会话, 所有者, 池号, 条件, 选中, 现在)
            错误数 = c.execute("SELECT COUNT(*) FROM feed_sources WHERE pool=? AND failures>0", (池号,)).fetchone()[0]
            结果 = {"队列编号": 池号, "卡片": 卡片, "状态": "就绪" if 卡片 else "准备中", "重试秒数": 4,
                    "提示": "部分来源准备较慢，正在自动重试" if 错误数 else "正在从不同古籍挑选名字"}
            今日 = datetime.now(timezone.utc).date().isoformat()
            预算 = c.execute("SELECT batches FROM feed_budget WHERE day=?", (今日,)).fetchone()
            if (预算 and 预算[0] >= self.每日上限) or self.每日上限 == 0:
                结果.update({"重试秒数":30,"提示":"后台已达到今日生产上限，已有名字仍可继续看"})
            elif c.execute("SELECT COUNT(*) FROM feed_sources WHERE pool=? AND retry>? AND failures=0", (池号, 现在+600)).fetchone()[0] >= 9:
                结果.update({"重试秒数":30,"提示":"当前条件下的原文候选已审读完，可调整固定字或避用字"})
            c.execute("INSERT INTO feed_receipts VALUES(?,?,?,?,?)", (所有者, 请求号, 池号, 编码(结果), 现在+self.租期))
            return 结果

    def 保存投递(self, c, 会话, 所有者, 池号, 条件, 选中, 现在):
        if not 选中:
            return []
        任务 = str(uuid.uuid4())
        c.execute("INSERT INTO name_runs(id,request_json,bazi_json,random_seed,rule_version,status,created_at) VALUES(?,?,NULL,0,'来源队列1.0','完成',?)",
                  (任务, 编码(条件), datetime.now(timezone.utc).isoformat()))
        c.execute("INSERT INTO run_owners VALUES(?,?)", (任务, 摘要(会话)))
        卡片 = []
        for 项 in 选中:
            c.execute("""INSERT INTO candidates(run_id,full_name,given_name,book,section_title,source_passage_id,
                      source_text,source_offset,direction,wuxing_json,pinyin,pinyin_tone,origin_type,base_score)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (任务, 项["姓名"], 项["名字"], 项["书名"], 项["篇章"],
                      项["来源片段编号"], 项["原文"], 项["原文位置"], 项.get("方向", ""), 编码(项.get("五行匹配", {})),
                      项.get("拼音", ""), 项.get("拼音带调", ""), 项["取字方式"], 项["基础分"]))
            编号 = uuid.uuid4().hex
            卡 = {"项目": 项, "任务编号": 任务, "投递编号": 编号, "到期时间": (现在+self.租期)*1000}
            c.execute("INSERT INTO feed_leases VALUES(?,?,?,?,?,?,?)", (编号, 所有者, 池号, 项["姓名"], 项["书名"], 编码(卡), 现在+self.租期))
            c.execute("INSERT INTO feed_deliveries VALUES(?,?,?,?,?)", (编号, 所有者, 项["姓名"], 项["书名"], 现在))
            卡片.append(卡)
        return 卡片

    def 确认(self, 会话, 指纹, 已展示, 续租, 释放, 池号=None):
        所有者, 现在 = self.身份(会话, 指纹), time.time()
        with self.连接() as c:
            c.execute("BEGIN IMMEDIATE")
            位行 = c.execute("SELECT bits FROM feed_blooms WHERE owner=?", (所有者,)).fetchone()
            布隆 = 布隆过滤器(位行[0] if 位行 else None)
            已确认数 = 0
            for 编号 in 已展示:
                行 = c.execute("SELECT * FROM feed_deliveries WHERE id=? AND owner=?", (编号, 所有者)).fetchone()
                if 行:
                    已确认数 += 1
                    c.execute("INSERT OR IGNORE INTO feed_exposures VALUES(?,?,?,?)", (所有者, 行["name"], 行["book"], 现在))
                    布隆.添加(行["name"])
                    c.execute("DELETE FROM feed_leases WHERE owner=? AND name=?", (所有者, 行["name"]))
            if 已确认数:
                c.execute("INSERT INTO feed_blooms VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET bits=excluded.bits", (所有者, bytes(布隆.位)))
            for 编号 in 续租:
                c.execute("UPDATE feed_leases SET expires=? WHERE id=? AND owner=? AND expires>?", (现在+self.租期, 编号, 所有者, 现在))
            for 编号 in 释放:
                c.execute("DELETE FROM feed_leases WHERE id=? AND owner=?", (编号, 所有者))
            if 池号:
                已订阅 = c.execute("UPDATE feed_subscribers SET touched=? WHERE pool=? AND owner=?", (现在, 池号, 所有者)).rowcount
                if 已订阅:
                    c.execute("UPDATE feed_pools SET touched=? WHERE id=?", (现在, 池号))
            有效 = [x[0] for x in c.execute("SELECT id FROM feed_leases WHERE owner=? AND expires>?", (所有者, 现在))]
            return {"状态": "已同步", "有效租约": 有效}

    def 调度循环(self):
        while not self.停止.wait(1):
            try:
                self.调度一次()
            except Exception:
                # 不记录模型凭据或包含原始请求的异常。下轮自动恢复数据库短暂繁忙。
                self.停止.wait(3)

    def 调度一次(self):
        with self.锁:
            空位 = 8-len(self.在途)
        if 空位 <= 0:
            return
        现在 = time.time()
        今日 = datetime.now(timezone.utc).date().isoformat()
        待发 = []
        with self.连接() as c:
            c.execute("BEGIN IMMEDIATE")
            self.清理(c, 现在)
            c.execute("INSERT OR IGNORE INTO feed_budget VALUES(?,0)", (今日,))
            已用 = c.execute("SELECT batches FROM feed_budget WHERE day=?", (今日,)).fetchone()[0]
            空位 = min(空位, self.每日上限-已用)
            池列表 = c.execute("SELECT * FROM feed_pools WHERE touched>? ORDER BY touched", (现在-self.活跃秒数,)).fetchall()
            书目 = [x[0] for x in c.execute("SELECT DISTINCT b.name FROM books b JOIN passages p ON p.book_id=b.id WHERE p.status IN ('已核验','待核验') ORDER BY b.name")]
            # 跨队列逐轮各派一批，不让首个用户包办全部并发。
            for _ in range(8):
                for 池 in 池列表:
                    if len(待发) >= 空位 or not 书目:
                        break
                    用户 = c.execute("SELECT owner FROM feed_subscribers WHERE pool=?", (池["id"],)).fetchall()
                    需要 = any(c.execute("""SELECT COUNT(*) FROM feed_materials m WHERE pool=? AND NOT EXISTS
                        (SELECT 1 FROM feed_exposures e WHERE e.owner=? AND e.name=m.name)""", (池["id"], u[0])).fetchone()[0] < self.高水位 for u in 用户)
                    总库存 = c.execute("SELECT COUNT(*) FROM feed_materials WHERE pool=?", (池["id"],)).fetchone()[0]
                    if 总库存 >= 1200 and 需要 and 用户:
                        # 只回收所有当前消费者都已看过且无人预留的物料，避免库存上限导致永久断粮。
                        c.execute("""DELETE FROM feed_materials WHERE pool=? AND NOT EXISTS
                            (SELECT 1 FROM feed_subscribers s WHERE s.pool=feed_materials.pool AND NOT EXISTS
                            (SELECT 1 FROM feed_exposures e WHERE e.owner=s.owner AND e.name=feed_materials.name))
                            AND NOT EXISTS (SELECT 1 FROM feed_leases l WHERE l.pool=feed_materials.pool AND l.name=feed_materials.name)""", (池["id"],))
                        总库存 = c.execute("SELECT COUNT(*) FROM feed_materials WHERE pool=?", (池["id"],)).fetchone()[0]
                    if not 需要 or 总库存 >= 1200:
                        continue
                    游标 = c.execute("SELECT cursor FROM feed_pools WHERE id=?", (池["id"],)).fetchone()[0]
                    for 偏移 in range(len(书目)):
                        书 = 书目[(游标+偏移) % len(书目)]
                        键 = (池["id"], 书)
                        with self.锁:
                            忙 = 键 in self.在途
                        if 忙 or any(x[:2] == 键 for x in 待发):
                            continue
                        行 = c.execute("SELECT retry FROM feed_sources WHERE pool=? AND book=?", 键).fetchone()
                        if 行 and 行[0] > 现在:
                            continue
                        c.execute("UPDATE feed_pools SET cursor=? WHERE id=?", ((游标+偏移+1) % len(书目), 池["id"]))
                        待发.append((池["id"], 书, json.loads(池["conditions"])))
                        break
            if 待发:
                c.execute("UPDATE feed_budget SET batches=batches+? WHERE day=?", (len(待发), 今日))
        for 池, 书, 条件 in 待发:
            with self.锁:
                self.在途.add((池, 书))
            self.执行器.submit(self.生产, 池, 书, 条件)

    def 生产(self, 池, 书, 条件):
        召回 = []
        try:
            配置 = 读取环境配置()
            if not 模型已配置(配置):
                raise RuntimeError("模型未配置")
            验证模型地址(配置.地址)
            with self.连接() as c:
                排除 = [x[0] for x in c.execute("SELECT name FROM feed_attempts WHERE pool=? AND book=?", (池, 书))]
                请求 = {**条件, "来源书名": 书, "随机种子": uuid.uuid4().int % 2**31, "排除名字": 排除}
                召回 = 批量召回(c, 请求, 25)
            if self.停止.is_set():
                return
            通过 = 模型筛选单批(召回, 请求, 配置) if 召回 else []
            with self.连接() as c:
                通过 = 补充解释(c, 通过, len(召回))
                c.execute("BEGIN IMMEDIATE")
                if not c.execute("SELECT 1 FROM feed_pools WHERE id=?", (池,)).fetchone():
                    return  # 临时队列已回收，晚到结果不得复活队列。
                c.executemany("INSERT OR IGNORE INTO feed_attempts VALUES(?,?,?)", [(池, 书, x["名字"]) for x in 召回])
                for 项 in 通过:
                    c.execute("INSERT OR IGNORE INTO feed_materials VALUES(?,?,?,?,?)", (池, 项["姓名"], 书, 编码(项), time.time()))
                延迟 = 2 if 通过 else (15 if 召回 else 3600)
                c.execute("""INSERT INTO feed_sources VALUES(?,?,?,0,1,?) ON CONFLICT(pool,book) DO UPDATE SET
                    retry=excluded.retry,failures=0,batches=batches+1,accepted=accepted+excluded.accepted""", (池, 书, time.time()+延迟, len(通过)))
                c.execute("DELETE FROM feed_errors WHERE pool=? AND book=?", (池, 书))
        except Exception as 异常:
            with self.连接() as c:
                if c.execute("SELECT 1 FROM feed_pools WHERE id=?", (池,)).fetchone():
                    旧 = c.execute("SELECT failures FROM feed_sources WHERE pool=? AND book=?", (池, 书)).fetchone()
                    失败 = (旧[0] if 旧 else 0)+1
                    c.execute("""INSERT INTO feed_sources VALUES(?,?,?,?,1,0) ON CONFLICT(pool,book) DO UPDATE SET
                        retry=excluded.retry,failures=excluded.failures,batches=batches+1""", (池, 书, time.time()+min(600, 15*2**min(失败, 5)), 失败))
                    # 仅记录分类，不记录原始异常、地址或请求正文，避免第三方错误夹带密钥。
                    类别 = "响应格式或网络异常"
                    if isinstance(异常, sqlite3.Error):
                        类别 = "数据库暂时不可用"
                    elif isinstance(异常, ValueError):
                        类别 = "模型地址配置异常"
                    elif "鉴权失败" in str(异常):
                        类别 = "模型鉴权失败"
                    elif str(异常) == "模型未配置":
                        类别 = "模型未配置"
                    c.execute("INSERT INTO feed_errors VALUES(?,?,?,?) ON CONFLICT(pool,book) DO UPDATE SET category=excluded.category,updated=excluded.updated", (池, 书, 类别, time.time()))
        finally:
            with self.锁:
                self.在途.discard((池, 书))

    def 统计(self):
        with self.连接() as c:
            return {"库存": c.execute("SELECT COUNT(*) FROM feed_materials").fetchone()[0],
                    "队列数": c.execute("SELECT COUNT(*) FROM feed_pools").fetchone()[0],
                    "生产中": len(self.在途), "每日批次上限": self.每日上限,
                    "今日已派批次": c.execute("SELECT COALESCE(SUM(batches),0) FROM feed_budget WHERE day=?", (datetime.now(timezone.utc).date().isoformat(),)).fetchone()[0],
                    "异常分类": [dict(x) for x in c.execute("SELECT DISTINCT book AS 书名,category AS 分类 FROM feed_errors")],
                    "来源": [dict(x) for x in c.execute("SELECT book AS 书名,SUM(batches) AS 批次,SUM(accepted) AS 合格数,SUM(failures) AS 连续失败数 FROM feed_sources GROUP BY book")]}
