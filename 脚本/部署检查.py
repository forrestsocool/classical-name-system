from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path


根目录 = Path(__file__).resolve().parents[1]
默认数据库 = Path(os.getenv("起名数据库路径", str(根目录 / "构建产物" / "起名系统.sqlite3")))
必需文件 = (
    根目录 / "前端" / "index.html",
    根目录 / "前端" / "app.js",
    根目录 / "后端" / "起名服务.py",
    根目录 / "后端" / "模型接口.py",
)
必需表 = {
    "sources",
    "books",
    "passages",
    "eras",
    "audit_issues",
    "characters",
    "character_elements",
    "candidate_phrases",
    "name_runs",
    "candidates",
    "model_candidates",
    "model_metrics",
    "favorites",
    "feedback",
}


def 检查数据库(数据库: Path) -> dict:
    if not 数据库.exists():
        raise FileNotFoundError(f"数据库不存在：{数据库}")
    with sqlite3.connect(数据库) as 连接:
        完整性 = 连接.execute("PRAGMA integrity_check").fetchone()[0]
        表名 = {
            行[0]
            for 行 in 连接.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        缺少表 = sorted(必需表 - 表名)
        if 完整性 != "ok":
            raise RuntimeError(f"数据库完整性检查失败：{完整性}")
        if 缺少表:
            raise RuntimeError(f"数据库缺少表：{','.join(缺少表)}")
        return {
            "完整性": 完整性,
            "古籍数": 连接.execute("SELECT COUNT(*) FROM books").fetchone()[0],
            "片段数": 连接.execute("SELECT COUNT(*) FROM passages").fetchone()[0],
            "候选词组数":连接.execute("SELECT COUNT(*) FROM candidate_phrases").fetchone()[0],
            "待处理问题数": 连接.execute(
                "SELECT COUNT(*) FROM audit_issues WHERE status = '待处理'"
            ).fetchone()[0],
        }


def 主程序() -> int:
    解析器 = argparse.ArgumentParser(description="检查起名系统部署条件")
    解析器.add_argument("--数据库", type=Path, default=默认数据库)
    参数 = 解析器.parse_args()
    缺少文件 = [str(路径) for 路径 in 必需文件 if not 路径.exists()]
    if 缺少文件:
        raise RuntimeError(f"缺少必需文件：{','.join(缺少文件)}")
    管理密钥 = os.getenv("起名管理密钥", "")
    if len(管理密钥) < 16:
        raise RuntimeError("起名管理密钥至少需要16个字符")
    if not 管理密钥.isascii():
        raise RuntimeError("起名管理密钥只能使用ASCII字符")
    结果 = {
        "状态": "通过",
        "管理密钥已配置": True,
        "模型已配置": bool(os.getenv("起名模型密钥") and os.getenv("起名模型名称")),
        "数据库": 检查数据库(参数.数据库),
    }
    print(json.dumps(结果, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(主程序())
