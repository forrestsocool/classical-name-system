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
        self.assertEqual(sum(报告["分区统计"].values()), 305)
        self.assertEqual(len({项目["篇号"] for 项目 in 报告["篇章"]}), 305)
        self.assertTrue(all(项目["原始起始行"] <= 项目["原始结束行"] for 项目 in 报告["篇章"]))
        self.assertTrue(
            all(项目["篇名状态"] == "首句候选，待人工核对" for 项目 in 报告["篇章"])
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
