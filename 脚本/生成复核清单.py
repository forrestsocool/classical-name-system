from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


根目录 = Path(__file__).resolve().parents[1]
默认数据库 = 根目录 / "构建产物" / "起名系统.sqlite3"
默认输出 = 根目录 / "构建产物" / "古籍片段复核清单.md"


def 生成清单(数据库: Path, 输出: Path, 每个方向数量: int = 8) -> None:
    连接 = sqlite3.connect(数据库)
    连接.row_factory = sqlite3.Row
    try:
        方向 = 连接.execute(
            """
            SELECT d.name, k.keyword
            FROM directions d
            JOIN direction_keywords k ON k.direction_id = d.id
            ORDER BY d.id, k.rowid
            """
        ).fetchall()
        关键词组: dict[str, list[str]] = {}
        for 行 in 方向:
            关键词组.setdefault(行["name"], []).append(行["keyword"])

        行列表 = [
            "# 古籍片段复核清单",
            "",
            "状态：待核验。复核通过后，使用片段编号开启候选资格。",
            "",
        ]
        已列出: set[int] = set()
        for 方向名, 关键词 in 关键词组.items():
            行列表.extend([f"## {方向名}", "", "| 片段编号 | 古籍 | 篇章 | 原文 |", "| ---: | --- | --- | --- |"])
            条件 = " OR ".join("p.text LIKE ?" for _ in 关键词)
            参数 = [f"%{项目}%" for 项目 in 关键词]
            结果 = 连接.execute(
                f"""
                SELECT p.id, b.name AS book, p.section_title, p.text
                FROM passages p
                JOIN books b ON b.id = p.book_id
                WHERE p.status = '待核验' AND ({条件})
                ORDER BY p.id
                LIMIT ?
                """,
                [*参数, 每个方向数量],
            ).fetchall()
            for 项目 in 结果:
                已列出.add(项目["id"])
                原文 = 项目["text"].replace("|", "\\|").replace("\n", " ")
                行列表.append(
                    f"| {项目['id']} | {项目['book']} | {项目['section_title']} | {原文} |"
                )
            if not 结果:
                行列表.append("| - | - | - | 暂无匹配片段 |")
            行列表.append("")

        行列表.extend(
            [
                "## 复核命令",
                "",
                "```powershell",
                "python .\\脚本\\标记核验片段.py 片段编号",
                "```",
                "",
                f"清单覆盖片段数：{len(已列出)}",
            ]
        )
        输出.parent.mkdir(parents=True, exist_ok=True)
        输出.write_text("\n".join(行列表) + "\n", encoding="utf-8")
    finally:
        连接.close()


def 主程序() -> int:
    解析器 = argparse.ArgumentParser(description="生成古籍片段人工复核清单")
    解析器.add_argument("--数据库", type=Path, default=默认数据库)
    解析器.add_argument("--输出", type=Path, default=默认输出)
    解析器.add_argument("--每个方向数量", type=int, default=8)
    参数 = 解析器.parse_args()
    生成清单(参数.数据库, 参数.输出, 参数.每个方向数量)
    print(f"已生成：{参数.输出}")
    return 0


if __name__ == "__main__":
    raise SystemExit(主程序())
