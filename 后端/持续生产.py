"""Independent, restartable PostgreSQL inventory producer (one model call at a time)."""
import logging
import os
import signal
import uuid
from threading import Event

from psycopg.types.json import Jsonb

from .数据库 import 连接数据库, 资料查询
from .智能筛选 import 批量召回, 模型筛选单批, 补充解释
from .模型接口 import 读取环境配置, 模型已配置, 验证模型地址

停止 = Event()
日志 = logging.getLogger("name.producer")
生产锁 = 2026091702


def 心跳(status, error=""):
    with 连接数据库() as c:
        c.execute("""INSERT INTO app_worker(id,status,last_error) VALUES (1,%s,%s)
            ON CONFLICT(id) DO UPDATE SET heartbeat=now(),status=excluded.status,last_error=excluded.last_error""",
            (status, error))


def 播种档案():
    from .小程序业务 import 拉卡参数
    with 连接数据库() as c:
        for surname in os.getenv("PRODUCER_SURNAMES", "李,王,张,刘,陈").split(","):
            surname = surname.strip()
            if not surname:
                continue
            for length in (1, 2):
                拉卡参数(request_id=uuid.uuid4(), surname=surname, name_length=length)
                c.execute("INSERT INTO app_profiles(surname,name_length) VALUES (%s,%s) ON CONFLICT DO NOTHING", (surname, length))


def 生产一次():
    配置 = 读取环境配置()
    if not 模型已配置(配置):
        心跳("等待配置", "模型未配置")
        return False
    验证模型地址(配置.地址)
    with 连接数据库() as c:
        档案 = c.execute("""SELECT f.id,f.surname,f.name_length,b.name AS book FROM app_profiles f
            CROSS JOIN (SELECT DISTINCT b.name FROM books b JOIN passages p ON p.book_id=b.id WHERE p.can_generate=1) b
            LEFT JOIN app_source_progress s ON s.profile_id=f.id AND s.book=b.name
            WHERE f.enabled AND (s.retry_at IS NULL OR s.retry_at<=now())
            ORDER BY f.last_scheduled,COALESCE(s.last_started,'epoch'::timestamptz),f.id,b.name LIMIT 1""").fetchone()
        if not 档案:
            心跳("等待可用来源")
            return False
        编号, 书 = 档案["id"], 档案["book"]
        排除 = [x["given_name"] for x in c.execute("SELECT given_name FROM app_attempts WHERE profile_id=%s AND book=%s", (编号, 书))]
        请求 = {"姓氏": 档案["surname"], "名字长度": 档案["name_length"], "来源书名": 书,
              "随机种子": uuid.uuid4().int % 2**31, "排除名字": 排除}
        召回 = 批量召回(资料查询(c), 请求, 25)
        c.execute("UPDATE app_profiles SET last_scheduled=now() WHERE id=%s", (编号,))
        c.execute("""INSERT INTO app_source_progress(profile_id,book,retry_at,last_started) VALUES (%s,%s,now()+interval '5 minutes',now())
            ON CONFLICT(profile_id,book) DO UPDATE SET last_started=now(),retry_at=excluded.retry_at""", (编号, 书))
        if not 召回:
            c.execute("UPDATE app_source_progress SET retry_at=now()+interval '1 hour' WHERE profile_id=%s AND book=%s", (编号, 书))
            return False
        上限 = max(0, int(os.getenv("PRODUCER_DAILY_BATCHES", "480")))
        c.execute("INSERT INTO app_budget(day) VALUES (CURRENT_DATE) ON CONFLICT DO NOTHING")
        批次 = c.execute("UPDATE app_budget SET batches=batches+1 WHERE day=CURRENT_DATE AND batches<%s RETURNING batches", (上限,)).fetchone()
        if not 批次:
            心跳("今日额度已用完")
            return False
        c.execute("UPDATE app_source_progress SET batches=batches+1 WHERE profile_id=%s AND book=%s", (编号, 书))
    # No open transaction/row locks across the network request. Budget is already durable.
    心跳("生产中")
    try:
        通过 = 模型筛选单批(召回, 请求, 配置)
        with 连接数据库() as c:
            通过 = 补充解释(资料查询(c), 通过, len(召回))
            for 项 in 召回:
                c.execute("INSERT INTO app_attempts VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (编号, 书, 项["名字"]))
            新增 = 0
            for 项 in 通过:
                新增 += c.execute("""INSERT INTO app_materials(profile_id,given_name,full_name,book,passage_id,payload)
                    SELECT %s,%s,%s,%s,id,%s FROM passages WHERE id=%s AND can_generate=1
                    ON CONFLICT(profile_id,given_name) DO NOTHING""",
                    (编号, 项["名字"], 项["姓名"], 书, Jsonb(项), 项["来源片段编号"])).rowcount
            c.execute("""UPDATE app_source_progress SET accepted=accepted+%s,failures=0,last_error='',retry_at=now()
                WHERE profile_id=%s AND book=%s""", (新增, 编号, 书))
        心跳("运行中")
        return True
    except Exception:
        with 连接数据库() as c:
            c.execute("""UPDATE app_source_progress SET failures=failures+1,last_error='模型或入库失败',
                retry_at=now()+make_interval(secs => LEAST(900,30*power(2,LEAST(failures,5)))::int)
                WHERE profile_id=%s AND book=%s""", (编号, 书))
        心跳("退避重试", "模型或入库失败")
        return False


def 主程序():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: 停止.set())
    while not 停止.is_set():
        try:
            with 连接数据库() as 锁连接:
                锁连接.autocommit = True
                if not 锁连接.execute("SELECT pg_try_advisory_lock(%s) AS locked", (生产锁,)).fetchone()["locked"]:
                    日志.info("另一生产进程正在运行")
                    停止.wait(15)
                    continue
                播种档案()
                while not 停止.is_set():
                    # A broken lock connection stops this worker before another batch starts.
                    锁连接.execute("SELECT 1")
                    生产一次()
                    停止.wait(max(1, int(os.getenv("PRODUCER_INTERVAL_SECONDS", "10"))))
                心跳("已停止")
        except Exception:
            # Avoid credentials, raw model errors and connection strings in logs.
            日志.warning("生产进程暂时不可用，15秒后重连；请检查数据库和模型配置")
            停止.wait(15)


if __name__ == "__main__":
    主程序()
