import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
from fastapi.testclient import TestClient
from 后端 import 起名服务 as 服务
from 后端.智能筛选 import 批量召回, 模型筛选, 多样性重排, 智能生成
from 后端.模型接口 import 模型配置, 验证模型地址


class 智能流程测试(unittest.TestCase):
    def test召回规模出处与排除(self):
        请求 = {"姓氏":"李", "名字长度":2, "随机种子":77, "必须包含":"", "排除名字":[]}
        with closing(sqlite3.connect(服务.数据库路径)) as c:
            c.row_factory = sqlite3.Row
            第一批 = 批量召回(c, 请求)
            self.assertEqual(len(第一批), 500)
            self.assertEqual(len({x["名字"] for x in 第一批}), 500)
            for x in 第一批:
                self.assertEqual(x["原文"][x["原文位置"]:x["原文位置"]+2], x["名字"])
            self.assertTrue({"父母","岂曰"}.isdisjoint({x["名字"] for x in 第一批}))
            第二批 = 批量召回(c, {**请求,"排除名字":[x["姓名"] for x in 第一批]})
            self.assertTrue({x["名字"] for x in 第一批}.isdisjoint({x["名字"] for x in 第二批}))

    def test模型不可引入池外候选或低分(self):
        from contextlib import contextmanager
        @contextmanager
        def 响应(*args, **kwargs):
            class 内容:
                def read(self, n):
                    return json.dumps({"choices":[{"message":{"content":json.dumps({"候选":[
                        {"编号":0,"分数":90,"释义":"品性温和","文化标签":["温润"]},
                        {"编号":0,"分数":95,"释义":"重复名字"},
                        {"编号":999,"分数":95,"释义":"池外名字"},
                        {"编号":1,"分数":50,"释义":"低分词组"}]})}}]}).encode()
            yield 内容()
        配置 = 模型配置(密钥="test-secret", 模型="test")
        with patch("后端.智能筛选.读取环境配置",return_value=配置), patch("后端.智能筛选.验证模型地址"), patch("urllib.request.OpenerDirector.open",side_effect=响应):
            结果 = 模型筛选([{"姓名":"李温和","名字":"温和","书名":"测试","原文位置":0,"原文":"温和"}, {"姓名":"李曰之","名字":"曰之","书名":"测试","原文位置":0,"原文":"曰之"}], {})
            self.assertEqual([x["名字"] for x in 结果],["温和"])

    def test多样性与质量(self):
        池 = [{"名字":x,"基础分":90,"书名":"测试","文化标签":[]} for x in ["清风","清云","清远","安宁","明德","修竹"]]
        结果 = 多样性重排(池, 9, 3)
        self.assertEqual(len(结果),3)
        self.assertLessEqual(sum("清" in x["名字"] for x in 结果),1)
        self.assertEqual(结果,多样性重排(池,9,3))

    def test配置权限脱敏及地址保护(self):
        with tempfile.TemporaryDirectory() as d, patch.dict("os.environ",{"起名管理密钥":"admin-test","起名模型配置文件":str(Path(d)/"config.json")}), TestClient(服务.应用) as client:
            body = {"地址":"https://example.com/v1", "模型":"test", "密钥":"private-key-123"}
            self.assertEqual(client.put("/api/admin/model-config",json=body).status_code,403)
            with patch("后端.起名服务.验证模型地址"):
                r=client.put("/api/admin/model-config",json=body,headers={"X-Admin-Key":"admin-test"})
                self.assertEqual(r.status_code,200)
                r=client.get("/api/admin/model-config",headers={"X-Admin-Key":"admin-test"})
                self.assertNotIn(body["密钥"],r.text)
                self.assertNotIn("密钥",r.json())
                r=client.put("/api/admin/model-config",json={**body,"超时秒数":-1},headers={"X-Admin-Key":"admin-test"})
                self.assertEqual(r.status_code,422)
                self.assertNotIn(body["密钥"],r.text)
                r=client.put("/api/admin/model-config",json={**body,"地址":"https://different.example/v1","密钥":""},headers={"X-Admin-Key":"admin-test"})
                self.assertEqual(r.status_code,422)
        for url in ["http://localhost/v1", "https://127.0.0.1/v1", "https://[::1]/v1", "https://user:pass@example.com/v1"]:
            with self.assertRaises(ValueError): 验证模型地址(url)

    def test模型失败不会降级为原文碎片(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d)/"test.db"
            with closing(sqlite3.connect(服务.数据库路径)) as src, closing(sqlite3.connect(db)) as dst:
                src.backup(dst)
            with patch.object(服务,"数据库路径",db), patch("后端.智能筛选.模型筛选",side_effect=RuntimeError("测试失败")), TestClient(服务.应用) as client:
                r=client.post("/api/name-runs",json={"姓氏":"李"},headers={"X-Session-Key":"web-"+"f"*32})
                self.assertEqual(r.status_code,503)
                self.assertNotIn("候选",r.json())
