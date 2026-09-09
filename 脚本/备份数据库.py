from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


根目录 = Path(__file__).resolve().parents[1]
默认数据库 = 根目录 / "构建产物" / "起名系统.sqlite3"
默认输出目录 = 根目录 / "构建产物" / "数据库备份"


def 备份数据库(数据库: Path, 输出目录: Path) -> Path:
    if not 数据库.exists():
        raise FileNotFoundError(f"数据库不存在：{数据库}")
    输出目录.mkdir(parents=True, exist_ok=True)
    时间标记 = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    目标 = 输出目录 / f"起名系统-{时间标记}.sqlite3"
    with sqlite3.connect(数据库) as 来源:
        with sqlite3.connect(目标) as 备份:
            来源.backup(备份)
            检查结果 = 备份.execute("PRAGMA integrity_check").fetchone()[0]
            if 检查结果 != "ok":
                raise RuntimeError(f"备份完整性检查失败：{检查结果}")
    return 目标


def 主程序() -> int:
    解析器 = argparse.ArgumentParser(description="备份起名系统 SQLite 数据库")
    解析器.add_argument("--数据库", type=Path, default=默认数据库)
    解析器.add_argument("--输出目录", type=Path, default=默认输出目录)
    参数 = 解析器.parse_args()
    目标 = 备份数据库(参数.数据库, 参数.输出目录)
    print(json.dumps({"备份文件": str(目标), "状态": "完成"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(主程序())
