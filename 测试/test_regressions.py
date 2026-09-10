import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sqlite3
import hashlib
from contextlib import closing
from datetime import datetime
from 后端.八字计算 import 本地时间, 计算八字

from fastapi.testclient import TestClient
from 后端 import 起名服务 as 服务
from 后端.名字校验 import 满足约束, 取字位置
from 后端.模型接口 import 校验模型输出, 语料证据
from 脚本.建立资料数据库 import 切分古籍, 建库, 默认资料目录


class 回归测试(unittest.TestCase):
    def test换一批有补充候选(self):
        第一批 = 服务.创建起名任务(服务.起名请求(姓氏="李", 名字长度=2, 随机种子=101))
        self.assertTrue(第一批["候选"])
        排除 = [项目["姓名"] for 项目 in 第一批["候选"]]
        第二批 = 服务.创建起名任务(服务.起名请求(姓氏="李", 名字长度=2, 随机种子=102, 排除名字=排除))
        self.assertTrue(第二批["候选"])
        self.assertTrue(set(排除).isdisjoint({项目["姓名"] for 项目 in 第二批["候选"]}))
        服务.删除起名任务(第一批["任务编号"])
        服务.删除起名任务(第二批["任务编号"])

    def test同一时刻的节气年月柱不随地区改变(self):
        时间 = datetime.fromisoformat("2024-02-04T09:00:00+00:00")
        北京 = 计算八字(时间, "Asia/Shanghai")
        纽约 = 计算八字(时间, "America/New_York")
        self.assertEqual(北京["四柱"][:2], 纽约["四柱"][:2])

    def test夏令时异常时间拒绝(self):
        with self.assertRaises(ValueError):
            本地时间(datetime(2024, 3, 10, 2, 30), "America/New_York")
        with self.assertRaises(ValueError):
            本地时间(datetime(2024, 11, 3, 1, 30), "America/New_York")

    def test硬性约束和逐字位置(self):
        self.assertFalse(满足约束("安宁", {"必须包含": "安安"}))
        self.assertFalse(满足约束("安宁", {"避用字": "宁"}))
        self.assertIsNone(取字位置("安宁", "安于此。宁于彼。", "同句取字"))
        self.assertEqual(取字位置("安宁", "安于此。宁于彼。", "跨句组合"), [0, 4])
        self.assertIsNone(取字位置("安安", "安于此。", "同句取字"))
        self.assertEqual(取字位置("安宁", "安且宁。", "同句取字"), [0, 2])
        输出 = {"候选": [{"名字": "安宁", "语料编号": 1, "取字方式": "原文连取", "现代释义": "安定", "风格标签": [], "风险提示": []}]}
        self.assertEqual(校验模型输出(输出, [语料证据(1, "安宁", "测试", "测试")], 2, {"避用字": "宁"}), [])

    def test诗经正式篇名进入实际片段(self):
        片段 = 切分古籍("诗经", 默认资料目录 / "古籍全文" / "诗经.txt", 1, 1)
        self.assertEqual(片段[0]["篇章"], "国风·周南·关雎")

    def test会话隔离及非破坏性建库(self):
        with TemporaryDirectory(prefix="name-http-") as 目录:
            路径 = Path(目录) / "测试.sqlite3"
            with closing(sqlite3.connect(服务.数据库路径)) as 源, closing(sqlite3.connect(路径)) as 目标:
                源.backup(目标)
            with patch.object(服务, "数据库路径", 路径), patch.dict("os.environ", {"起名每分钟上限": "10000"}), TestClient(服务.应用) as 客户:
                甲 = {"X-Session-Key": "web-" + "a" * 32}
                乙 = {"X-Session-Key": "web-" + "b" * 32}
                self.assertEqual(客户.get("/api/name-runs").status_code, 401)
                响应 = 客户.post("/api/name-runs", headers=甲, json={"姓氏": "李", "随机种子": 7})
                self.assertEqual(响应.status_code, 200, 响应.text)
                编号 = 响应.json()["任务编号"]
                self.assertEqual(客户.get("/api/name-runs", headers=乙).json()["数量"], 0)
                self.assertEqual(客户.get(f"/api/name-runs/{编号}", headers=乙).status_code, 404)
                self.assertEqual(客户.delete(f"/api/name-runs/{编号}", headers=乙).status_code, 404)
                self.assertEqual(客户.post(f"/api/name-runs/{编号}/model-candidates", headers=乙).status_code, 404)
                self.assertEqual(客户.get(f"/api/name-runs/{编号}", headers=甲).status_code, 200)
                名字 = 响应.json()["候选"][0]["姓名"]
                乙收藏夹 = hashlib.sha256(乙["X-Session-Key"].encode()).hexdigest()
                self.assertEqual(客户.post("/api/favorites", headers=乙, json={"collection_id": 乙收藏夹, "run_id": 编号, "full_name": 名字}).status_code, 404)
                self.assertEqual(客户.post("/api/feedback", headers=乙, json={"collection_id": 乙收藏夹, "run_id": 编号, "full_name": 名字, "feedback_type": "喜欢"}).status_code, 404)
                单字 = 客户.post("/api/name-runs", headers=甲, json={"姓氏": "李", "名字长度": 1}).json()
                self.assertTrue(单字["候选"])
                self.assertTrue(all(len(项["名字"]) == 1 for 项 in 单字["候选"]))
                self.assertEqual(客户.post("/api/name-runs", headers=甲, json={"姓氏": "李", "必须包含": "宁", "避用字": "宁"}).status_code, 422)
                with self.assertRaisesRegex(ValueError, "业务记录"):
                    建库(默认资料目录, 路径)
                self.assertEqual(客户.delete(f"/api/name-runs/{编号}", headers=甲).status_code, 200)
            服务.查询缓存.清空()
