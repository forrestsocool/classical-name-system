from __future__ import annotations

import os
import json
import sqlite3
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from 后端.候选生成 import 生成基础候选, 提取名字
from 后端.缓存 import TTL缓存
from 后端.模型接口 import (
    模型配置,
    模型已配置,
    语料证据,
    构建提示词,
    调用兼容模型,
    校验模型输出,
)
from 后端.起名服务 import (
    获取方向,
    获取片段,
    获取年号,
    获取收藏,
    获取质量统计,
    获取模型候选,
    获取复核队列,
    获取五行复核队列,
    获取审计问题队列,
    获取汉字,
    获取起名任务,
    获取任务列表,
    生成模型候选,
    计算八字接口,
    健康检查,
    就绪检查,
    搜索古籍,
    搜索年号,
    起名请求,
    八字请求,
    收藏请求,
    比较收藏,
    比较请求,
    收藏候选,
    删除收藏,
    删除起名任务,
    复核片段,
    提交反馈,
    片段复核请求,
    反馈请求,
    汉字五行复核请求,
    审计问题复核请求,
    复核审计问题,
    复核五行规则,
    请求是否超限,
    创建起名任务,
)


class 起名系统测试(unittest.TestCase):
    class 假响应:
        def __init__(self, 内容: bytes) -> None:
            self.内容 = 内容

        def __enter__(self):
            return self

        def __exit__(self, 类型, 值, 回溯):
            return False

        def read(self) -> bytes:
            return self.内容

    def test数据库健康状态(self) -> None:
        结果 = 健康检查()
        self.assertEqual(结果["状态"], "正常")
        self.assertEqual(结果["古籍数"], 9)
        self.assertGreater(结果["片段数"], 8000)
        self.assertGreaterEqual(结果["可生成片段数"], 10)
        就绪 = 就绪检查()
        self.assertEqual(就绪["状态"], "就绪")
        self.assertEqual(就绪["数据库完整性"], "ok")

    def test搜索和出处详情(self) -> None:
        结果 = 搜索古籍("温故")
        self.assertGreaterEqual(结果["数量"], 1)
        self.assertTrue(any(项目["book"] == "论语" for 项目 in 结果["结果"]))
        详情 = 获取片段(结果["结果"][0]["id"])
        self.assertIn("温故", 详情["text"])
        self.assertEqual(len(详情["sha256"]), 64)

    def test方向接口(self) -> None:
        结果 = 获取方向()
        self.assertEqual(len(结果["方向"]), 7)
        self.assertTrue(any(项目["名称"] == "温润君子" for 项目 in 结果["方向"]))

    def test年号搜索和详情(self) -> None:
        结果 = 搜索年号(关键词=None, 地区=None, 状态=None, 数量=3)
        self.assertEqual(结果["数量"], 3)
        年号编号 = 结果["结果"][0]["id"]
        详情 = 获取年号(年号编号)
        self.assertEqual(详情["id"], 年号编号)
        self.assertTrue(详情["era_name"])

    def test八字计算和五行统计(self) -> None:
        结果 = 计算八字接口(
            八字请求(
                出生时间=datetime(1990, 1, 1, 12, 0, 0),
                时区="Asia/Shanghai",
                日界规则="子初",
            )
        )
        self.assertEqual(len(结果["四柱"]), 4)
        self.assertEqual(sum(结果["五行统计"]["明干支"].values()), 8)
        self.assertEqual(结果["日界规则"], "子初")

    def test八字日界和时区边界(self) -> None:
        子初 = 计算八字接口(
            八字请求(
                出生时间=datetime(2020, 1, 1, 23, 30),
                日界规则="子初",
            )
        )
        午夜 = 计算八字接口(
            八字请求(
                出生时间=datetime(2020, 1, 1, 23, 30),
                日界规则="午夜",
            )
        )
        self.assertNotEqual(子初["四柱"][2], 午夜["四柱"][2])

    def test汉字读音和五行规则状态(self) -> None:
        结果 = 获取汉字("清")
        self.assertTrue(结果["pinyin"])
        self.assertTrue(any(规则["element"] == "水" for 规则 in 结果["五行规则"]))
        self.assertTrue(all(规则["status"] == "待复核" for 规则 in 结果["五行规则"]))

    def test模型出处校验(self) -> None:
        证据 = [语料证据(1, "温故而知新，可以为师矣。", "论语", "为政")]
        提示 = 构建提示词({"名字长度": 2, "方向": ["智慧通达"]}, 证据)
        self.assertIn("温故而知新", 提示["用户提示"])
        输出 = {
            "候选": [
                {
                    "名字": "知新",
                    "语料编号": 1,
                    "取字方式": "原文连取",
                    "现代释义": "保持学习和更新",
                    "风格标签": ["智慧通达"],
                    "风险提示": [],
                },
                {
                    "名字": "虚构",
                    "语料编号": 999,
                    "取字方式": "原文连取",
                    "现代释义": "不应通过",
                    "风格标签": [],
                    "风险提示": [],
                },
            ]
        }
        结果 = 校验模型输出(输出, 证据, 2)
        self.assertEqual([项目["名字"] for 项目 in 结果], ["知新"])
        self.assertFalse(模型已配置(模型配置()))

    def test兼容模型请求适配器(self) -> None:
        响应内容 = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "候选": [
                                        {
                                            "名字": "知新",
                                            "语料编号": 1,
                                            "取字方式": "原文连取",
                                            "现代释义": "持续学习并不断更新",
                                            "风格标签": ["智慧通达"],
                                            "风险提示": [],
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")
        证据 = [语料证据(1, "温故而知新，可以为师矣。", "论语", "为政")]
        配置 = 模型配置(地址="https://模型测试.invalid/v1/chat/completions", 密钥="测试密钥", 模型="测试模型")
        with patch(
            "后端.模型接口.urllib.request.urlopen",
            return_value=self.假响应(响应内容),
        ) as 请求模拟:
            结果 = 调用兼容模型({"名字长度": 2}, 证据, 配置)
        self.assertEqual(结果[0]["名字"], "知新")
        请求对象 = 请求模拟.call_args.args[0]
        请求体 = json.loads(请求对象.data.decode("utf-8"))
        self.assertEqual(请求体["model"], "测试模型")
        self.assertEqual(请求对象.headers["Authorization"], "Bearer 测试密钥")
        with patch(
            "后端.模型接口.urllib.request.urlopen",
            side_effect=[
                self.假响应(b'{"choices": []}'),
                self.假响应(响应内容),
            ],
        ) as 重试模拟:
            结果 = 调用兼容模型({"名字长度": 2}, 证据, 配置)
        self.assertEqual(结果[0]["名字"], "知新")
        self.assertEqual(重试模拟.call_count, 2)

    def test模型本地网络完整链路(self) -> None:
        任务 = 创建起名任务(起名请求(姓氏="沈", 名字长度=2, 随机种子=53))
        self.assertTrue(任务["候选"])
        第一项 = 任务["候选"][0]
        响应内容 = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "候选": [
                                        {
                                            "名字": 第一项["名字"],
                                            "语料编号": 第一项["来源片段编号"],
                                            "取字方式": 第一项["取字方式"],
                                            "现代释义": "本地接口测试释义",
                                            "风格标签": [第一项["方向"]],
                                            "风险提示": [],
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")

        class 模拟接口处理器(BaseHTTPRequestHandler):
            def do_POST(self):
                长度 = int(self.headers.get("Content-Length", "0"))
                请求体 = json.loads(self.rfile.read(长度).decode("utf-8"))
                self.server.已收到模型 = 请求体["model"] == "本地测试模型"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(响应内容)

            def log_message(self, 格式, *参数):
                return

        服务 = ThreadingHTTPServer(("127.0.0.1", 0), 模拟接口处理器)
        服务.已收到模型 = False
        线程 = threading.Thread(target=服务.serve_forever, daemon=True)
        线程.start()
        try:
            with patch.dict(
                os.environ,
                {
                    "起名模型地址": f"http://127.0.0.1:{服务.server_port}/v1/chat/completions",
                    "起名模型密钥": "local-test-key-123",
                    "起名模型名称": "本地测试模型",
                },
            ):
                结果 = 生成模型候选(任务["任务编号"])
        finally:
            服务.shutdown()
            线程.join(timeout=2)
            服务.server_close()
        self.assertTrue(服务.已收到模型)
        self.assertEqual(结果["保存数量"], 1)
        已保存 = 获取模型候选(任务["任务编号"])
        self.assertEqual(已保存["数量"], 1)
        self.assertEqual(已保存["候选"][0]["status"], "已校验")

    def test起名任务和八字摘要可追踪(self) -> None:
        结果 = 创建起名任务(
            起名请求(
                姓氏="王",
                名字长度=2,
                出生时间=datetime(1990, 1, 1, 12, 0, 0),
                方向=["智慧通达"],
            )
        )
        self.assertEqual(结果["状态"], "完成")
        self.assertGreaterEqual(len(结果["候选"]), 1)
        self.assertIsNotNone(结果["八字"])
        self.assertTrue(all(项目["原文"] for 项目 in 结果["候选"]))
        self.assertTrue(all("五行匹配" in 项目 for 项目 in 结果["候选"]))
        self.assertTrue(all(项目["拼音"] for 项目 in 结果["候选"]))
        第二次 = 创建起名任务(
            起名请求(
                姓氏="王",
                名字长度=2,
                随机种子=31,
                排除名字=[结果["候选"][0]["姓名"]],
            )
        )
        self.assertNotIn(结果["候选"][0]["姓名"], [项目["姓名"] for 项目 in 第二次["候选"]])
        任务 = 获取起名任务(结果["任务编号"])
        self.assertEqual(任务["status"], "完成")
        self.assertEqual(len(任务["候选"]), len(结果["候选"]))
        self.assertIsNotNone(任务["八字"])
        self.assertNotIn("出生时间", 任务["请求"])
        self.assertTrue(任务["请求"]["出生时间已处理"])
        self.assertNotIn("输入时间", 任务["八字"])
        self.assertTrue(任务["八字"]["出生时间已隐去"])
        列表 = 获取任务列表(数量=20)
        self.assertTrue(any(项目["id"] == 结果["任务编号"] for 项目 in 列表["任务"]))
        删除 = 删除起名任务(结果["任务编号"])
        self.assertEqual(删除["状态"], "已删除")
        with self.assertRaises(Exception):
            获取起名任务(结果["任务编号"])

    def test收藏和比较(self) -> None:
        任务 = 创建起名任务(起名请求(姓氏="林", 名字长度=2, 随机种子=11))
        self.assertTrue(任务["候选"])
        名字 = 任务["候选"][0]["姓名"]
        收藏 = 收藏候选(
            收藏请求(
                collection_id="test-suite",
                run_id=任务["任务编号"],
                full_name=名字,
                note="测试收藏",
            )
        )
        self.assertEqual(收藏["full_name"], 名字)
        列表 = 获取收藏("test-suite")
        self.assertEqual(列表["数量"], 1)
        比较 = 比较收藏(
            比较请求(collection_id="test-suite", favorite_ids=[收藏["id"]])
        )
        self.assertEqual(len(比较["结果"]), 1)
        删除 = 删除收藏(收藏["id"], "test-suite")
        self.assertEqual(删除["状态"], "已删除")

    def test反馈和质量统计(self) -> None:
        任务 = 创建起名任务(起名请求(姓氏="周", 名字长度=2, 随机种子=17))
        名字 = 任务["候选"][0]["姓名"]
        反馈 = 提交反馈(
            反馈请求(
                collection_id="metrics-suite",
                run_id=任务["任务编号"],
                full_name=名字,
                feedback_type="喜欢",
                score=5,
            )
        )
        self.assertEqual(反馈["feedback_type"], "喜欢")
        with patch.dict(os.environ, {"起名管理密钥": "admin-test-key-2026"}):
            统计 = 获取质量统计(管理密钥="admin-test-key-2026")
        self.assertGreaterEqual(统计["反馈总数"], 1)
        self.assertGreaterEqual(统计["反馈类型"]["喜欢"], 1)
        self.assertGreaterEqual(统计["模型调用总数"], 0)
        self.assertEqual(统计["模型估算成本"], 0)

    def test模型调用指标记录(self) -> None:
        任务 = 创建起名任务(起名请求(姓氏="赵", 名字长度=2, 随机种子=19))
        with patch.dict(os.environ, {"起名管理密钥": "admin-test-key-2026"}):
            调用前 = 获取质量统计(管理密钥="admin-test-key-2026")
        with patch.dict(
            os.environ,
            {"起名模型密钥": "测试密钥", "起名模型名称": "测试模型"},
        ), patch("后端.起名服务.调用兼容模型", return_value=[]):
            结果 = 生成模型候选(任务["任务编号"])
        self.assertEqual(结果["保存数量"], 0)
        with patch.dict(os.environ, {"起名管理密钥": "admin-test-key-2026"}):
            统计 = 获取质量统计(管理密钥="admin-test-key-2026")
        self.assertEqual(统计["模型调用总数"], 调用前["模型调用总数"] + 1)
        self.assertEqual(统计["模型成功数"], 调用前["模型成功数"] + 1)
        self.assertGreaterEqual(统计["模型平均耗时毫秒"], 0)

    def test资料复核流程和管理密钥(self) -> None:
        with patch.dict(os.environ, {"起名管理密钥": "admin-test-key-2026"}):
            队列 = 获取复核队列(
                状态="待核验", 数量=3, 管理密钥="admin-test-key-2026"
            )
            self.assertEqual(队列["状态"], "待核验")
            self.assertGreaterEqual(队列["数量"], 1)
            片段编号 = 队列["片段"][0]["id"]
            结果 = 复核片段(
                片段编号,
                片段复核请求(
                    状态="已核验", 复核人="测试复核人", 备注="测试复核流程"
                ),
                管理密钥="admin-test-key-2026",
            )
        self.assertEqual(结果["status"], "已核验")
        self.assertEqual(结果["can_generate"], 1)
        self.assertEqual(结果["reviewer"], "测试复核人")
        self.assertTrue(结果["reviewed_at"])

        with patch.dict(os.environ, {"起名管理密钥": ""}):
            with self.assertRaises(Exception) as 上下文:
                获取复核队列(状态="待核验", 数量=1, 管理密钥="")
        self.assertEqual(上下文.exception.status_code, 503)

    def test请求限流边界(self) -> None:
        with patch.dict(os.environ, {"起名每分钟上限": "2"}):
            来源 = "限流测试来源"
            self.assertFalse(请求是否超限(来源, 100.0))
            self.assertFalse(请求是否超限(来源, 101.0))
            self.assertTrue(请求是否超限(来源, 102.0))
            self.assertFalse(请求是否超限(来源, 161.0))

    def test五行规则复核流程(self) -> None:
        with patch.dict(os.environ, {"起名管理密钥": "admin-test-key-2026"}):
            队列 = 获取五行复核队列(
                状态="待复核", 数量=1, 管理密钥="admin-test-key-2026"
            )
            self.assertEqual(队列["数量"], 1)
            规则 = 队列["规则"][0]
            结果 = 复核五行规则(
                规则["char"],
                汉字五行复核请求(
                    方法=规则["method"],
                    状态="已核验",
                    复核人="测试复核人",
                    备注="测试五行复核",
                ),
                管理密钥="admin-test-key-2026",
            )
        self.assertEqual(结果["status"], "已核验")
        self.assertEqual(结果["reviewer"], "测试复核人")
        self.assertTrue(结果["reviewed_at"])

    def test审计问题复核流程(self) -> None:
        with patch.dict(os.environ, {"起名管理密钥": "admin-test-key-2026"}):
            队列 = 获取审计问题队列(
                状态="待处理", 数量=1, 管理密钥="admin-test-key-2026"
            )
            self.assertEqual(队列["数量"], 1)
            问题 = 队列["问题"][0]
            结果 = 复核审计问题(
                问题["id"],
                审计问题复核请求(
                    状态="已处理", 复核人="测试复核人", 备注="测试审计复核"
                ),
                管理密钥="admin-test-key-2026",
            )
        self.assertEqual(结果["status"], "已处理")
        self.assertEqual(结果["reviewer"], "测试复核人")
        self.assertTrue(结果["reviewed_at"])

    def test本地缓存隔离和容量(self) -> None:
        缓存 = TTL缓存(有效秒数=60, 最大数量=1)
        原值 = {"列表": ["甲"]}
        缓存.写入("甲", 原值)
        读取值 = 缓存.读取("甲")
        读取值["列表"].append("乙")
        self.assertEqual(缓存.读取("甲"), {"列表": ["甲"]})
        缓存.写入("乙", {"值": 2})
        self.assertIsNone(缓存.读取("甲"))
        self.assertEqual(缓存.数量(), 1)

    def test候选生成约束和随机种子(self) -> None:
        连接 = sqlite3.connect(":memory:")
        连接.row_factory = sqlite3.Row
        连接.executescript(
            """
            CREATE TABLE directions (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE direction_keywords (direction_id INTEGER, keyword TEXT);
            CREATE TABLE books (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE passages (
                id INTEGER PRIMARY KEY, book_id INTEGER, section_title TEXT,
                text TEXT, can_generate INTEGER
            );
            CREATE TABLE candidate_phrases (
                id INTEGER PRIMARY KEY, passage_id INTEGER, phrase TEXT,
                source_offset INTEGER, direction TEXT, origin_type TEXT,
                quality_score INTEGER, status TEXT
            );
            CREATE TABLE character_elements (
                char TEXT, element TEXT, method TEXT,
                confidence TEXT, status TEXT, note TEXT
            );
            CREATE TABLE characters (
                char TEXT, pinyin TEXT, pinyin_tone TEXT,
                source TEXT, status TEXT
            );
            INSERT INTO directions VALUES (1, '温润君子');
            INSERT INTO direction_keywords VALUES (1, '和');
            INSERT INTO books VALUES (1, '测试书');
            INSERT INTO passages VALUES (1, 1, '测试篇', '和光同尘安宁', 1);
            INSERT INTO candidate_phrases VALUES
                (1, 1, '和光', 0, '温润君子', '原文连取', 90, '已核验');
            INSERT INTO candidate_phrases VALUES
                (2, 1, '安宁', 4, '安宁福泽', '原文连取', 88, '已核验');
            INSERT INTO character_elements VALUES
                ('和', '土', '测试规则', '高', '已核验', '');
            INSERT INTO character_elements VALUES
                ('光', '火', '测试规则', '高', '已核验', '');
            INSERT INTO characters VALUES
                ('和', 'he', 'he2', '测试', '已核验');
            INSERT INTO characters VALUES
                ('光', 'guang', 'guang1', '测试', '已核验');
            INSERT INTO characters VALUES
                ('安', 'an', 'an1', '测试', '已核验');
            INSERT INTO characters VALUES
                ('宁', 'ning', 'ning2', '测试', '已核验');
            """
        )
        self.assertEqual(提取名字("和光同尘", 2), ["和光", "光同", "同尘"])
        第一批 = 生成基础候选(
            连接, "王", 2, ["温润君子"], "", "尘", "", 7, ["火"], 12
        )
        第二批 = 生成基础候选(
            连接, "王", 2, ["温润君子"], "", "尘", "", 7, ["火"], 12
        )
        self.assertEqual(第一批, 第二批)
        self.assertTrue(all("尘" not in 项目["名字"] for 项目 in 第一批))
        self.assertTrue(any(项目["名字"] == "和光" for 项目 in 第一批))
        连接.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
