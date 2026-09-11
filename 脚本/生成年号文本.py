from __future__ import annotations

import argparse
import re
from pathlib import Path


根目录 = Path(__file__).resolve().parents[1]
默认来源文件 = 根目录 / "古籍与东亚年号参考资料" / "儒家文化圈历史年号汇总.txt"
默认目标文件 = 根目录 / "古籍与东亚年号参考资料" / "古籍全文" / "东亚年号.txt"


def 生成年号文本(源文件: Path, 目标文件: Path) -> dict:
    行列表 = 源文件.read_text(encoding="utf-8").splitlines()
    当前地区 = "中国"
    当前分类 = "西汉年号"
    章节字典: dict[str, list[str]] = {}
    已收录年号: set[str] = set()

    for 原行 in 行列表:
        行 = 原行.strip()
        if not 行:
            continue
        if "｜" not in 行:
            if 行 in ["中国", "朝鲜半岛", "越南", "日本"]:
                当前地区 = 行
            else:
                清洗分类 = re.sub(r"\{\{.*?\}\}|rowspan=\".*?\"\|", "", 行).strip()
                当前分类 = f"{当前地区}·{清洗分类}" if 当前地区 != "中国" else 清洗分类
            continue

        字段 = [项.strip() for 项 in 行.split("｜")]
        年号名 = 字段[0]
        年号名 = re.sub(r"\{\{.*?\}\}|rowspan=\".*?\"\|", "", 年号名).strip()

        # 过滤非汉字、存疑或含残缺字符的记录
        if (
            not re.fullmatch(r"[\u4e00-\u9fff]{1,4}", 年号名)
            or "？" in 行
            or "?" in 行
            or "□" in 行
        ):
            continue

        时期 = 字段[1] if len(字段) > 1 else ""
        时期 = re.sub(r"\{\{.*?\}\}|rowspan=\".*?\"\|", "", 时期).strip()
        附加 = 字段[2] if len(字段) > 2 else ""
        附加 = re.sub(r"\{\{.*?\}\}|rowspan=\".*?\"\|", "", 附加).strip()

        描述部分 = []
        if 时期 and 时期 != "？":
            描述部分.append(时期)
        if 附加 and 附加 != "？":
            描述部分.append(附加)

        描述文本 = f"（{'，'.join(描述部分)}）" if 描述部分 else "。"
        正文行 = (
            f"{年号名}：{当前分类}{描述文本}。"
            if not 描述文本.endswith("。")
            else f"{年号名}：{当前分类}{描述文本}"
        )

        章节字典.setdefault(当前分类, []).append(正文行)
        已收录年号.add(年号名)

    输出行 = []
    for 分类, 条目列表 in 章节字典.items():
        if not 条目列表:
            continue
        输出行.append(f"【{分类}】")
        输出行.extend(条目列表)
        输出行.append("")

    目标文件.parent.mkdir(parents=True, exist_ok=True)
    最终文本 = "\n".join(输出行).strip() + "\n"
    目标文件.write_text(最终文本, encoding="utf-8")

    统计 = {
        "来源文件": str(源文件),
        "目标文件": str(目标文件),
        "章节数": len(章节字典),
        "年号条目数": sum(len(v) for v in 章节字典.values()),
        "独立年号数": len(已收录年号),
        "总行数": len(最终文本.splitlines()),
        "总字符数": len(最终文本),
    }
    return 统计


def 主程序() -> int:
    解析器 = argparse.ArgumentParser(description="由历史年号汇总生成东亚年号古籍全文")
    解析器.add_argument("--源文件", type=Path, default=默认来源文件)
    解析器.add_argument("--目标文件", type=Path, default=默认目标文件)
    参数 = 解析器.parse_args()
    统计 = 生成年号文本(参数.源文件, 参数.目标文件)
    import json
    print(json.dumps(统计, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(主程序())
