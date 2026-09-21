import hashlib
import json
import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from psycopg.types.json import Jsonb

from .数据库 import 连接数据库


# PostgreSQL identifiers are signed bigint; reject overflow before executing SQL.
名字编号 = Annotated[int, Field(gt=0, le=9223372036854775807)]


class 严格参数(BaseModel):
    model_config = ConfigDict(extra="forbid")


class 拉卡参数(严格参数):
    request_id: UUID
    name_length: Literal[1, 2] = 2
    gender: Literal["any", "male", "female"] = "any"
    count: int = Field(default=8, ge=1, le=8)
    # Surname affects display only; character filters apply to the given name.
    surname: str = Field(default="", max_length=4)
    required: str = Field(default="", max_length=2)
    excluded: str = Field(default="", max_length=32)
    excluded_sources: list[Annotated[str, StringConstraints(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=256)

    @field_validator("required", "excluded")
    @classmethod
    def 校验用字(cls, value):
        if not re.fullmatch(r"[\u3400-\u9fff]*", value):
            raise ValueError("筛选用字仅支持汉字")
        return "".join(sorted(set(value)))

    @field_validator("excluded_sources")
    @classmethod
    def 整理来源(cls, value):
        return sorted(set(value))

    @model_validator(mode="after")
    def 校验冲突(self):
        if set(self.required) & set(self.excluded):
            raise ValueError("必须包含和避开的字不能重复")
        return self


class 名字参数(严格参数):
    material_id: 名字编号


class 反馈参数(名字参数):
    kind: Literal["不喜欢", "出处问题", "释义问题"]
    comment: str = Field(default="", max_length=500)


class 列表参数(严格参数):
    before_id: 名字编号 | None = None


class 比较参数(严格参数):
    material_ids: list[名字编号] = Field(min_length=2, max_length=4)


def 卡片(row):
    内容 = dict(row["payload"])
    内容.setdefault("男孩适配分", 50)
    内容.setdefault("女孩适配分", 50)
    return {"id": row["id"], "item": 内容}


def 拉卡(owner, p):
    指纹条件 = p.model_dump(mode="json", exclude={"request_id", "surname"})
    # Empty defaults retain the fingerprint of requests from older builds.
    for key in ("required", "excluded", "excluded_sources"):
        if not 指纹条件[key]:
            指纹条件.pop(key)
    if p.gender == "any":
        指纹条件.pop("gender", None)
    指纹 = hashlib.sha256(json.dumps(指纹条件, sort_keys=True).encode()).hexdigest()
    with 连接数据库() as c:
        # All same-user selections serialize across API workers; no leases or process locks.
        c.execute("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (owner,))
        回执 = c.execute("SELECT * FROM app_receipts WHERE owner=%s AND request_id=%s", (owner, p.request_id)).fetchone()
        if 回执:
            if 回执["fingerprint"] != 指纹:
                raise HTTPException(409, "请求编号已用于其他条件")
            return 回执["response"]
        档案 = c.execute("SELECT id FROM app_profiles WHERE surname='' AND name_length=%s", (p.name_length,)).fetchone()
        if not 档案:
            raise HTTPException(503, "名字正在准备中，请稍后再试")
        条件 = ["m.profile_id=%s", "p.can_generate=1",
              "COALESCE((m.payload->>'基础分')::int,0)>=85",
              "NOT EXISTS (SELECT 1 FROM app_seen_names d WHERE d.owner=%s AND d.given_name=m.given_name)"]
        参数 = [档案["id"], owner]
        if p.excluded_sources:
            条件.append("NOT (m.book=ANY(%s))")
            参数.append(p.excluded_sources)
        for 字 in p.required:
            条件.append("strpos(m.given_name,%s)>0")
            参数.append(字)
        for 字 in p.excluded:
            条件.append("strpos(m.given_name,%s)=0")
            参数.append(字)
        if p.gender == "male":
            条件.append("COALESCE((m.payload->>'男孩适配分')::int,50)>=COALESCE((m.payload->>'女孩适配分')::int,50)")
        elif p.gender == "female":
            条件.append("COALESCE((m.payload->>'女孩适配分')::int,50)>=COALESCE((m.payload->>'男孩适配分')::int,50)")
        # Rank within each source, then interleave sources; do not load the whole pool in Python.
        查询 = """SELECT id,given_name,full_name,payload FROM (
            SELECT m.id,m.given_name,m.full_name,m.payload,m.book,row_number() OVER (PARTITION BY m.book ORDER BY m.id) AS rank
            FROM app_materials m JOIN passages p ON p.id=m.passage_id WHERE """ + " AND ".join(条件) + ") q ORDER BY rank,md5(book || %s) LIMIT %s"
        行 = c.execute(查询, [*参数, str(p.request_id), p.count]).fetchall()
        for 项 in 行:
            c.execute("INSERT INTO app_seen_names(owner,given_name) VALUES (%s,%s)", (owner, 项["given_name"]))
            c.execute("INSERT INTO app_deliveries(owner,full_name,material_id) VALUES (%s,%s,%s)",
                      (owner, 项["full_name"], 项["id"]))
        结果 = {"cards": [卡片(x) for x in 行], "status": "ready" if 行 else "preparing",
              "message": "" if 行 else "暂时没有符合当前条件的新名字，可以调整筛选，或稍后再来。", "retry_after": 15}
        c.execute("INSERT INTO app_receipts(owner,request_id,fingerprint,response) VALUES (%s,%s,%s,%s)",
                  (owner, p.request_id, 指纹, Jsonb(结果)))
        return 结果


def 来源列表(owner, p):
    with 连接数据库() as c:
        # Include sources without inventory, so switches remain stable as production runs.
        行 = c.execute("SELECT DISTINCT name FROM books ORDER BY name").fetchall()
        return {"sources": [{"name": x["name"], "kind": "年号" if x["name"] == "东亚年号" else "古籍"} for x in 行]}


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
      "sources.list": (严格参数, 来源列表),
      "feed.pull": (拉卡参数, 拉卡), "favorites.list": (列表参数, 收藏列表),
      "favorites.add": (名字参数, 收藏), "favorites.remove": (名字参数, 取消收藏),
      "favorites.compare": (比较参数, 比较), "feedback.save": (反馈参数, 反馈)}
