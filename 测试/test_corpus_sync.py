"""Integration checks against a disposable PostgreSQL database, never production tables."""
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from 后端.数据库 import 初始化数据库
from 脚本.同步校勘资料 import 同步

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Requires a disposable PostgreSQL database")
class CorpusSyncTests(unittest.TestCase):
    def test_sync_preserves_history_and_rolls_back_failures(self):
        base = os.environ["TEST_DATABASE_URL"]
        name = "codex_corpus_test_" + uuid.uuid4().hex
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
        cfg = conninfo_to_dict(base)
        cfg["dbname"] = name
        try:
            with tempfile.TemporaryDirectory() as temporary, psycopg.connect(make_conninfo(**cfg), row_factory=dict_row) as c:
                source = Path(temporary) / "source.sqlite3"
                with sqlite3.connect(ROOT / "构建产物/起名系统.sqlite3") as original, sqlite3.connect(source) as snapshot:
                    original.backup(snapshot)
                    snapshot.row_factory = sqlite3.Row
                    passage = dict(snapshot.execute("SELECT * FROM passages WHERE can_generate=1 LIMIT 1").fetchone())
                    book = dict(snapshot.execute("SELECT * FROM books WHERE id=?", (passage["book_id"],)).fetchone())
                    origin = dict(snapshot.execute("SELECT * FROM sources WHERE id=?", (passage["source_id"],)).fetchone())
                    expected = snapshot.execute("SELECT count(*) FROM passages WHERE can_generate=1").fetchone()[0]
                初始化数据库(c)
                for table, row in (("sources", {**origin, "id": 70000}),
                                   ("books", {**book, "id": 80000, "source_id": 70000}),
                                   ("passages", {**passage, "id": 90000, "source_id": 70000, "book_id": 80000})):
                    c.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(sql.Identifier(table),
                        sql.SQL(",").join(map(sql.Identifier, row)), sql.SQL(",").join(sql.Placeholder() for _ in row)), list(row.values()))
                c.execute("INSERT INTO passages(id,source_id,book_id,section_title,ordinal,text,source_line_start,source_line_end,status,can_generate) VALUES (90001,70000,80000,'obsolete',99999,'obsolete text',1,1,'已核验',1)")
                c.execute("INSERT INTO favorites(collection_id,full_name,given_name,source_passage_id,source_text,created_at) VALUES ('history','李清','清',90001,'obsolete text','2026-09-18')")
                c.commit()
                dry = 同步(source, c)
                self.assertEqual(dry["eligible_passages"], expected)
                self.assertEqual(c.execute("SELECT count(*) AS n FROM passages").fetchone()["n"], 2)
                c.commit()
                # Failure after updates have begun must restore eligibility and all inserted rows.
                bad = Path(temporary) / "bad.sqlite3"
                with sqlite3.connect(source) as good, sqlite3.connect(bad) as broken:
                    good.backup(broken)
                    broken.execute("UPDATE passages SET book_id=-1 WHERE id=(SELECT max(id) FROM passages)")
                    broken.commit()
                with self.assertRaises(KeyError):
                    同步(bad, c, apply=True)
                self.assertEqual(c.execute("SELECT count(*) AS n FROM passages WHERE can_generate=1").fetchone()["n"], 2)
                c.commit()
                result = 同步(source, c, apply=True)
                c.commit()
                self.assertEqual(result["eligible_passages"], expected)
                self.assertEqual(result["reused_passages"], 1)
                self.assertEqual(c.execute("SELECT text FROM passages WHERE id=90000").fetchone()["text"], passage["text"])
                obsolete = c.execute("SELECT can_generate,active_for_recall FROM passages WHERE id=90001").fetchone()
                self.assertEqual(obsolete["can_generate"], 0)
                self.assertFalse(obsolete["active_for_recall"])
                self.assertEqual(c.execute("SELECT source_passage_id FROM favorites").fetchone()["source_passage_id"], 90001)
                c.commit()
                self.assertTrue(同步(source, c, apply=True)["already_applied"])
                c.commit()
                with psycopg.connect(make_conninfo(**cfg), autocommit=True) as producer:
                    producer.execute("SELECT pg_advisory_lock(2026091702)")
                    with self.assertRaisesRegex(RuntimeError, "停止"):
                        同步(source, c, apply=True)
        finally:
            with psycopg.connect(base, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


if __name__ == "__main__":
    unittest.main()
