import unittest

from 后端.姓名热度 import 匹配姓名热度, 读取姓名报告


class 姓名热度测试(unittest.TestCase):
    def test本地报告包含三个完整热门字表和热门名表(self):
        报告 = 读取姓名报告()["报告"]
        self.assertEqual([项目["统计年度"] for 项目 in 报告], [2019, 2020, 2021])
        self.assertTrue(all(len(项目["热门字"]) == 50 for 项目 in 报告))
        self.assertTrue(all(len(项目["热门名"]["男"]) == 10 for 项目 in 报告))
        self.assertTrue(all(len(项目["热门名"]["女"]) == 10 for 项目 in 报告))

    def test热门名字同时返回热门名和热门字提示(self):
        结果 = 匹配姓名热度("梓涵")
        self.assertTrue(结果["命中"])
        self.assertEqual({项目["统计年度"] for 项目 in 结果["热门名"]}, {2019, 2020, 2021})
        self.assertIn("梓", {项目["字"] for 项目 in 结果["热门字"]})
        self.assertTrue(any("热门名" in 提示 for 提示 in 结果["提示"]))

    def test二〇一九年数据包含图表中的热门字和热门名(self):
        报告 = 读取姓名报告()["报告"][0]
        self.assertEqual(报告["统计年度"], 2019)
        self.assertEqual(报告["热门字"][28], "沫")
        self.assertEqual(报告["热门字"][31], "钰")
        self.assertEqual(报告["热门名"]["男"][0], {"名字": "浩宇", "人数": 20102})
        self.assertEqual(报告["热门名"]["女"][3], {"名字": "诗涵", "人数": 20862})

    def test不热门名字不产生误报(self):
        结果 = 匹配姓名热度("知远")
        self.assertFalse(结果["命中"])
        self.assertEqual(结果["热门字"], [])
        self.assertEqual(结果["热门名"], [])
        self.assertEqual(结果["提示"], [])

    def test只匹配名字不把姓氏算作热门字(self):
        结果 = 匹配姓名热度("李")
        self.assertFalse(结果["命中"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
