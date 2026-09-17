import hashlib
import json
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb

from .数据库 import 连接数据库


class 严格参数(BaseModel):
    model_config = ConfigDict(extra="forbid")


class 拉卡参数(严格参数):
    request_id: UUID
    surname: str = Field(pattern=r"^[\u3400-\u9fff]{1,2}$")
    name_length: Literal[1, 2] = 2
    required: str = Field(default="", pattern=r"^[\u3400-\u9fff]{0,2}$")
    excluded: str = Field(default="", pattern=r"^[\u3400-\u9fff]{0,32}$")
    count: int = Field(default=8, ge=1, le=8)


class 名字参数(严格参数):
    material_id: int = Field(gt=0)


class 反馈参数(名字参数):
    kind: Literal["不喜欢", "出处问题", "释义问题"]
    comment: str = Field(default="", max_length=500)


class 列表参数(严格参数):
    before_id: int | None = Field(default=None, gt=0)


class 比较参数(严格参数):
    material_ids: list[int] = Field(min_length=2, max_length=4)


def 卡片(row):
    return {"id": row["id"], "item": row["payload"]}


def 拉卡(owner, p):
    if len(p.required) > p.name_length or set(p.required) & set(p.excluded):
        raise HTTPException(422, "固定字与字数或避用字冲突")
    指纹 = hashlib.sha256(json.dumps(p.model_dump(mode="json", exclude={"request_id"}), sort_keys=True).encode()).hexdigest()
    with 连接数据库() as c:
        # All same-user selections serialize across API workers; no leases or process locks.
        c.execute("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (owner,))
        回执 = c.execute("SELECT * FROM app_receipts WHERE owner=%s AND request_id=%s", (owner, p.request_id)).fetchone()
        if 回执:
            if 回执["fingerprint"] != 指纹:
                raise HTTPException(409, "请求编号已用于其他条件")
            return 回执["response"]
        档案 = c.execute("""INSERT INTO app_profiles(surname,name_length) VALUES (%s,%s)
            ON CONFLICT(surname,name_length) DO UPDATE SET surname=excluded.surname RETURNING id""",
            (p.surname, p.name_length)).fetchone()["id"]
        条件 = ["m.profile_id=%s", "p.can_generate=1", "NOT EXISTS (SELECT 1 FROM app_deliveries d WHERE d.owner=%s AND d.full_name=m.full_name)"]
        参数 = [档案, owner]
        for 字 in set(p.required):
            条件.append("char_length(m.given_name)-char_length(replace(m.given_name,%s,'')) >= %s")
            参数.extend([字, p.required.count(字)])
        if p.excluded:
            条件.append("m.given_name !~ %s")
            参数.append("[" + p.excluded + "]")
        # Rank within each source, then interleave sources; do not load the whole pool in Python.
        查询 = """SELECT id,payload FROM (
            SELECT m.id,m.payload,m.book,row_number() OVER (PARTITION BY m.book ORDER BY m.id) AS rank
            FROM app_materials m JOIN passages p ON p.id=m.passage_id WHERE """ + " AND ".join(条件) + ") q ORDER BY rank,md5(book || %s) LIMIT %s"
        行 = c.execute(查询, [*参数, str(p.request_id), p.count]).fetchall()
        for 项 in 行:
            c.execute("INSERT INTO app_deliveries(owner,full_name,material_id) VALUES (%s,%s,%s)",
                      (owner, 项["payload"]["姓名"], 项["id"]))
        结果 = {"cards": [卡片(x) for x in 行], "status": "ready" if 行 else "preparing",
              "message": "" if 行 else "暂时没有符合条件的新名字，可以稍后再看或放宽条件。", "retry_after": 15}
        c.execute("INSERT INTO app_receipts(owner,request_id,fingerprint,response) VALUES (%s,%s,%s,%s)",
                  (owner, p.request_id, 指纹, Jsonb(结果)))
        return 结果


def 收藏列表(owner, p):
    with 连接数据库() as c:
        行 = c.execute("""SELECT m.id,m.payload FROM app_favorites f JOIN app_materials m ON m.id=f.material_id
            WHERE f.owner=%s AND (%s::bigint IS NULL OR m.id<%s) ORDER BY m.id DESC LIMIT 51""",
            (owner, p.before_id, p.before_id)).fetchall()
        return {"cards": [卡片(x) for x in 行[:50]], "next_cursor": 行[49]["id"] if len(行) > 50 else None}


def 收藏(owner, p):
    with 连接数据库() as c:
        if not c.execute("SELECT 1 FROM app_deliveries WHERE owner=%s AND material_id=%s", (owner, p.material_id)).fetchone():
            raise HTTPException(404, "名字不存在")
        c.execute("INSERT INTO app_favorites(owner,material_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (owner, p.material_id))
    return {"saved": True}


def 取消收藏(owner, p):
    with 连接数据库() as c:
        c.execute("DELETE FROM app_favorites WHERE owner=%s AND material_id=%s", (owner, p.material_id))
    return {"saved": False}


def 比较(owner, p):
    if len(set(p.material_ids)) != len(p.material_ids):
        raise HTTPException(422, "请选择不同的名字")
    with 连接数据库() as c:
        行 = c.execute("""SELECT m.id,m.payload FROM app_favorites f JOIN app_materials m ON m.id=f.material_id
            WHERE f.owner=%s AND m.id=ANY(%s) ORDER BY m.id""", (owner, p.material_ids)).fetchall()
        if len(行) != len(p.material_ids):
            raise HTTPException(404, "收藏不存在")
        return {"cards": [卡片(x) for x in 行]}


def 反馈(owner, p):
    with 连接数据库() as c:
        if not c.execute("SELECT 1 FROM app_deliveries WHERE owner=%s AND material_id=%s", (owner, p.material_id)).fetchone():
            raise HTTPException(404, "名字不存在")
        c.execute("""INSERT INTO app_feedback(owner,material_id,kind,comment) VALUES (%s,%s,%s,%s)
            ON CONFLICT(owner,material_id) DO UPDATE SET kind=excluded.kind,comment=excluded.comment""",
            (owner, p.material_id, p.kind, p.comment))
    return {"saved": True}


动作 = {"session.get": (严格参数, lambda owner, p: {"user_id": owner}),
      "feed.pull": (拉卡参数, 拉卡), "favorites.list": (列表参数, 收藏列表),
      "favorites.add": (名字参数, 收藏), "favorites.remove": (名字参数, 取消收藏),
      "favorites.compare": (比较参数, 比较), "feedback.save": (反馈参数, 反馈)}
