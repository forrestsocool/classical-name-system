import hmac
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import Field
from psycopg import sql

from .数据库 import 连接数据库
from .小程序业务 import 严格参数
from .模型接口 import 模型配置, 配置文件, 读取环境配置, 模型已配置, 验证模型地址


def 管理权限(x_admin_key: str = Header(default=""), authorization: str = Header(default="")):
    key = os.getenv("起名管理密钥", "")
    if os.getenv("起名管理密钥文件"):
        try:
            key = Path(os.environ["起名管理密钥文件"]).read_text(encoding="utf-8").strip()
        except OSError:
            key = ""
    if len(key) < 16 or not key.isascii():
        raise HTTPException(503, "管理密钥未正确配置")
    supplied = x_admin_key or (authorization[7:] if authorization.startswith("Bearer ") else "")
    if not hmac.compare_digest(supplied.encode(), key.encode()):
        raise HTTPException(403, "管理密钥不正确")


路由 = APIRouter(prefix="/api/admin", dependencies=[Depends(管理权限)])


class 档案参数(严格参数):
    surname: str = Field(pattern=r"^[\u3400-\u9fff]{1,2}$")
    name_length: Literal[1, 2] = 2
    enabled: bool = True


@路由.get("/profiles")
def 档案列表():
    with 连接数据库() as c:
        return c.execute("""SELECT p.*,count(m.id) AS stock FROM app_profiles p LEFT JOIN app_materials m ON m.profile_id=p.id
            GROUP BY p.id ORDER BY p.id""").fetchall()


@路由.put("/profiles")
def 保存档案(p: 档案参数):
    with 连接数据库() as c:
        return c.execute("""INSERT INTO app_profiles(surname,name_length,enabled) VALUES (%s,%s,%s)
            ON CONFLICT(surname,name_length) DO UPDATE SET enabled=excluded.enabled RETURNING *""",
            (p.surname, p.name_length, p.enabled)).fetchone()


@路由.get("/metrics")
def 指标():
    with 连接数据库() as c:
        totals = {}
        for name, table in {"库存": "app_materials", "用户": "app_users", "收藏": "app_favorites", "反馈": "app_feedback",
                            "历史任务": "name_runs", "历史收藏": "favorites"}.items():
            totals[name] = c.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table))).fetchone()["n"]
        return {"totals": totals, "worker": c.execute("SELECT *,heartbeat>now()-interval '5 minutes' AS alive FROM app_worker").fetchone(),
                "daily_limit": int(os.getenv("PRODUCER_DAILY_BATCHES", "480")),
                "today_batches": c.execute("SELECT COALESCE(sum(batches),0) AS n FROM app_budget WHERE day=CURRENT_DATE").fetchone()["n"],
                "sources": c.execute("""SELECT s.*,p.surname,p.name_length FROM app_source_progress s
                    JOIN app_profiles p ON p.id=s.profile_id ORDER BY p.id,s.book""").fetchall()}


@路由.get("/feedback")
def 用户反馈():
    with 连接数据库() as c:
        return c.execute("""SELECT f.material_id,f.kind,f.comment,f.created_at,m.full_name,m.book
            FROM app_feedback f JOIN app_materials m ON m.id=f.material_id ORDER BY f.created_at DESC LIMIT 100""").fetchall()


@路由.get("/model-config")
def 获取配置():
    config = 读取环境配置()
    return {"地址": config.地址, "模型": config.模型, "已配置": 模型已配置(config), "超时秒数": config.超时秒数}


@路由.put("/model-config")
def 保存配置(p: 模型配置):
    p.地址 = p.地址.rstrip("/")
    if not p.地址.endswith("/chat/completions"):
        p.地址 += "/chat/completions"
    try:
        验证模型地址(p.地址)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    old = 读取环境配置()
    if not p.密钥:
        if p.地址 != old.地址:
            raise HTTPException(422, "更换地址时必须填写密钥")
        p.密钥 = old.密钥
    if not p.密钥 or not p.模型.strip():
        raise HTTPException(422, "请填写密钥和模型名称")
    path = 配置文件()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as f:
            os.chmod(temp, 0o600)
            f.write(p.model_dump_json())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return {"saved": True}


class 复核参数(严格参数):
    status: str = Field(max_length=16)
    reviewer: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=1000)
    method: str = Field(default="", max_length=100)


@路由.get("/review/{kind}")
def 复核列表(kind: Literal["passages", "elements", "issues"], status: str = "", limit: int = Query(20, ge=1, le=100)):
    查询 = {
        "passages": ("SELECT p.*,b.name AS book FROM passages p JOIN books b ON b.id=p.book_id WHERE p.status=%s ORDER BY p.id LIMIT %s", "待核验"),
        "elements": ("SELECT * FROM character_elements WHERE status=%s ORDER BY char,method LIMIT %s", "待复核"),
        "issues": ("SELECT * FROM audit_issues WHERE status=%s ORDER BY id LIMIT %s", "待处理"),
    }
    query, default = 查询[kind]
    with 连接数据库() as c:
        return c.execute(query, (status or default, limit)).fetchall()


@路由.post("/review/{kind}/{record_id}")
def 保存复核(kind: Literal["passages", "elements", "issues"], record_id: str, p: 复核参数):
    statuses = {"passages": ("待核验", "已核验", "不采用"), "elements": ("待复核", "已核验", "不采用"), "issues": ("待处理", "已处理", "忽略")}
    if p.status not in statuses[kind]:
        raise HTTPException(422, "复核状态不正确")
    now = datetime.now(timezone.utc).isoformat()
    with 连接数据库() as c:
        if kind == "elements":
            row = c.execute("""UPDATE character_elements SET status=%s,reviewer=%s,note=%s,reviewed_at=%s
                WHERE char=%s AND method=%s RETURNING *""", (p.status, p.reviewer, p.note, now, record_id, p.method)).fetchone()
        else:
            if not record_id.isascii() or not record_id.isdigit() or len(record_id) > 18:
                raise HTTPException(422, "编号不正确")
            if kind == "passages":
                row = c.execute("""UPDATE passages SET status=%s,reviewer=%s,review_note=%s,reviewed_at=%s,can_generate=%s
                    WHERE id=%s RETURNING *""", (p.status, p.reviewer, p.note, now, int(p.status == "已核验"), int(record_id))).fetchone()
            else:
                row = c.execute("""UPDATE audit_issues SET status=%s,reviewer=%s,review_note=%s,reviewed_at=%s
                    WHERE id=%s RETURNING *""", (p.status, p.reviewer, p.note, now, int(record_id))).fetchone()
        if not row:
            raise HTTPException(404, "资料不存在")
        return row
