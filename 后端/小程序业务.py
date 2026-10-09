import base64
import hashlib
import json
import re
import secrets
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from psycopg.types.json import Jsonb

from .数据库 import 连接数据库
from .姓名五行 import 分析姓名, 逐字出处


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


class 自定义名字参数(严格参数):
    name: str = Field(min_length=1, max_length=2, pattern=r"^[\u3400-\u9fff]{1,2}$")


class 反馈参数(名字参数):
    kind: Literal["不喜欢", "出处问题", "释义问题"]
    comment: str = Field(default="", max_length=500)


class 列表参数(严格参数):
    before_id: 名字编号 | None = None


class 比较参数(严格参数):
    material_ids: list[名字编号] = Field(min_length=2, max_length=4)


class 姓名分析参数(严格参数):
    material_ids: list[名字编号] = Field(min_length=1, max_length=2)
    surname: str = Field(default="", max_length=4, pattern=r"^[\u3400-\u9fff]*$")


class 姓名详情参数(名字参数):
    surname: str = Field(default="", max_length=4, pattern=r"^[\u3400-\u9fff]*$")


class 分享链接参数(严格参数):
    token: str = Field(min_length=32, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    include_image: bool = True
    surname: str = Field(default="", max_length=4, pattern=r"^[\u3400-\u9fff]*$")


class 创建分享参数(名字参数):
    include_image: bool = True


def 卡片(row, include_wuxing=False):
    内容 = dict(row["payload"])
    内容.setdefault("男孩适配分", 50)
    内容.setdefault("女孩适配分", 50)
    内容.pop("五行匹配", None)
    if include_wuxing:
        内容["wuxing"] = 分析姓名(内容.get("姓名", ""))
    return {"id": row["id"], "item": 内容}


def 已投递名字(owner, ids, c=None):
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "名字编号不能重复")
    if c is None:
        with 连接数据库() as c:
            return 已投递名字(owner, ids, c)
    rows = c.execute("""SELECT DISTINCT m.id,m.given_name FROM app_materials m
        JOIN app_deliveries d ON d.material_id=m.id
        WHERE d.owner=%s AND m.id=ANY(%s)""", (owner, ids)).fetchall()
    found = {row["id"]: row["given_name"] for row in rows}
    if len(found) != len(ids):
        raise HTTPException(404, "名字不存在")
    return found


