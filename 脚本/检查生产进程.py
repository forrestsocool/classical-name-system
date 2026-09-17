import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from 后端.数据库 import 连接数据库

with 连接数据库() as c:
    row = c.execute("SELECT heartbeat>now()-interval '5 minutes' AND status<>'已停止' AS alive FROM app_worker WHERE id=1").fetchone()
sys.exit(0 if row and row["alive"] else 1)
