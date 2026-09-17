"""Requires pg_dump on PATH. Stores a PostgreSQL custom-format backup."""
import argparse
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from psycopg.conninfo import conninfo_to_dict

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--目录", type=Path, default=Path("构建产物/数据库备份"))
    args = parser.parse_args()
    config = conninfo_to_dict(os.environ["DATABASE_URL"])
    env = os.environ.copy()
    for name, value in config.items():
        mapped = {"dbname": "PGDATABASE", "user": "PGUSER", "password": "PGPASSWORD", "host": "PGHOST", "port": "PGPORT",
                  "sslmode": "PGSSLMODE", "sslrootcert": "PGSSLROOTCERT", "sslcert": "PGSSLCERT", "sslkey": "PGSSLKEY"}.get(name)
        if mapped:
            env[mapped] = value
    args.目录.mkdir(parents=True, exist_ok=True)
    target = args.目录 / ("names-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".dump")
    try:
        subprocess.run(["pg_dump", "--format=custom", "--no-password", "--file", str(target)], env=env, check=True)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    print(target)
