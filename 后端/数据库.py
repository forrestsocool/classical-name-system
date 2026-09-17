"""PostgreSQL runtime and a read-only adapter for the existing naming rules."""
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def 连接数据库():
    地址 = os.getenv("DATABASE_URL", "")
    if not 地址.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("请配置 PostgreSQL DATABASE_URL")
    return psycopg.connect(地址, row_factory=dict_row, connect_timeout=5,
                           options="-c statement_timeout=15000 -c timezone=UTC")


def 初始化数据库(连接):
    # Deployment/migration only; API workers never race to run DDL.
    目录 = Path(__file__).with_name("迁移")
    for 文件 in sorted(目录.glob("*.sql")):
        连接.execute(文件.read_text(encoding="utf-8"))


class 资料行(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class 资料游标:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        row = self.cursor.fetchone()
        return 资料行(row) if row is not None else None

    def fetchall(self):
        return [资料行(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class 资料查询:
    """Only the static SELECT statements in 候选生成/智能筛选 use qmark notation.

    Values remain driver-bound; this is not a general SQLite compatibility layer.
    All new runtime writes and queries use native PostgreSQL SQL.
    """
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, params=()):
        if not query.lstrip().upper().startswith("SELECT "):
            raise ValueError("资料查询只允许 SELECT")
        return 资料游标(self.connection.execute(query.replace("?", "%s"), params))
