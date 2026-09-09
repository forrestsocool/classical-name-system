from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


根目录 = Path(__file__).resolve().parents[1]
默认数据库 = 根目录 / "构建产物" / "起名系统.sqlite3"


def 主程序() -> int:
    解析器 = argparse.ArgumentParser(description="将人工复核通过的语料片段加入候选池")
    解析器.add_argument("片段编号", nargs="+", type=int)
    解析器.add_argument("--数据库", type=Path, default=默认数据库)
    解析器.add_argument("--复核人", default="命令行复核")
    解析器.add_argument("--备注", default="")
    参数 = 解析器.parse_args()
    连接 = sqlite3.connect(参数.数据库)
    try:
        占位符 = ",".join("?" for _ in 参数.片段编号)
        游标 = 连接.execute(
            f"""
            UPDATE passages
            SET status = '已核验', can_generate = 1,
                reviewed_at = ?, reviewer = ?, review_note = ?
            WHERE id IN ({占位符})
            """,
            [datetime.now(timezone.utc).isoformat(), 参数.复核人, 参数.备注, *参数.片段编号],
        )
        连接.commit()
        print(f"已核验片段：{游标.rowcount} 条")
        return 0
    finally:
        连接.close()


if __name__ == "__main__":
    raise SystemExit(主程序())
