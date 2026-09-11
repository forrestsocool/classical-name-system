"""显式启用的限量真实模型验收；在临时运行库中测试，不覆盖业务库。"""
import argparse
import json
import sqlite3
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from pathlib import Path

from 后端.候选队列 import 候选队列
from 后端.起名服务 import 数据库路径


def 主程序():
    参数器 = argparse.ArgumentParser()
    参数器.add_argument("--真实模型", action="store_true", help="明确授权最多8次真实模型请求")
    参数器.add_argument("--姓氏", default="李")
    参数 = 参数器.parse_args()
    if not 参数.真实模型:
        参数器.error("此检查消耗模型额度，请显式传入 --真实模型")
    with tempfile.TemporaryDirectory() as d:
        路径 = Path(d)/"生产验收.sqlite3"
        with closing(sqlite3.connect(数据库路径)) as src, closing(sqlite3.connect(路径)) as dst:
            src.backup(dst)
        q = 候选队列(路径, 自动生产=False)
        会话, 指纹 = "web-"+uuid.uuid4().hex, uuid.uuid4().hex*2
        条件 = {"姓氏":参数.姓氏,"名字长度":2,"必须包含":"","避用字":"","关键词":""}
        try:
            池 = q.拉取(会话,指纹,条件,uuid.uuid4().hex)["队列编号"]
            with q.连接() as c:
                # 本次测量只统计新产生的临时测试物料。
                for 表 in ("feed_materials","feed_sources","feed_attempts"):
                    c.execute(f"DELETE FROM {表} WHERE pool=?",(池,))
                书 = [x[0] for x in c.execute("SELECT name FROM books ORDER BY name LIMIT 8")]
            开始 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=8) as ex:
                任务 = {ex.submit(q.生产,池,b,条件):b for b in 书}
                for f in as_completed(任务):
                    f.result()
                    with q.连接() as c:
                        n = c.execute("SELECT COUNT(*) FROM feed_materials WHERE pool=? AND book=?",(池,任务[f])).fetchone()[0]
                    print(json.dumps({"来源":任务[f],"完成秒数":round(time.perf_counter()-开始,2),"合格数":n},ensure_ascii=False),flush=True)
            取卡开始 = time.perf_counter()
            响应 = q.拉取(会话,指纹,条件,uuid.uuid4().hex,12)
            print(json.dumps({"真实请求上限":8,"合计秒数":round(time.perf_counter()-开始,2),"取库存毫秒":round((time.perf_counter()-取卡开始)*1000,2),
                  "首批": [{"名字":x["项目"]["姓名"],"来源":x["项目"]["书名"]} for x in 响应["卡片"]],"统计":q.统计()},ensure_ascii=False),flush=True)
            if not 响应["卡片"]:
                raise SystemExit("本次没有成功获取合格名字，请检查管理配置与来源统计")
        finally:
            q.关闭()


if __name__ == "__main__": 主程序()
