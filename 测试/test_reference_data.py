from __future__ import annotations

import json
import unittest
from pathlib import Path


根目录 = Path(__file__).resolve().parents[1]


class 参考资料结构测试(unittest.TestCase):
    def test诗经篇章结构清单(self) -> None:
        报告路径 = 根目录 / "构建产物" / "诗经篇章结构.json"
        报告 = json.loads(报告路径.read_text(encoding="utf-8"))
        self.assertEqual(报告["篇数"], 305)
        self.assertEqual(报告["正式篇名数"], 305)
        self.assertEqual(sum(报告["分区统计"].values()), 305)
        self.assertEqual(len({项目["篇号"] for 项目 in 报告["篇章"]}), 305)
        self.assertTrue(all(项目["原始起始行"] <= 项目["原始结束行"] for 项目 in 报告["篇章"]))
        self.assertTrue(
            all(项目["篇名状态"] == "已按目录核对" for 项目 in 报告["篇章"])
        )
        self.assertTrue(all(项目["正式篇名"] for 项目 in 报告["篇章"]))
        self.assertTrue(all(项目["分区篇序"] >= 1 for 项目 in 报告["篇章"]))

    def test周易字形核验清单(self) -> None:
        报告路径 = 根目录 / "构建产物" / "周易字形核验.json"
        报告 = json.loads(报告路径.read_text(encoding="utf-8"))
        self.assertEqual(报告["原文干字总数"], 79)
        self.assertEqual(报告["统计"]["建议改为乾"], 53)
        self.assertEqual(报告["统计"]["建议保留干"], 26)
        self.assertEqual(报告["统计"]["待人工核验"], 0)
        self.assertEqual(报告["章节标题修正规则"][0]["建议"], "01. 乾（卦一）")
        展示文件 = 根目录 / "构建产物" / "展示资料" / "周易-规范化展示.txt"
        self.assertTrue(展示文件.exists())
        self.assertEqual(展示文件.read_text(encoding="utf-8").splitlines()[0], "【01. 乾（卦一）】")


if __name__ == "__main__":
    unittest.main(verbosity=2)