def 记录姓氏(owner, surname, c=None):
    if not surname:
        return
    if c is None:
        with 连接数据库() as c:
            return 记录姓氏(owner, surname, c)
    if c.execute("SELECT 1 FROM app_surname_queries WHERE owner=%s AND query_day=CURRENT_DATE AND surname=%s",
                 (owner, surname)).fetchone():
        return
    # Serialize only new surnames across workers; recheck after acquiring the lock.
    c.execute("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (owner,))
    if c.execute("SELECT 1 FROM app_surname_queries WHERE owner=%s AND query_day=CURRENT_DATE AND surname=%s",
                 (owner, surname)).fetchone():
        return
    used = c.execute("SELECT count(*) AS n FROM app_surname_queries WHERE owner=%s AND query_day=CURRENT_DATE",
                     (owner,)).fetchone()["n"]
    if used >= 16:
        raise HTTPException(429, "今天更换姓氏过于频繁，请明天再试")
    c.execute("INSERT INTO app_surname_queries(owner,query_day,surname) VALUES (%s,CURRENT_DATE,%s)",
              (owner, surname))


def 姓名分析(owner, p):
    with 连接数据库() as c:
        names = 已投递名字(owner, p.material_ids, c)
        记录姓氏(owner, p.surname, c)
    return {"results": [{"id": id, "wuxing": 分析姓名(p.surname + names[id])} for id in p.material_ids]}


def 姓名详情(owner, p):
    with 连接数据库() as c:
        name = p.surname + 已投递名字(owner, [p.material_id], c)[p.material_id]
        记录姓氏(owner, p.surname, c)
    return {"wuxing": 分析姓名(name), "elements": 逐字出处(name)}


def 可分享物料(c, material_id=None, token=None):
    # Match the public-feed quality gate; a withdrawn passage cannot keep circulating.
    where = "m.id=%s" if material_id is not None else "s.token=%s"
    join = "" if material_id is not None else "JOIN app_share_links s ON s.material_id=m.id"
    value = material_id if material_id is not None else token
    return c.execute(f"""SELECT m.id,m.given_name,m.full_name,m.payload FROM app_materials m
        JOIN app_profiles f ON f.id=m.profile_id
        JOIN passages p ON p.id=m.passage_id
        {join} WHERE {where} AND f.surname='' AND p.active_for_recall
        AND (p.status='待核验' OR (p.status='已核验' AND p.can_generate=1))
        AND COALESCE((m.payload->>'基础分')::int,0)>=85""", (value,)).fetchone()


def 创建分享(owner, p):
    with 连接数据库() as c:
        if not c.execute("SELECT 1 FROM app_deliveries WHERE owner=%s AND material_id=%s",
                         (owner, p.material_id)).fetchone() or not 可分享物料(c, material_id=p.material_id):
            raise HTTPException(404, "名字暂不可分享")
        row = c.execute("SELECT token FROM app_share_links WHERE owner=%s AND material_id=%s",
                        (owner, p.material_id)).fetchone()
        if not row:
            row = c.execute("""INSERT INTO app_share_links(token,owner,material_id) VALUES (%s,%s,%s)
                ON CONFLICT(owner,material_id) DO NOTHING RETURNING token""",
                (secrets.token_urlsafe(24), owner, p.material_id)).fetchone()
            if not row:
                row = c.execute("SELECT token FROM app_share_links WHERE owner=%s AND material_id=%s",
                                (owner, p.material_id)).fetchone()
    from .分享图片 import 图片地址, 渲染分享图片
    result = {"token": row["token"], "image_url": 图片地址(row["token"])}
    if not p.include_image:
        return result
    with 连接数据库() as c:
        material = 可分享物料(c, token=row["token"])
    if not material:
        raise HTTPException(404, "名字暂不可分享")
    return {**result, "image_base64": base64.b64encode(渲染分享图片(material)).decode("ascii")}


def 打开分享(owner, p):
    with 连接数据库() as c:
        row = 可分享物料(c, token=p.token)
        if row and p.surname:
            记录姓氏(owner, p.surname, c)
    if not row:
        raise HTTPException(404, "分享的名字已不可查看")
    name = p.surname + row["given_name"]
    from .分享图片 import 图片地址, 渲染分享图片
    result = {"card": 卡片(row, include_wuxing=True), "elements": 逐字出处(name), "image_url": 图片地址(p.token)}
    if p.surname:
        result['card']['item'].update({'surname': p.surname, 'displayName': name, 'wuxing': 分析姓名(name)})
    if p.include_image:
        result["image_base64"] = base64.b64encode(渲染分享图片(row)).decode("ascii")
    return result


def 收藏分享(owner, p):
    with 连接数据库() as c:
        # Serialize with feed.pull so a shared name is not delivered again mid-save.
        c.execute("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (owner,))
        row = 可分享物料(c, token=p.token)
        if not row:
            raise HTTPException(404, "分享的名字已不可收藏")
        c.execute("INSERT INTO app_seen_names(owner,given_name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                  (owner, row["given_name"]))
        c.execute("""INSERT INTO app_deliveries(owner,full_name,material_id) VALUES (%s,%s,%s)
            ON CONFLICT(owner,material_id) DO NOTHING""", (owner, row["given_name"], row["id"]))
        c.execute("""INSERT INTO app_favorites(owner,material_id) VALUES (%s,%s)
            ON CONFLICT DO NOTHING""", (owner, row["id"]))
    return {"saved": True, "material_id": row["id"]}


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
        条件 = ["m.profile_id=%s", "p.active_for_recall", "(p.status='待核验' OR (p.status='已核验' AND p.can_generate=1))",
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
            SELECT q.*,row_number() OVER (PARTITION BY given_name ORDER BY rank,md5(book || %s)) AS name_rank FROM (
            SELECT m.id,m.given_name,m.full_name,m.payload,m.book,row_number() OVER (PARTITION BY m.book ORDER BY m.id) AS rank
            FROM app_materials m JOIN passages p ON p.id=m.passage_id WHERE """ + " AND ".join(条件) + ") q) chosen WHERE name_rank=1 ORDER BY rank,md5(book || %s) LIMIT %s"
        行 = c.execute(查询, [str(p.request_id), *参数, str(p.request_id), p.count]).fetchall()
        for 项 in 行:
            c.execute("INSERT INTO app_seen_names(owner,given_name) VALUES (%s,%s)", (owner, 项["given_name"]))
            c.execute("INSERT INTO app_deliveries(owner,full_name,material_id) VALUES (%s,%s,%s)",
                      (owner, 项["full_name"], 项["id"]))
        结果 = {"cards": [卡片(x, include_wuxing=True) for x in 行], "status": "ready" if 行 else "preparing",
              "message": "" if 行 else "暂时没有符合当前条件的新名字，可以调整筛选，或稍后再来。", "retry_after": 15}
        c.execute("INSERT INTO app_receipts(owner,request_id,fingerprint,response) VALUES (%s,%s,%s,%s)",
                  (owner, p.request_id, 指纹, Jsonb(结果)))
        return 结果


def 来源列表(owner, p):
    with 连接数据库() as c:
        # Include sources without inventory, so switches remain stable as production runs.
        行 = c.execute("SELECT DISTINCT name FROM books ORDER BY name").fetchall()
        return {"sources": [{"name": x["name"], "kind": "年号" if x["name"] == "东亚年号"
                              else "榜单" if x["name"] == "历年高考状元" else "古籍"} for x in 行]}


def 收藏列表(owner, p):
    with 连接数据库() as c:
        查询 = """SELECT m.id,m.payload FROM app_favorites f JOIN app_materials m ON m.id=f.material_id
            WHERE f.owner=%s"""
        参数 = [owner]
        if p.before_id is not None:
            查询 += " AND f.material_id<%s"
            参数.append(p.before_id)
        行 = c.execute(查询 + " ORDER BY f.material_id DESC LIMIT 51", 参数).fetchall()
        return {"cards": [卡片(x) for x in 行[:50]], "next_cursor": 行[49]["id"] if len(行) > 50 else None}


def 收藏(owner, p):
    with 连接数据库() as c:
        if not c.execute("SELECT 1 FROM app_deliveries WHERE owner=%s AND material_id=%s", (owner, p.material_id)).fetchone():
            raise HTTPException(404, "名字不存在")
        c.execute("INSERT INTO app_favorites(owner,material_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (owner, p.material_id))
    return {"saved": True}


def 自定义收藏(owner, p):
    from .自定义名字 import 补全自定义名字
    from .持续生产 import 预留模型调用, 额度上限
    with 连接数据库() as c:
        row = c.execute("SELECT id,payload FROM app_materials WHERE custom_owner=%s AND given_name=%s",
                        (owner, p.name)).fetchone()
    if not row:
        with 连接数据库() as c:
            if 预留模型调用(c, 额度上限()):
                raise HTTPException(429, '名字补全服务繁忙，请稍后重试')
        try:
            payload = 补全自定义名字(p.name)
        except (RuntimeError, ValueError):
            raise HTTPException(503, '名字信息补全失败，请稍后重试') from None
    with 连接数据库() as c:
        # Serialize favorite creation with this user's feed and retry requests.
        c.execute("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (owner,))
        if not row:
            row = c.execute("""INSERT INTO app_materials(given_name,full_name,book,payload,custom_owner)
                VALUES (%s,%s,'用户自定义',%s,%s)
                ON CONFLICT(custom_owner,given_name) WHERE custom_owner IS NOT NULL
                DO UPDATE SET given_name=excluded.given_name RETURNING id,payload""",
                (p.name, p.name, Jsonb(payload), owner)).fetchone()
        c.execute("INSERT INTO app_seen_names(owner,given_name) VALUES (%s,%s) ON CONFLICT DO NOTHING", (owner, p.name))
        c.execute("""INSERT INTO app_deliveries(owner,full_name,material_id) VALUES (%s,%s,%s)
            ON CONFLICT(owner,material_id) DO NOTHING""", (owner, p.name, row['id']))
        c.execute("INSERT INTO app_favorites(owner,material_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (owner, row['id']))
    return {'saved': True, 'card': 卡片(row, include_wuxing=True)}


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
      "names.analyze": (姓名分析参数, 姓名分析), "names.detail": (姓名详情参数, 姓名详情),
      "shares.create": (创建分享参数, 创建分享), "shares.get": (分享链接参数, 打开分享),
      "shares.save": (分享链接参数, 收藏分享),
      "favorites.add": (名字参数, 收藏), "favorites.remove": (名字参数, 取消收藏),
      "favorites.custom": (自定义名字参数, 自定义收藏),
      "favorites.compare": (比较参数, 比较), "feedback.save": (反馈参数, 反馈)}
