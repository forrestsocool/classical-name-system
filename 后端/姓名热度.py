"""公安部全国姓名报告的热门字、热门名匹配。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


根目录 = Path(__file__).resolve().parents[1]
资料路径 = 根目录 / "公安部姓名报告参考资料" / "公安部姓名报告热度.json"


@lru_cache(maxsize=1)
def 读取姓名报告() -> dict:
    """读取随代码发布的本地资料，不访问外网，服务离线时也可提示。"""
    try:
        with 资料路径.open("r", encoding="utf-8") as 文件:
            资料 = json.load(文件)
    except (OSError, json.JSONDecodeError):
        return {"报告": []}
    if not isinstance(资料, dict) or not isinstance(资料.get("报告"), list):
        return {"报告": []}
    return 资料


def 匹配姓名热度(名字: str) -> dict:
    """匹配名字部分，返回可直接给网页展示的解释数据。"""
    结果 = {"命中": False, "热门字": [], "热门名": [], "提示": []}
    if not isinstance(名字, str) or not 名字:
        return 结果

    for 报告 in 读取姓名报告().get("报告", []):
        年度 = 报告.get("统计年度")
        字列表 = 报告.get("热门字", [])
        if not isinstance(年度, int) or not isinstance(字列表, list):
            continue
        for 排名, 字 in enumerate(字列表, 1):
            if 字 not in 名字:
                continue
            结果["热门字"].append({"统计年度": 年度, "排名": 排名, "字": 字})

        名字表 = 报告.get("热门名", {})
        if not isinstance(名字表, dict):
            continue
        for 性别, 项目列表 in 名字表.items():
            if not isinstance(项目列表, list):
                continue
            for 排名, 项目 in enumerate(项目列表, 1):
                if not isinstance(项目, dict) or 项目.get("名字") != 名字:
                    continue
                命中 = {
                    "统计年度": 年度,
                    "性别": 性别,
                    "排名": 排名,
                    "名字": 名字,
                }
                if isinstance(项目.get("人数"), int):
                    命中["人数"] = 项目["人数"]
                结果["热门名"].append(命中)

    结果["热门字"].sort(key=lambda x: (x["统计年度"], x["排名"]))
    结果["热门名"].sort(key=lambda x: (x["统计年度"], x["性别"], x["排名"]))
    for 项目 in 结果["热门名"]:
        人数 = f"（{项目['人数']}人）" if "人数" in 项目 else ""
        结果["提示"].append(
            f"名字“{名字}”入选{项目['统计年度']}年{项目['性别']}宝宝热门名第{项目['排名']}位{人数}"
        )
    for 项目 in 结果["热门字"]:
        结果["提示"].append(
            f"名字中的“{项目['字']}”入选{项目['统计年度']}年新生儿热门字第{项目['排名']}位"
        )
    结果["命中"] = bool(结果["热门字"] or 结果["热门名"])
    if 结果["命中"]:
        结果["说明"] = "以上提示来自公安部全国姓名报告历史新生儿登记统计，仅用于识别流行度，不代表当前实时重名人数。"
    return 结果
