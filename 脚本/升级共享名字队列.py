"""Apply the shared-name inventory migration atomically; run with producer stopped."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from 后端.数据库 import 连接数据库


def 升级(connection):
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(2026091701)")
        migration = Path(__file__).resolve().parents[1] / "后端/迁移/003_共享名字队列.sql"
        connection.execute(migration.read_text(encoding="utf-8"))
        return connection.execute("""SELECT p.name_length,p.enabled,count(m.id) AS stock
            FROM app_profiles p LEFT JOIN app_materials m ON m.profile_id=p.id
            WHERE p.surname='' GROUP BY p.id ORDER BY p.name_length""").fetchall()


if __name__ == "__main__":
    with 连接数据库() as connection:
        print(json.dumps(升级(connection), ensure_ascii=False))
