from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


根目录 = Path(__file__).resolve().parents[1]
默认输入 = 根目录 / "古籍与东亚年号参考资料" / "古籍全文" / "周易.txt"
默认输出 = 根目录 / "构建产物" / "周易字形核验.json"
标题正则 = re.compile(r"^【([^】]+)】$")
卦名语境正则 = re.compile(
    r"《干》|干（卦|干下|干上|乎干|干行|干，健|干为|干知|干以|"
    r"干之策|战乎干|干，天|干，阳物|夫干|大哉干|干始|成象为干|"
    r"辟户谓之干|盖取诸《干》|干君|干，确然|干，天下"
)
保留语境正则 = re.compile(r"干干|干事|干父|干母|干胏|干肉|干城|于干")


def 分类(行: str, 位置: int) -> tuple[str, str, str]:
    左右 = 行[max(0, 位置 - 10) : min(len(行), 位置 + 14)]
    if 卦名语境正则.search(左右):
        return "乾", "高", "卦名、卦象或八卦语境"
    if 保留语境正则.search(左右):
        return "干", "高", "动词、名词或地名语境"
    return "待定", "待核验", "仅凭局部语境不能安全判断"


def 生成报告(路径: Path) -> dict:
    原文 = 路径.read_text(encoding="utf-8")
    结果: list[dict] = []
    标题结果: list[dict] = []
    字符总数 = 0
    for 行号, 行 in enumerate(原文.splitlines(), 1):
        标题匹配 = 标题正则.fullmatch(行.strip())
        if 标题匹配 and "干（卦一）" in 标题匹配.group(1):
            标题结果.append(
                {
                    "行": 行号,
                    "原文": 标题匹配.group(1),
                    "建议": 标题匹配.group(1).replace("干（卦一）", "乾（卦一）"),
                    "状态": "高置信修正规则",
                }
            )
        起点 = 0
        while True:
            位置 = 行.find("干", 起点)
            if 位置 < 0:
                break
            建议, 置信度, 依据 = 分类(行, 位置)
            结果.append(
                {
                    "行": 行号,
                    "列": 位置 + 1,
                    "原文片段": 行[max(0, 位置 - 16) : min(len(行), 位置 + 17)],
                    "原字符": "干",
                    "建议字符": 建议,
                    "置信度": 置信度,
                    "依据": 依据,
                }
            )
            字符总数 += 1
            起点 = 位置 + 1
    return {
        "报告版本": "1.0",
        "说明": "原始文件只读保留；正文只生成核验建议，不自动覆盖原文。",
        "文件": str(路径),
        "文件哈希": hashlib.sha256(路径.read_bytes()).hexdigest(),
        "原文干字总数": 字符总数,
        "章节标题修正规则": 标题结果,
        "正文逐字核验": 结果,
        "统计": {
            "建议改为乾": sum(项目["建议字符"] == "乾" for 项目 in 结果),
            "建议保留干": sum(项目["建议字符"] == "干" for 项目 in 结果),
            "待人工核验": sum(项目["建议字符"] == "待定" for 项目 in 结果),
        },
    }


def 主程序() -> int:
    解析器 = argparse.ArgumentParser(description="生成周易干乾字形核验报告")
    解析器.add_argument("--输入", type=Path, default=默认输入)
    解析器.add_argument("--输出", type=Path, default=默认输出)
    参数 = 解析器.parse_args()
    if not 参数.输入.exists():
        raise FileNotFoundError(f"文件不存在：{参数.输入}")
    参数.输出.parent.mkdir(parents=True, exist_ok=True)
    报告 = 生成报告(参数.输入)
    参数.输出.write_text(
        json.dumps(报告, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"已生成：{参数.输出}")
    print(json.dumps(报告["统计"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(主程序())
