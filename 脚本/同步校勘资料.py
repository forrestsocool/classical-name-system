"""Synchronize reviewed reference data without replacing user history or passage IDs.

Dry-run by default. Stop the producer and take a pg_dump before --apply.
Obsolete passages remain available to historical references, but cannot generate.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from psycopg import sql
from psycopg.types.json import Jsonb
from 后端.数据库 import 连接数据库


def 同步(源路径, 目标, apply=False):
    with closing(sqlite3.connect(Path(源路径).resolve().as_uri() + "?mode=ro", uri=True)) as source, \
            closing(sqlite3.connect(":memory:")) as snapshot:
        source.backup(snapshot)
        if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("源数据库完整性检查失败")
        snapshot.row_factory = sqlite3.Row
        tables = ("sources", "books", "passages", "characters", "character_elements", "candidate_phrases")
        data = {table: [dict(r) for r in snapshot.execute(f'SELECT * FROM "{table}" ORDER BY rowid')] for table in tables}
    if not data["passages"] or not any(r["can_generate"] == 1 for r in data["passages"]):
        raise ValueError("源数据库没有可生成的校勘片段，拒绝停用全部生产资料")
    digest = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    migration = "reviewed-corpus-" + digest
    with 目标.transaction(force_rollback=not apply):
        if not 目标.execute("SELECT pg_try_advisory_xact_lock(2026091702) AS locked").fetchone()["locked"]:
            raise RuntimeError("请先停止持续生产进程再同步资料")
        目标.execute("SELECT pg_advisory_xact_lock(2026091701)")
        previous = 目标.execute("SELECT summary FROM app_migrations WHERE id=%s", (migration,)).fetchone()
        if previous:
            return {**previous["summary"], "already_applied": True}
        # Prevent a concurrent administrative review from being silently overwritten.
        目标.execute("LOCK TABLE sources,books,passages,characters,character_elements,candidate_phrases IN SHARE ROW EXCLUSIVE MODE")
        stats = {"source_sha256": digest, "input_passages": len(data["passages"]), "inserted_passages": 0, "reused_passages": 0}

        def insert(table, row):
            columns = list(row)
            return 目标.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING id").format(
                sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.SQL(",").join(sql.Placeholder() for _ in columns)), list(row.values())).fetchone()["id"]

        sources = {}
        for row in data["sources"]:
            found = 目标.execute("SELECT id FROM sources WHERE file_name=%s AND sha256=%s ORDER BY id LIMIT 1",
                               (row["file_name"], row["sha256"])).fetchone()
            if found:
                sources[row["id"]] = found["id"]
            else:
                # Keep the old source hash and its old passages intact for provenance.
                目标.execute("UPDATE sources SET path=path || '.archive-' || id WHERE path=%s", (row["path"],))
                sources[row["id"]] = insert("sources", {k: v for k, v in row.items() if k != "id"})
        books = {}
        for row in data["books"]:
            sid = sources[row["source_id"]]
            found = 目标.execute("SELECT id FROM books WHERE source_id=%s AND name=%s", (sid, row["name"])).fetchone()
            books[row["id"]] = found["id"] if found else insert("books", {"source_id": sid, "name": row["name"]})

        existing = {}
        for row in 目标.execute("SELECT id,source_id,book_id,section_title,ordinal,text FROM passages ORDER BY id"):
            key = tuple(row[k] for k in ("source_id", "book_id", "section_title", "ordinal", "text"))
            if key in existing:
                raise ValueError("目标存在重复原文定位，拒绝猜测历史编号")
            existing[key] = row["id"]
        目标.execute("UPDATE passages SET can_generate=0 WHERE can_generate<>0")
        passages = {}
        for original in data["passages"]:
            row = {k: v for k, v in original.items() if k != "id"}
            row.update(source_id=sources[row["source_id"]], book_id=books[row["book_id"]])
            key = tuple(row[k] for k in ("source_id", "book_id", "section_title", "ordinal", "text"))
            if key in existing:
                pid = existing[key]
                columns = list(row)
                目标.execute(sql.SQL("UPDATE passages SET {} WHERE id=%s").format(
                    sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(k)) for k in columns)), [*row.values(), pid])
                stats["reused_passages"] += 1
            else:
                pid = insert("passages", row)
                stats["inserted_passages"] += 1
            passages[original["id"]] = pid
        for table, conflict in (("characters", ("char",)), ("character_elements", ("char", "method")),
                                ("candidate_phrases", ("passage_id", "phrase", "direction"))):
            for original in data[table]:
                row = {k: v for k, v in original.items() if k != "id"}
                if table == "candidate_phrases":
                    row["passage_id"] = passages[row["passage_id"]]
                columns = list(row)
                目标.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}").format(
                    sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, columns)),
                    sql.SQL(",").join(sql.Placeholder() for _ in columns), sql.SQL(",").join(map(sql.Identifier, conflict)),
                    sql.SQL(",").join(sql.SQL("{}=excluded.{}").format(sql.Identifier(k), sql.Identifier(k)) for k in columns if k not in conflict)), list(row.values()))
        stats["eligible_passages"] = 目标.execute("SELECT count(*) AS n FROM passages WHERE can_generate=1").fetchone()["n"]
        expected = sum(r["can_generate"] == 1 for r in data["passages"])
        if stats["eligible_passages"] != expected:
            raise ValueError("可生成片段数量不一致，回滚")
        # The corpus has expanded; previously exhausted sources may now have new candidates.
        目标.execute("UPDATE app_source_progress SET retry_at=now()")
        目标.execute("INSERT INTO app_migrations(id,summary) VALUES (%s,%s)", (migration, Jsonb(stats)))
        return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with 连接数据库() as connection:
        print(json.dumps({"applied": args.apply, **同步(args.source, connection, args.apply)}, ensure_ascii=False))
