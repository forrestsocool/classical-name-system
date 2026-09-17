"""Copy a consistent SQLite snapshot into an empty PostgreSQL schema, atomically."""
import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from psycopg import sql
from psycopg.types.json import Jsonb
from 后端.数据库 import 连接数据库, 初始化数据库

表顺序 = (
    "schema_version", "sources", "books", "passages", "eras", "directions",
    "direction_keywords", "audit_issues", "name_runs", "candidates", "candidate_phrases",
    "characters", "character_elements", "model_candidates", "model_metrics", "favorites", "feedback",
)


def 迁移(源路径, 目标):
    源路径 = Path(源路径).resolve(strict=True)
    with closing(sqlite3.connect(源路径.as_uri() + "?mode=ro", uri=True)) as 原库, \
            closing(sqlite3.connect(":memory:")) as 快照:
        原库.backup(快照)  # includes committed WAL; never writes the input database
        if 快照.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite 完整性检查未通过")
        with 目标.transaction():
            目标.execute("SELECT pg_advisory_xact_lock(2026091701)")
            if 目标.execute("SELECT to_regclass('sources') AS name").fetchone()["name"]:
                raise RuntimeError("目标数据库已初始化，拒绝重复迁移或覆盖；请使用空数据库")
            初始化数据库(目标)
            统计 = {}
            for 表 in 表顺序:
                信息 = 快照.execute(f'PRAGMA table_info("{表}")').fetchall()
                if not 信息:
                    raise RuntimeError(f"源数据库缺少表：{表}")
                列 = [x[1] for x in 信息]
                写入 = sql.SQL("COPY {} ({}) FROM STDIN").format(
                    sql.Identifier(表), sql.SQL(",").join(map(sql.Identifier, 列)))
                with 目标.cursor().copy(写入) as 导入:
                    for 行 in 快照.execute(f'SELECT * FROM "{表}"'):
                        导入.write_row(行)
                原数 = 快照.execute(f'SELECT COUNT(*) FROM "{表}"').fetchone()[0]
                新数 = 目标.execute(sql.SQL("SELECT COUNT(*) AS n FROM {}").format(sql.Identifier(表))).fetchone()["n"]
                if 原数 != 新数:
                    raise RuntimeError(f"迁移数量不一致：{表}")
                统计[表] = 新数
                if any(x[1] == "id" and x[2].upper() == "INTEGER" and x[5] for x in 信息):
                    目标.execute(sql.SQL("SELECT setval(pg_get_serial_sequence(%s, 'id'), COALESCE(MAX(id),1), COUNT(*)>0) FROM {}").format(sql.Identifier(表)), (表,))
            # Retain anonymous ownership and generated stock for administrative archive only.
            for 表 in ("run_owners", "feed_materials"):
                if not 快照.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (表,)).fetchone():
                    continue
                目标.execute(sql.SQL("CREATE TABLE {} (record JSONB NOT NULL)").format(sql.Identifier("legacy_" + 表)))
                快照.row_factory = sqlite3.Row
                for 行 in 快照.execute(f'SELECT * FROM "{表}"'):
                    目标.execute(sql.SQL("INSERT INTO {} VALUES (%s)").format(sql.Identifier("legacy_" + 表)), (Jsonb(dict(行)),))
                统计["legacy_" + 表] = 快照.execute(f'SELECT COUNT(*) FROM "{表}"').fetchone()[0]
                快照.row_factory = None
            目标.execute("INSERT INTO app_migrations(id,summary) VALUES ('sqlite-v1',%s)", (Jsonb(统计),))
    return 统计


if __name__ == "__main__":
    参数 = argparse.ArgumentParser(description=__doc__)
    参数.add_argument("--源", type=Path, default=Path("构建产物/起名系统.sqlite3"))
    选项 = 参数.parse_args()
    with 连接数据库() as 目标:
        print(json.dumps(迁移(选项.源, 目标), ensure_ascii=False, indent=2))
