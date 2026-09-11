import json
import sqlite3
import tempfile
import time
import unittest
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from 后端 import 起名服务 as 服务
from 后端.候选队列 import 候选队列, 布隆过滤器, 编码
from 后端.智能筛选 import 批量召回, 补充解释


class 队列测试(unittest.TestCase):
    def setUp(self):
        self.目录 = tempfile.TemporaryDirectory()
        self.路径 = Path(self.目录.name)/"queue.db"
        with closing(sqlite3.connect(服务.数据库路径)) as src, closing(sqlite3.connect(self.路径)) as dst:
            src.backup(dst)
        self.q = 候选队列(self.路径, 自动生产=False)
        self.会话, self.指纹 = "web-"+"a"*32, "b"*64
        self.条件 = {"姓氏":"李", "名字长度":2, "必须包含":"", "避用字":"", "关键词":""}

    def tearDown(self):
        self.q.关闭()
        self.目录.cleanup()

    def 拉取(self, 会话=None, 条件=None, 请求号=None):
        return self.q.拉取(会话 or self.会话, self.指纹, 条件 or self.条件, 请求号 or uuid.uuid4().hex, 12)

    def 填充(self, 条件=None):
        条件 = 条件 or self.条件
        池 = self.拉取(条件=条件)["队列编号"]
        with self.q.连接() as c:
            项目 = 批量召回(c, {**条件, "随机种子":91}, 90)
            for 项 in 项目:
                项.update({"基础分":90,"现代释义":"仅用于回归测试，不代表真实推荐","文化标签":[],"方向":""})
            项目 = 补充解释(c, 项目, 90)
            c.executemany("INSERT OR IGNORE INTO feed_materials VALUES(?,?,?,?,?)", [(池,x["姓名"],x["书名"],编码(x),time.time()) for x in 项目])
        return 池

    def test来源轮换与实际曝光(self):
        self.填充()
        第一 = self.拉取()
        分布 = Counter(x["项目"]["书名"] for x in 第一["卡片"])
        self.assertGreaterEqual(len(分布), 9)
        self.assertLessEqual(len(分布), 11)
        self.assertLessEqual(max(分布.values()), 2)
        with self.q.连接() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM feed_exposures").fetchone()[0], 0)
        卡 = 第一["卡片"][0]
        self.q.确认(self.会话, self.指纹, [卡["投递编号"]], [], [], 第一["队列编号"])
        with self.q.连接() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM feed_exposures").fetchone()[0], 1)
        第二 = self.拉取()
        self.assertTrue({x["项目"]["姓名"] for x in 第一["卡片"]}.isdisjoint(x["项目"]["姓名"] for x in 第二["卡片"]))

    def test布隆误判不浪费物料(self):
        self.填充()
        owner = self.q.身份(self.会话, self.指纹)
        with self.q.连接() as c:
            c.execute("INSERT INTO feed_blooms VALUES(?,?)", (owner, b"\xff"*布隆过滤器.字节数))
        self.assertEqual(len(self.拉取()["卡片"]), 12)

    def test同条件共享固定字私有(self):
        self.填充()
        a, b = self.拉取(), self.拉取(会话="web-"+"c"*32)
        self.assertEqual(a["队列编号"], b["队列编号"])
        self.assertTrue(b["卡片"])
        固定 = {**self.条件,"必须包含":"清"}
        a, b = self.拉取(条件=固定), self.拉取(会话="web-"+"c"*32, 条件=固定)
        self.assertNotEqual(a["队列编号"],b["队列编号"])
        with self.q.连接() as c:
            c.execute("UPDATE feed_pools SET touched=? WHERE private=1", (time.time()-301,))
            self.q.清理(c,time.time())
            self.assertEqual(c.execute("SELECT COUNT(*) FROM feed_pools WHERE private=1").fetchone()[0],0)

    def test并发投递不重复且请求幂等(self):
        self.填充()
        with ThreadPoolExecutor(max_workers=3) as ex:
            结果 = list(ex.map(lambda _: self.拉取(), range(3)))
        名 = [x["项目"]["姓名"] for r in 结果 for x in r["卡片"]]
        self.assertEqual(len(名),len(set(名)))
        with self.q.连接() as c:
            c.execute("DELETE FROM feed_leases")
        请求号 = uuid.uuid4().hex
        a, b = self.拉取(请求号=请求号), self.拉取(请求号=请求号)
        self.assertEqual(a,b)
        卡 = a["卡片"][0]
        self.q.确认(self.会话,self.指纹,[卡["投递编号"]],[],[])
        c = self.拉取(请求号=请求号)
        self.assertNotIn(卡,c["卡片"])

    def test未看租约回收和离线晚确认(self):
        self.填充()
        r = self.拉取(); 卡 = r["卡片"][0]
        with self.q.连接() as c:
            c.execute("UPDATE feed_leases SET expires=0")
            self.q.清理(c,time.time())
        self.q.确认(self.会话,self.指纹,[卡["投递编号"]],[],[])
        with self.q.连接() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM feed_exposures").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM feed_materials").fetchone()[0],90)
        self.assertNotIn(卡["项目"]["姓名"], [x["项目"]["姓名"] for x in self.拉取()["卡片"]])

    def test曝光持久化且不能跨用户确认(self):
        self.填充(); r = self.拉取(); 卡 = r["卡片"][0]
        self.q.确认("web-"+"d"*32,self.指纹,[卡["投递编号"]],[],[])
        with self.q.连接() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM feed_exposures").fetchone()[0],0)
        self.q.确认(self.会话,self.指纹,[卡["投递编号"]],[],[])
        self.q.关闭(); self.q = 候选队列(self.路径,自动生产=False)
        self.assertNotIn(卡["项目"]["姓名"], [x["项目"]["姓名"] for x in self.拉取()["卡片"]])

    def test调度八来源与无人暂停预算(self):
        self.拉取()
        with patch.object(self.q.执行器,"submit") as submit:
            self.q.调度一次()
            self.assertEqual(submit.call_count,8)
            self.assertEqual(len({x.args[2] for x in submit.call_args_list}),8)
            self.q.在途.clear()
            self.q.每日上限 = 8
            self.q.调度一次()
            self.assertEqual(submit.call_count,8)
            self.q.每日上限 = 480
            with self.q.连接() as c:
                c.execute("UPDATE feed_pools SET touched=0")
                c.execute("UPDATE feed_subscribers SET touched=0")
            self.q.调度一次()
            self.assertEqual(submit.call_count,8)

    def test失败退避不降级原文(self):
        池 = self.拉取()["队列编号"]
        with patch("后端.候选队列.读取环境配置", side_effect=RuntimeError("测试秘密不应进入接口")):
            self.q.生产(池,"诗经",self.条件)
        with self.q.连接() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM feed_materials").fetchone()[0],0)
            self.assertGreater(c.execute("SELECT retry FROM feed_sources").fetchone()[0],time.time())
            self.assertNotIn("秘密",c.execute("SELECT category FROM feed_errors").fetchone()[0])

    def test生产单批即入库且库存足够暂停(self):
        from 后端.模型接口 import 模型配置
        池 = self.拉取()["队列编号"]
        def 审稿(召回,请求,配置):
            self.assertEqual(len(召回),25)
            self.assertEqual({x["书名"] for x in 召回},{"庄子"})
            return [{**x,"基础分":90,"现代释义":"测试寓意","文化标签":[],"方向":""} for x in 召回[:2]]
        with patch("后端.候选队列.读取环境配置",return_value=模型配置(密钥="test",模型="test")), patch("后端.候选队列.验证模型地址"), patch("后端.候选队列.模型筛选单批",side_effect=审稿):
            self.q.生产(池,"庄子",self.条件)
        with self.q.连接() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM feed_materials").fetchone()[0],2)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM feed_attempts").fetchone()[0],25)
        self.q.高水位 = 2
        with patch.object(self.q.执行器,"submit") as submit:
            self.q.调度一次()
            submit.assert_not_called()
        self.assertEqual(len(self.拉取()["卡片"]),2)

    def test临时队列关闭后晚到结果不会复活(self):
        from 后端.模型接口 import 模型配置
        条件 = {**self.条件,"必须包含":"清"}
        池 = self.拉取(条件=条件)["队列编号"]
        def 晚到(召回,请求,配置):
            with self.q.连接() as c:
                c.execute("UPDATE feed_pools SET touched=0 WHERE id=?",(池,))
                self.q.清理(c,time.time())
            return [{**x,"基础分":90,"现代释义":"测试寓意","文化标签":[],"方向":""} for x in 召回[:1]]
        with patch("后端.候选队列.读取环境配置",return_value=模型配置(密钥="test",模型="test")), patch("后端.候选队列.验证模型地址"), patch("后端.候选队列.模型筛选单批",side_effect=晚到):
            self.q.生产(池,"庄子",条件)
        with self.q.连接() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM feed_pools WHERE id=?",(池,)).fetchone()[0],0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM feed_materials WHERE pool=?",(池,)).fetchone()[0],0)

    def test接口会话收藏归属与参数验证(self):
        self.填充()
        with patch.object(服务,"数据库路径",self.路径), patch.object(服务,"获取候选队列",return_value=self.q), patch.dict("os.environ",{"起名管理密钥":"test-feed-admin-key"}), TestClient(服务.应用) as client:
            body = {"指纹":self.指纹,"请求编号":uuid.uuid4().hex,"条件":self.条件}
            self.assertEqual(client.post("/api/feed/pull",json=body).status_code,401)
            h = {"X-Session-Key":self.会话}
            r = client.post("/api/feed/pull",json=body,headers=h)
            self.assertEqual(r.status_code,200,r.text)
            卡 = r.json()["卡片"][0]
            self.assertEqual(client.get("/api/name-runs/"+卡["任务编号"],headers=h).status_code,200)
            self.assertEqual(client.get("/api/name-runs/"+卡["任务编号"],headers={"X-Session-Key":"web-"+"e"*32}).status_code,404)
            r = client.post("/api/favorites",json={"collection_id":__import__('hashlib').sha256(self.会话.encode()).hexdigest(),"run_id":卡["任务编号"],"full_name":卡["项目"]["姓名"]},headers=h)
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(client.post("/api/feed/pull",json={**body,"条件":{**self.条件,"必须包含":"?"}},headers=h).status_code,422)
            self.assertEqual(client.get("/api/admin/feed-metrics").status_code,403)


if __name__ == "__main__":
    unittest.main()
