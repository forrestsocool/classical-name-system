from __future__ import annotations

import json
import hmac
import os
import re
import sqlite3
import time
import uuid
import hashlib
from contextvars import ContextVar
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, BoundedSemaphore
from typing import Literal
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .八字计算 import 计算八字
from .缓存 import TTL缓存
from .候选生成 import 生成基础候选
from .名字校验 import 取字位置
from .模型接口 import (
    语料证据,
    调用兼容模型,
    模型已配置,
    读取环境配置,
)


根目录 = Path(__file__).resolve().parents[1]
数据库路径 = Path(os.getenv("起名数据库路径", str(根目录 / "构建产物" / "起名系统.sqlite3")))
当前会话 = ContextVar("当前会话", default=None)
模型并发 = BoundedSemaphore(2)

应用 = FastAPI(title="古籍智能起名服务", version="0.1.0")
前端目录 = 根目录 / "前端"
限流记录: dict[str, deque[float]] = defaultdict(deque)
限流锁 = Lock()
查询缓存 = TTL缓存(有效秒数=60, 最大数量=256)
请求指标锁 = Lock()
请求指标数据 = {
    "请求总数": 0,
    "错误请求数": 0,
    "耗时毫秒总数": 0.0,
    "路径": {},
}


def 记录请求指标(方法: str, 路径: str, 状态码: int, 耗时毫秒: float) -> None:
    """记录不含查询参数和请求正文的进程内监控指标。"""
    路径键 = f"{方法} {路径}"
    with 请求指标锁:
        请求指标数据["请求总数"] += 1
        请求指标数据["耗时毫秒总数"] += max(0.0, 耗时毫秒)
        if 状态码 >= 400:
            请求指标数据["错误请求数"] += 1
        路径指标 = 请求指标数据["路径"].setdefault(
            路径键,
            {"请求数": 0, "错误数": 0, "耗时毫秒总数": 0.0},
        )
        路径指标["请求数"] += 1
        路径指标["耗时毫秒总数"] += max(0.0, 耗时毫秒)
        if 状态码 >= 400:
            路径指标["错误数"] += 1


def 规范监控路径(路径: str) -> str:
    """将资源编号归一化，避免监控标签因用户数据产生高基数。"""
    规则 = (
        (r"^/api/name-runs/[^/]+/model-candidates$", "/api/name-runs/{id}/model-candidates"),
        (r"^/api/name-runs/[^/]+$", "/api/name-runs/{id}"),
        (r"^/api/admin/passages/[^/]+/review$", "/api/admin/passages/{id}/review"),
        (r"^/api/admin/characters/[^/]+/element-review$", "/api/admin/characters/{char}/element-review"),
        (r"^/api/admin/audit-issues/[^/]+/review$", "/api/admin/audit-issues/{id}/review"),
        (r"^/api/eras/[^/]+$", "/api/eras/{id}"),
        (r"^/api/passages/[^/]+$", "/api/passages/{id}"),
        (r"^/api/characters/[^/]+$", "/api/characters/{char}"),
        (r"^/api/favorites/[^/]+$", "/api/favorites/{id}"),
    )
    for 模式, 替换 in 规则:
        if re.fullmatch(模式, 路径):
            return 替换
    固定路径 = {"/", "/metrics", "/api/health", "/api/ready", "/api/search", "/api/directions", "/api/eras", "/api/bazi", "/api/model/status", "/api/name-runs", "/api/favorites", "/api/favorites/compare", "/api/feedback", "/api/admin/review-queue", "/api/admin/element-queue", "/api/admin/audit-queue", "/api/admin/metrics"}
    return 路径 if 路径 in 固定路径 else "/其他"


def 获取请求指标() -> dict:
    with 请求指标锁:
        路径 = {
            键: dict(值) for 键, 值 in 请求指标数据["路径"].items()
        }
        return {
            "请求总数": 请求指标数据["请求总数"],
            "错误请求数": 请求指标数据["错误请求数"],
            "耗时毫秒总数": 请求指标数据["耗时毫秒总数"],
            "路径": 路径,
        }


def _转义Prometheus标签(值: str) -> str:
    return 值.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def 生成Prometheus指标() -> str:
    指标 = 获取请求指标()
    总数 = 指标["请求总数"]
    错误数 = 指标["错误请求数"]
    总耗时 = 指标["耗时毫秒总数"]
    行 = [
        "# HELP name_service_requests_total HTTP请求总数",
        "# TYPE name_service_requests_total counter",
        f"name_service_requests_total {总数}",
        "# HELP name_service_request_errors_total HTTP错误请求总数",
        "# TYPE name_service_request_errors_total counter",
        f"name_service_request_errors_total {错误数}",
        "# HELP name_service_request_duration_ms_sum HTTP请求耗时毫秒总和",
        "# TYPE name_service_request_duration_ms_sum counter",
        f"name_service_request_duration_ms_sum {总耗时:.3f}",
        "# HELP name_service_request_duration_ms_count HTTP请求耗时样本数",
        "# TYPE name_service_request_duration_ms_count counter",
        f"name_service_request_duration_ms_count {总数}",
        "# HELP name_service_request_path_total 按方法和路径统计的HTTP请求数",
        "# TYPE name_service_request_path_total counter",
    ]
    for 路径键, 路径指标 in sorted(指标["路径"].items()):
        方法, 路径 = 路径键.split(" ", 1)
        标签 = (
            f'method="{_转义Prometheus标签(方法)}",'
            f'path="{_转义Prometheus标签(路径)}"'
        )
        行.append(
            f"name_service_request_path_total{{{标签}}} "
            f"{路径指标['请求数']}"
        )
    return "\n".join(行) + "\n"


def 每分钟请求上限() -> int:
    try:
        return max(1, min(int(os.getenv("起名每分钟上限", "60")), 10000))
    except ValueError:
        return 60


def 请求是否超限(来源: str, 当前时间: float) -> bool:
    截止时间 = 当前时间 - 60
    上限 = 每分钟请求上限()
    with 限流锁:
        if len(限流记录) >= 4096:
            for 键 in list(限流记录):
                if not 限流记录[键] or 限流记录[键][-1] <= 截止时间:
                    del 限流记录[键]
            if 来源 not in 限流记录 and len(限流记录) >= 4096:
                return True
        时间队列 = 限流记录[来源]
        while 时间队列 and 时间队列[0] <= 截止时间:
            时间队列.popleft()
        if len(时间队列) >= 上限:
            return True
        时间队列.append(当前时间)
        return False


@应用.middleware("http")
async def 请求保护(请求, 调用下一个):
    开始时间 = time.perf_counter()
    状态码 = 500
    会话令牌 = None
    try:
        路径 = 请求.url.path
        if any(路径.startswith(前缀) for 前缀 in ("/api/name-runs", "/api/favorites", "/api/feedback")):
            密钥 = 请求.headers.get("X-Session-Key", "")
            if not re.fullmatch(r"web-[a-f0-9]{32}", 密钥):
                状态码 = 401
                return JSONResponse({"detail": "请使用有效的浏览器会话"}, status_code=401)
            会话令牌 = 当前会话.set(密钥)
            匹配 = re.match(r"^/api/name-runs/([^/]+)", 路径)
            if 匹配:
                with 连接数据库() as 连接:
                    所有者 = 连接.execute("SELECT owner FROM run_owners WHERE run_id = ?", (匹配.group(1),)).fetchone()
                if 所有者 is None or 所有者[0] != hashlib.sha256(密钥.encode()).hexdigest():
                    状态码 = 404
                    return JSONResponse({"detail": "起名任务不存在"}, status_code=404)
        if 请求.url.path.startswith("/api/"):
            来源 = 请求.client.host if 请求.client else "未知来源"
            if 请求是否超限(来源, time.monotonic()):
                响应 = JSONResponse(
                    {"detail": "请求过于频繁，请稍后再试"},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
            else:
                响应 = await 调用下一个(请求)
        else:
            响应 = await 调用下一个(请求)
        状态码 = 响应.status_code
        if 当前会话.get():
            响应.headers["Cache-Control"] = "no-store"
        响应.headers["X-Content-Type-Options"] = "nosniff"
        响应.headers["X-Frame-Options"] = "DENY"
        响应.headers["Referrer-Policy"] = "no-referrer"
        响应.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'"
        )
        return 响应
    finally:
        if 会话令牌 is not None:
            当前会话.reset(会话令牌)
        记录请求指标(
            请求.method,
            规范监控路径(请求.url.path),
            状态码,
            (time.perf_counter() - 开始时间) * 1000,
        )


class 起名请求(BaseModel):
    姓氏: str = Field(min_length=1, max_length=4)
    名字长度: int = Field(default=2, ge=1, le=2)
    方向: list[Literal["温润君子", "胸怀天下", "智慧通达", "坚毅担当", "自由洒脱", "文采气质", "安宁福泽"]] = Field(default_factory=list, max_length=3)
    必须包含: str = Field(default="", max_length=2)
    避用字: str = Field(default="", max_length=50)
    关键词: str = Field(default="", max_length=20)
    随机种子: int | None = Field(default=None, ge=0, le=2**63 - 1)
    五行偏好: list[str] = Field(default_factory=list, max_length=5)
    出生时间: datetime | None = None
    时区: str = "Asia/Shanghai"
    日界规则: Literal["子初", "午夜"] = "子初"
    排除名字: list[str] = Field(default_factory=list, max_length=100)


class 八字请求(BaseModel):
    出生时间: datetime
    时区: str = "Asia/Shanghai"
    日界规则: Literal["子初", "午夜"] = "子初"


class 收藏请求(BaseModel):
    collection_id: str = Field(min_length=1, max_length=80)
    run_id: str = Field(min_length=1, max_length=80)
    full_name: str = Field(min_length=2, max_length=8)
    note: str = Field(default="", max_length=200)


class 比较请求(BaseModel):
    collection_id: str = Field(min_length=1, max_length=80)
    favorite_ids: list[int] = Field(min_length=1, max_length=5)


class 反馈请求(BaseModel):
    collection_id: str = Field(min_length=1, max_length=80)
    run_id: str = Field(min_length=1, max_length=80)
    full_name: str = Field(min_length=2, max_length=8)
    feedback_type: Literal["喜欢", "不喜欢", "出处有误", "读音不佳", "含义不符"]
    score: int | None = Field(default=None, ge=1, le=5)
    comment: str = Field(default="", max_length=500)


class 片段复核请求(BaseModel):
    状态: Literal["待核验", "已核验", "不采用"]
    复核人: str = Field(min_length=1, max_length=80)
    备注: str = Field(default="", max_length=500)


class 汉字五行复核请求(BaseModel):
    方法: str = Field(min_length=1, max_length=80)
    状态: Literal["待复核", "已核验", "不采用"]
    复核人: str = Field(min_length=1, max_length=80)
    备注: str = Field(default="", max_length=500)


class 审计问题复核请求(BaseModel):
    状态: Literal["待处理", "已处理", "忽略"]
    复核人: str = Field(min_length=1, max_length=80)
    备注: str = Field(default="", max_length=500)


@应用.get("/", include_in_schema=False)
def 首页() -> FileResponse:
    return FileResponse(前端目录 / "index.html")


class 自动关闭连接(sqlite3.Connection):
    def __exit__(self, *参数):
        try:
            return super().__exit__(*参数)
        finally:
            self.close()


def 连接数据库() -> sqlite3.Connection:
    连接 = sqlite3.connect(数据库路径, timeout=5.0, factory=自动关闭连接)
    连接.row_factory = sqlite3.Row
    连接.execute("PRAGMA foreign_keys = ON")
    连接.execute("PRAGMA busy_timeout = 5000")
    连接.execute("CREATE TABLE IF NOT EXISTS run_owners (run_id TEXT PRIMARY KEY, owner TEXT NOT NULL)")
    return 连接


def 准备持久化请求(请求字典: dict) -> dict:
    """任务历史只保存起名条件，不保存完整出生时间。"""
    保存内容 = dict(请求字典)
    if 保存内容.pop("出生时间", None) is not None:
        保存内容["出生时间已处理"] = True
    return 保存内容


def 准备持久化八字(八字结果: dict | None) -> dict | None:
    """保留可复核的计算结果，去除可反推出生时刻的字段。"""
    if 八字结果 is None:
        return None
    保存内容 = dict(八字结果)
    保存内容.pop("输入时间", None)
    保存内容.pop("计算本地时间", None)
    保存内容.pop("农历日期", None)
    保存内容["出生时间已隐去"] = True
    return 保存内容


def 记录模型指标(
    任务编号: str,
    配置,
    开始时间: float,
    状态: str,
    错误: str = "",
) -> None:
    服务商 = re.sub(r"^https?://", "", 配置.地址).split("/", 1)[0]
    with 连接数据库() as 连接:
        连接.execute(
            """
            INSERT INTO model_metrics(
                run_id, provider, model, latency_ms, status, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                任务编号,
                服务商,
                配置.模型,
                max(0, round((time.perf_counter() - 开始时间) * 1000)),
                状态,
                错误[:500],
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def 校验管理权限(管理密钥: str | None) -> None:
    配置密钥 = os.getenv("起名管理密钥", "")
    if not 配置密钥:
        raise HTTPException(status_code=503, detail="管理接口尚未配置密钥")
    if not 配置密钥.isascii():
        raise HTTPException(status_code=503, detail="管理密钥必须使用ASCII字符")
    if 管理密钥 is not None and not 管理密钥.isascii():
        raise HTTPException(status_code=403, detail="管理密钥格式不正确")
    if not 管理密钥 or not hmac.compare_digest(
        管理密钥.encode("utf-8"), 配置密钥.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="管理密钥不正确")


@应用.get("/api/health")
def 健康检查() -> dict:
    if not 数据库路径.exists():
        return {"状态": "等待建库"}
    with 连接数据库() as 连接:
        return {
            "状态": "正常",
            "古籍数": 连接.execute("SELECT COUNT(*) FROM books").fetchone()[0],
            "片段数": 连接.execute("SELECT COUNT(*) FROM passages").fetchone()[0],
            "可生成片段数": 连接.execute(
                "SELECT COUNT(*) FROM passages WHERE can_generate = 1"
            ).fetchone()[0],
        }


@应用.get("/api/ready")
def 就绪检查() -> dict:
    if not 数据库路径.exists():
        raise HTTPException(status_code=503, detail="数据库尚未建立")
    try:
        with 连接数据库() as 连接:
            连接.execute("SELECT 1 FROM schema_version LIMIT 1").fetchone()
            完整性 = "ok"
            可生成数 = 连接.execute(
                "SELECT COUNT(*) FROM passages WHERE can_generate = 1"
            ).fetchone()[0]
    except sqlite3.Error as 异常:
        raise HTTPException(status_code=503, detail="数据库不可用") from 异常
    if 完整性 != "ok":
        raise HTTPException(status_code=503, detail="数据库完整性检查未通过")
    return {"状态": "就绪", "数据库完整性": 完整性, "可生成片段数": 可生成数}


@应用.get("/metrics", include_in_schema=False)
def 监控指标() -> PlainTextResponse:
    return PlainTextResponse(
        生成Prometheus指标(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@应用.post("/api/bazi")
def 计算八字接口(请求: 八字请求) -> dict:
    try:
        return 计算八字(请求.出生时间, 请求.时区, 请求.日界规则)
    except ValueError as 异常:
        raise HTTPException(status_code=422, detail=str(异常)) from 异常


@应用.get("/api/model/status")
def 模型状态() -> dict:
    配置 = 读取环境配置()
    return {
        "已配置": 模型已配置(配置),
        "模型": 配置.模型,
    }


@应用.get("/api/search")
def 搜索古籍(
    关键词: Annotated[str, Query(min_length=1, max_length=40)],
    书名: str | None = None,
    数量: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict:
    缓存键 = ("搜索", 关键词, 书名, 数量)
    缓存结果 = 查询缓存.读取(缓存键)
    if 缓存结果 is not None:
        return 缓存结果
    条件 = ["p.text LIKE ?"]
    参数: list[object] = [f"%{关键词}%"]
    if 书名:
        条件.append("b.name = ?")
        参数.append(书名)
    查询 = f"""
        SELECT p.id, b.name AS book, p.section_title, p.text,
               p.source_line_start, p.source_line_end, p.status,
               p.can_generate
        FROM passages p
        JOIN books b ON b.id = p.book_id
        WHERE {' AND '.join(条件)}
        ORDER BY b.name, p.ordinal
        LIMIT ?
    """
    参数.append(数量)
    with 连接数据库() as 连接:
        结果 = [dict(行) for 行 in 连接.execute(查询, 参数).fetchall()]
    返回结果 = {"关键词": 关键词, "数量": len(结果), "结果": 结果}
    查询缓存.写入(缓存键, 返回结果)
    return 返回结果


@应用.get("/api/directions")
def 获取方向() -> dict:
    缓存键 = ("方向",)
    缓存结果 = 查询缓存.读取(缓存键)
    if 缓存结果 is not None:
        return 缓存结果
    with 连接数据库() as 连接:
        结果 = []
        for 行 in 连接.execute(
            "SELECT id, name FROM directions ORDER BY id"
        ).fetchall():
            关键词 = [
                项目[0]
                for 项目 in 连接.execute(
                    """
                    SELECT keyword FROM direction_keywords
                    WHERE direction_id = ? ORDER BY rowid
                    """,
                    (行["id"],),
                ).fetchall()
            ]
            结果.append({"名称": 行["name"], "关键词": 关键词})
    返回结果 = {"方向": 结果}
    查询缓存.写入(缓存键, 返回结果)
    return 返回结果


@应用.get("/api/eras")
def 搜索年号(
    关键词: str | None = Query(default=None, max_length=40),
    地区: str | None = Query(default=None, max_length=40),
    状态: str | None = Query(default=None, max_length=20),
    数量: Annotated[int, Query(ge=1, le=100)] = 30,
) -> dict:
    缓存键 = ("年号", 关键词, 地区, 状态, 数量)
    缓存结果 = 查询缓存.读取(缓存键)
    if 缓存结果 is not None:
        return 缓存结果
    条件 = []
    参数: list[object] = []
    if 关键词:
        条件.append("(era_name LIKE ? OR category LIKE ? OR period LIKE ?)")
        参数.extend([f"%{关键词}%"] * 3)
    if 地区:
        条件.append("region = ?")
        参数.append(地区)
    if 状态:
        条件.append("status = ?")
        参数.append(状态)
    查询 = """
        SELECT id, region, category, era_name, period, duration, status,
               source_line, record_type, person, note
        FROM eras
    """
    if 条件:
        查询 += " WHERE " + " AND ".join(条件)
    查询 += " ORDER BY region, period, id LIMIT ?"
    参数.append(数量)
    with 连接数据库() as 连接:
        结果 = [dict(行) for 行 in 连接.execute(查询, 参数).fetchall()]
    返回结果 = {"关键词": 关键词, "地区": 地区, "数量": len(结果), "结果": 结果}
    查询缓存.写入(缓存键, 返回结果)
    return 返回结果


@应用.get("/api/eras/{era_id}")
def 获取年号(era_id: int) -> dict:
    缓存键 = ("年号详情", era_id)
    缓存结果 = 查询缓存.读取(缓存键)
    if 缓存结果 is not None:
        return 缓存结果
    with 连接数据库() as 连接:
        行 = 连接.execute(
            """
            SELECT id, region, category, era_name, period, duration, status,
                   source_line, record_type, person, note
            FROM eras WHERE id = ?
            """,
            (era_id,),
        ).fetchone()
    if 行 is None:
        raise HTTPException(status_code=404, detail="年号不存在")
    返回结果 = dict(行)
    查询缓存.写入(缓存键, 返回结果)
    return 返回结果


@应用.get("/api/passages/{passage_id}")
def 获取片段(passage_id: int) -> dict:
    缓存键 = ("片段", passage_id)
    缓存结果 = 查询缓存.读取(缓存键)
    if 缓存结果 is not None:
        return 缓存结果
    with 连接数据库() as 连接:
        行 = 连接.execute(
            """
            SELECT p.id, b.name AS book, p.section_title, p.text,
                   p.source_line_start, p.source_line_end, p.status,
                   p.can_generate, s.path AS source_path, s.sha256
            FROM passages p
            JOIN books b ON b.id = p.book_id
            JOIN sources s ON s.id = p.source_id
            WHERE p.id = ?
            """,
            (passage_id,),
        ).fetchone()
    if 行 is None:
        raise HTTPException(status_code=404, detail="片段不存在")
    返回结果 = dict(行)
    查询缓存.写入(缓存键, 返回结果)
    return 返回结果


@应用.get("/api/characters/{char}")
def 获取汉字(char: str) -> dict:
    if len(char) != 1:
        raise HTTPException(status_code=422, detail="一次只能查询一个汉字")
    缓存键 = ("汉字", char)
    缓存结果 = 查询缓存.读取(缓存键)
    if 缓存结果 is not None:
        return 缓存结果
    with 连接数据库() as 连接:
        字符 = 连接.execute(
            "SELECT char, pinyin, pinyin_tone, source, status FROM characters WHERE char = ?",
            (char,),
        ).fetchone()
        if 字符 is None:
            raise HTTPException(status_code=404, detail="汉字不存在")
        规则 = [
            dict(行)
            for 行 in 连接.execute(
                """
                SELECT element, method, confidence, status, note
                FROM character_elements WHERE char = ? ORDER BY method
                """,
                (char,),
            ).fetchall()
        ]
    结果 = dict(字符)
    结果["五行规则"] = 规则
    查询缓存.写入(缓存键, 结果)
    return 结果


@应用.post("/api/name-runs")
def 创建起名任务(请求: 起名请求) -> dict:
    """第一版接口只使用已审核语料，未审核资料不会直接进入候选池。"""
    任务编号 = str(uuid.uuid4())
    随机种子 = 请求.随机种子
    if 随机种子 is None:
        随机种子 = uuid.uuid4().int % (2**31)
    请求字典 = 请求.model_dump(mode="json")
    if not re.fullmatch(r"[\u3400-\u4dbf\u4e00-\u9fff]{1,4}", 请求.姓氏):
        raise HTTPException(status_code=422, detail="姓氏必须为一至四个汉字")
    if len(请求.必须包含) > 请求.名字长度:
        raise HTTPException(status_code=422, detail="固定字数量超过名字长度")
    if set(请求.必须包含) & set(请求.避用字):
        raise HTTPException(status_code=422, detail="固定字与避用字冲突")
    请求字典["随机种子"] = 随机种子
    不支持五行 = set(请求字典["五行偏好"]) - {"金", "木", "水", "火", "土"}
    if 不支持五行:
        raise HTTPException(status_code=422, detail="五行偏好只能包含金、木、水、火、土")
    八字结果 = None
    if 请求.出生时间 is not None:
        try:
            八字结果 = 计算八字(请求.出生时间, 请求.时区, 请求.日界规则)
        except ValueError as 异常:
            raise HTTPException(status_code=422, detail=str(异常)) from 异常
    保存请求 = 准备持久化请求(请求字典)
    保存八字 = 准备持久化八字(八字结果)
    with 连接数据库() as 连接:
        连接.execute(
            """
            INSERT INTO name_runs(
                id, request_json, bazi_json, random_seed, rule_version, status, created_at
            ) VALUES (?, ?, ?, ?, '基础规则0.1', '处理中', ?)
            """,
            (
                任务编号,
                json.dumps(保存请求, ensure_ascii=False),
                json.dumps(保存八字, ensure_ascii=False) if 保存八字 else None,
                随机种子,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        if 当前会话.get():
            连接.execute("INSERT INTO run_owners VALUES (?, ?)", (任务编号, hashlib.sha256(当前会话.get().encode()).hexdigest()))
        可生成数 = 连接.execute(
            "SELECT COUNT(*) FROM passages WHERE can_generate = 1"
        ).fetchone()[0]
    if 可生成数 == 0:
        with 连接数据库() as 连接:
            连接.execute(
                "UPDATE name_runs SET status = '等待资料复核' WHERE id = ?",
                (任务编号,),
            )
        return {
            "状态": "等待资料复核",
            "任务编号": 任务编号,
            "候选": [],
            "原因": "当前古籍片段尚未完成人工核验，系统不会用未核验文本生成名字。",
            "请求": 请求字典,
            "八字": 八字结果,
        }
    with 连接数据库() as 连接:
        候选 = 生成基础候选(
            连接,
            请求字典["姓氏"],
            请求字典["名字长度"],
            请求字典["方向"],
            请求字典["必须包含"],
            请求字典["避用字"],
            请求字典["关键词"],
            随机种子,
            请求字典["五行偏好"],
            排除名字=请求字典["排除名字"],
        )
        连接.executemany(
            """
            INSERT INTO candidates(
                run_id, full_name, given_name, book, section_title,
                source_passage_id, source_text, source_offset, direction,
                wuxing_json, pinyin, pinyin_tone, origin_type, base_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    任务编号,
                    项目["姓名"],
                    项目["名字"],
                    项目["书名"],
                    项目["篇章"],
                    项目["来源片段编号"],
                    项目["原文"],
                    项目["原文位置"],
                    项目["方向"],
                    json.dumps(项目["五行匹配"], ensure_ascii=False),
                    项目["拼音"],
                    项目["拼音带调"],
                    项目["取字方式"],
                    项目["基础分"],
                )
                for 项目 in 候选
            ],
        )
        连接.execute(
            "UPDATE name_runs SET status = ? WHERE id = ?",
            ("完成" if 候选 else "没有符合条件的候选", 任务编号),
        )
    return {
        "状态": "完成" if 候选 else "没有符合条件的候选",
        "任务编号": 任务编号,
        "候选": 候选,
        "请求": 请求字典,
        "八字": 八字结果,
    }


@应用.get("/api/name-runs/{run_id}")
def 获取起名任务(run_id: str) -> dict:
    run_id = run_id.strip()
    with 连接数据库() as 连接:
        任务 = 连接.execute(
            "SELECT * FROM name_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if 任务 is None:
            raise HTTPException(status_code=404, detail="起名任务不存在")
        候选 = [
            dict(项目)
            for 项目 in 连接.execute(
                """
                SELECT full_name, given_name, book, section_title,
                       source_passage_id, source_text, source_offset,
                       direction, wuxing_json, pinyin, pinyin_tone,
                       origin_type, base_score
                FROM candidates WHERE run_id = ? ORDER BY base_score DESC, id
                """,
                (run_id,),
            ).fetchall()
        ]
        for 项目 in 候选:
            五行文本 = 项目.pop("wuxing_json")
            项目["五行匹配"] = json.loads(五行文本) if 五行文本 else None
    结果 = dict(任务)
    结果["请求"] = json.loads(结果.pop("request_json"))
    八字文本 = 结果.pop("bazi_json")
    结果["八字"] = json.loads(八字文本) if 八字文本 else None
    结果["候选"] = 候选
    return 结果


@应用.get("/api/name-runs")
def 获取任务列表(
    数量: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    with 连接数据库() as 连接:
        任务列表 = []
        for 行 in 连接.execute(
            """
            SELECT id, request_json, random_seed, rule_version, status, created_at
            FROM name_runs
            WHERE (? IS NULL OR id IN (SELECT run_id FROM run_owners WHERE owner = ?))
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (当前会话.get(), hashlib.sha256((当前会话.get() or "").encode()).hexdigest(), 数量),
        ).fetchall():
            项目 = dict(行)
            项目["请求"] = json.loads(项目.pop("request_json"))
            任务列表.append(项目)
    return {"数量": len(任务列表), "任务": 任务列表}


@应用.delete("/api/name-runs/{run_id}")
def 删除起名任务(run_id: str) -> dict:
    run_id = run_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", run_id):
        raise HTTPException(status_code=422, detail="任务编号格式不正确")
    with 连接数据库() as 连接:
        存在 = 连接.execute(
            "SELECT 1 FROM name_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if 存在 is None:
            raise HTTPException(status_code=404, detail="起名任务不存在")
        删除数量 = {}
        for 表名 in (
            "feedback",
            "favorites",
            "model_metrics",
            "model_candidates",
            "candidates",
        ):
            游标 = 连接.execute(
                f"DELETE FROM {表名} WHERE run_id = ?", (run_id,)
            )
            删除数量[表名] = 游标.rowcount
        连接.execute("DELETE FROM name_runs WHERE id = ?", (run_id,))
        连接.execute("DELETE FROM run_owners WHERE run_id = ?", (run_id,))
    return {"状态": "已删除", "任务编号": run_id, "删除数量": 删除数量}


def 校验收藏夹编号(编号: str) -> None:
    if 当前会话.get() is not None and 编号 != hashlib.sha256(当前会话.get().encode()).hexdigest():
        raise HTTPException(status_code=403, detail="无权访问这个收藏夹")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", 编号):
        raise HTTPException(status_code=422, detail="收藏夹编号格式不正确")


def 校验任务归属(连接, 编号: str) -> None:
    if 当前会话.get() is not None:
        行 = 连接.execute("SELECT owner FROM run_owners WHERE run_id = ?", (编号,)).fetchone()
        if 行 is None or 行[0] != hashlib.sha256(当前会话.get().encode()).hexdigest():
            raise HTTPException(status_code=404, detail="起名任务不存在")


@应用.post("/api/favorites")
def 收藏候选(请求: 收藏请求) -> dict:
    校验收藏夹编号(请求.collection_id)
    with 连接数据库() as 连接:
        校验任务归属(连接, 请求.run_id)
        候选 = 连接.execute(
            """
            SELECT full_name, given_name, pinyin, pinyin_tone, book,
                   section_title, source_passage_id, source_text,
                   source_offset, direction, wuxing_json, origin_type, base_score
            FROM candidates WHERE run_id = ? AND full_name = ?
            """,
            (请求.run_id, 请求.full_name),
        ).fetchone()
        if 候选 is None:
            raise HTTPException(status_code=404, detail="任务中不存在这个名字")
        连接.execute(
            """
            INSERT INTO favorites(
                collection_id, run_id, full_name, given_name, pinyin, pinyin_tone,
                book, section_title, source_passage_id, source_text, source_offset,
                direction, wuxing_json, origin_type, base_score, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(collection_id, full_name) DO UPDATE SET
                run_id = excluded.run_id,
                given_name = excluded.given_name,
                pinyin = excluded.pinyin,
                pinyin_tone = excluded.pinyin_tone,
                book = excluded.book,
                section_title = excluded.section_title,
                source_passage_id = excluded.source_passage_id,
                source_text = excluded.source_text,
                source_offset = excluded.source_offset,
                direction = excluded.direction,
                wuxing_json = excluded.wuxing_json,
                origin_type = excluded.origin_type,
                base_score = excluded.base_score,
                note = excluded.note
            """,
            (
                请求.collection_id,
                请求.run_id,
                候选["full_name"],
                候选["given_name"],
                候选["pinyin"],
                候选["pinyin_tone"],
                候选["book"],
                候选["section_title"],
                候选["source_passage_id"],
                候选["source_text"],
                候选["source_offset"],
                候选["direction"],
                候选["wuxing_json"],
                候选["origin_type"],
                候选["base_score"],
                请求.note,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        结果 = 连接.execute(
            "SELECT * FROM favorites WHERE collection_id = ? AND full_name = ?",
            (请求.collection_id, 请求.full_name),
        ).fetchone()
    return dict(结果)


@应用.get("/api/favorites")
def 获取收藏(collection_id: str) -> dict:
    校验收藏夹编号(collection_id)
    with 连接数据库() as 连接:
        结果 = [
            dict(行)
            for 行 in 连接.execute(
                """
                SELECT * FROM favorites
                WHERE collection_id = ? ORDER BY created_at DESC, id DESC
                """,
                (collection_id,),
            ).fetchall()
        ]
    for 项目 in 结果:
        文本 = 项目.get("wuxing_json")
        项目["五行匹配"] = json.loads(文本) if 文本 else None
        项目.pop("wuxing_json", None)
    return {"收藏夹": collection_id, "数量": len(结果), "结果": 结果}


@应用.delete("/api/favorites/{favorite_id}")
def 删除收藏(favorite_id: int, collection_id: str) -> dict:
    校验收藏夹编号(collection_id)
    with 连接数据库() as 连接:
        游标 = 连接.execute(
            "DELETE FROM favorites WHERE id = ? AND collection_id = ?",
            (favorite_id, collection_id),
        )
    if 游标.rowcount == 0:
        raise HTTPException(status_code=404, detail="收藏不存在")
    return {"状态": "已删除", "收藏编号": favorite_id}


@应用.post("/api/favorites/compare")
def 比较收藏(请求: 比较请求) -> dict:
    校验收藏夹编号(请求.collection_id)
    占位符 = ",".join("?" for _ in 请求.favorite_ids)
    参数 = [请求.collection_id, *请求.favorite_ids]
    with 连接数据库() as 连接:
        结果 = [
            dict(行)
            for 行 in 连接.execute(
                f"""
                SELECT * FROM favorites
                WHERE collection_id = ? AND id IN ({占位符})
                ORDER BY id
                """,
                参数,
            ).fetchall()
        ]
    if len(结果) != len(set(请求.favorite_ids)):
        raise HTTPException(status_code=404, detail="部分收藏不存在或不属于该收藏夹")
    for 项目 in 结果:
        文本 = 项目.get("wuxing_json")
        项目["五行匹配"] = json.loads(文本) if 文本 else None
        项目.pop("wuxing_json", None)
    return {"收藏夹": 请求.collection_id, "结果": 结果}


@应用.post("/api/feedback")
def 提交反馈(请求: 反馈请求) -> dict:
    校验收藏夹编号(请求.collection_id)
    with 连接数据库() as 连接:
        校验任务归属(连接, 请求.run_id)
        候选 = 连接.execute(
            "SELECT 1 FROM candidates WHERE run_id = ? AND full_name = ?",
            (请求.run_id, 请求.full_name),
        ).fetchone()
        if 候选 is None:
            raise HTTPException(status_code=404, detail="任务中不存在这个名字")
        连接.execute(
            """
            INSERT INTO feedback(
                collection_id, run_id, full_name, feedback_type,
                score, comment, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(collection_id, run_id, full_name) DO UPDATE SET
                feedback_type = excluded.feedback_type,
                score = excluded.score,
                comment = excluded.comment,
                created_at = excluded.created_at
            """,
            (
                请求.collection_id,
                请求.run_id,
                请求.full_name,
                请求.feedback_type,
                请求.score,
                请求.comment,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        结果 = 连接.execute(
            """
            SELECT id, collection_id, run_id, full_name, feedback_type, score, comment
            FROM feedback WHERE collection_id = ? AND run_id = ? AND full_name = ?
            """,
            (请求.collection_id, 请求.run_id, 请求.full_name),
        ).fetchone()
    return dict(结果)


@应用.get("/api/admin/review-queue")
def 获取复核队列(
    状态: Literal["待核验", "已核验", "不采用"] = "待核验",
    数量: Annotated[int, Query(ge=1, le=100)] = 20,
    管理密钥: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    校验管理权限(管理密钥)
    with 连接数据库() as 连接:
        结果 = [
            dict(行)
            for 行 in 连接.execute(
                """
                SELECT p.id, b.name AS book, p.section_title, p.text,
                       p.source_line_start, p.source_line_end, p.status,
                       p.can_generate, p.reviewed_at, p.reviewer, p.review_note,
                       s.path AS source_path, s.sha256
                FROM passages p
                JOIN books b ON b.id = p.book_id
                JOIN sources s ON s.id = p.source_id
                WHERE p.status = ?
                ORDER BY p.id
                LIMIT ?
                """,
                (状态, 数量),
            ).fetchall()
        ]
    return {"状态": 状态, "数量": len(结果), "片段": 结果}


@应用.post("/api/admin/passages/{passage_id}/review")
def 复核片段(
    passage_id: int,
    请求: 片段复核请求,
    管理密钥: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    校验管理权限(管理密钥)
    可生成 = 1 if 请求.状态 == "已核验" else 0
    with 连接数据库() as 连接:
        游标 = 连接.execute(
            """
            UPDATE passages
            SET status = ?, can_generate = ?, reviewed_at = ?,
                reviewer = ?, review_note = ?
            WHERE id = ?
            """,
            (
                请求.状态,
                可生成,
                datetime.now(timezone.utc).isoformat(),
                请求.复核人,
                请求.备注,
                passage_id,
            ),
        )
        if 游标.rowcount == 0:
            raise HTTPException(status_code=404, detail="片段不存在")
        结果 = 连接.execute(
            """
            SELECT p.id, b.name AS book, p.section_title, p.text,
                   p.source_line_start, p.source_line_end, p.status,
                   p.can_generate, p.reviewed_at, p.reviewer, p.review_note
            FROM passages p JOIN books b ON b.id = p.book_id
            WHERE p.id = ?
            """,
            (passage_id,),
        ).fetchone()
    查询缓存.清空()
    return dict(结果)


@应用.get("/api/admin/element-queue")
def 获取五行复核队列(
    状态: Literal["待复核", "已核验", "不采用"] = "待复核",
    数量: Annotated[int, Query(ge=1, le=100)] = 50,
    管理密钥: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    校验管理权限(管理密钥)
    with 连接数据库() as 连接:
        结果 = [
            dict(行)
            for 行 in 连接.execute(
                """
                SELECT char, element, method, confidence, status, note,
                       reviewed_at, reviewer
                FROM character_elements
                WHERE status = ?
                ORDER BY char, method
                LIMIT ?
                """,
                (状态, 数量),
            ).fetchall()
        ]
    return {"状态": 状态, "数量": len(结果), "规则": 结果}


@应用.post("/api/admin/characters/{char}/element-review")
def 复核五行规则(
    char: str,
    请求: 汉字五行复核请求,
    管理密钥: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    校验管理权限(管理密钥)
    if len(char) != 1:
        raise HTTPException(status_code=422, detail="一次只能复核一个汉字")
    with 连接数据库() as 连接:
        游标 = 连接.execute(
            """
            UPDATE character_elements
            SET status = ?, note = ?, reviewed_at = ?, reviewer = ?
            WHERE char = ? AND method = ?
            """,
            (
                请求.状态,
                请求.备注,
                datetime.now(timezone.utc).isoformat(),
                请求.复核人,
                char,
                请求.方法,
            ),
        )
        if 游标.rowcount == 0:
            raise HTTPException(status_code=404, detail="五行规则不存在")
        结果 = 连接.execute(
            """
            SELECT char, element, method, confidence, status, note,
                   reviewed_at, reviewer
            FROM character_elements
            WHERE char = ? AND method = ?
            """,
            (char, 请求.方法),
        ).fetchone()
    查询缓存.删除(("汉字", char))
    return dict(结果)


@应用.get("/api/admin/audit-queue")
def 获取审计问题队列(
    状态: Literal["待处理", "已处理", "忽略"] = "待处理",
    数量: Annotated[int, Query(ge=1, le=100)] = 50,
    管理密钥: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    校验管理权限(管理密钥)
    with 连接数据库() as 连接:
        结果 = [
            dict(行)
            for 行 in 连接.execute(
                """
                SELECT a.id, a.source_id, s.file_name, a.issue_type, a.detail,
                       a.status, a.reviewed_at, a.reviewer, a.review_note
                FROM audit_issues a
                LEFT JOIN sources s ON s.id = a.source_id
                WHERE a.status = ?
                ORDER BY a.id
                LIMIT ?
                """,
                (状态, 数量),
            ).fetchall()
        ]
    return {"状态": 状态, "数量": len(结果), "问题": 结果}


@应用.post("/api/admin/audit-issues/{issue_id}/review")
def 复核审计问题(
    issue_id: int,
    请求: 审计问题复核请求,
    管理密钥: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    校验管理权限(管理密钥)
    with 连接数据库() as 连接:
        游标 = 连接.execute(
            """
            UPDATE audit_issues
            SET status = ?, reviewed_at = ?, reviewer = ?, review_note = ?
            WHERE id = ?
            """,
            (
                请求.状态,
                datetime.now(timezone.utc).isoformat(),
                请求.复核人,
                请求.备注,
                issue_id,
            ),
        )
        if 游标.rowcount == 0:
            raise HTTPException(status_code=404, detail="审计问题不存在")
        结果 = 连接.execute(
            """
            SELECT a.id, a.source_id, s.file_name, a.issue_type, a.detail,
                   a.status, a.reviewed_at, a.reviewer, a.review_note
            FROM audit_issues a
            LEFT JOIN sources s ON s.id = a.source_id
            WHERE a.id = ?
            """,
            (issue_id,),
        ).fetchone()
    return dict(结果)


@应用.get("/api/admin/metrics")
def 获取质量统计(
    管理密钥: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    校验管理权限(管理密钥)
    with 连接数据库() as 连接:
        状态 = {
            行["status"]: 行["数量"]
            for 行 in 连接.execute(
                "SELECT status, COUNT(*) AS 数量 FROM name_runs GROUP BY status"
            ).fetchall()
        }
        反馈类型 = {
            行["feedback_type"]: 行["数量"]
            for 行 in 连接.execute(
                "SELECT feedback_type, COUNT(*) AS 数量 FROM feedback GROUP BY feedback_type"
            ).fetchall()
        }
        模型指标 = 连接.execute(
            """
            SELECT COUNT(*) AS 总数,
                   SUM(CASE WHEN status = '完成' THEN 1 ELSE 0 END) AS 成功数,
                   SUM(CASE WHEN status = '失败' THEN 1 ELSE 0 END) AS 失败数,
                   AVG(latency_ms) AS 平均耗时毫秒,
                   COALESCE(SUM(estimated_cost), 0) AS 估算成本
            FROM model_metrics
            """
        ).fetchone()
        统计 = {
            "任务总数": 连接.execute("SELECT COUNT(*) FROM name_runs").fetchone()[0],
            "任务状态": 状态,
            "候选总数": 连接.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
            "收藏总数": 连接.execute("SELECT COUNT(*) FROM favorites").fetchone()[0],
            "反馈总数": 连接.execute("SELECT COUNT(*) FROM feedback").fetchone()[0],
            "反馈类型": 反馈类型,
            "模型调用总数": 模型指标["总数"],
            "模型成功数": 模型指标["成功数"] or 0,
            "模型失败数": 模型指标["失败数"] or 0,
            "模型平均耗时毫秒": round(模型指标["平均耗时毫秒"] or 0, 2),
            "模型估算成本": 模型指标["估算成本"],
            "模型候选总数": 连接.execute(
                "SELECT COUNT(*) FROM model_candidates"
            ).fetchone()[0],
            "待处理问题数": 连接.execute(
                "SELECT COUNT(*) FROM audit_issues WHERE status = '待处理'"
            ).fetchone()[0],
            "已核验片段数": 连接.execute(
                "SELECT COUNT(*) FROM passages WHERE can_generate = 1"
            ).fetchone()[0],
            "已核验词组数": 连接.execute(
                "SELECT COUNT(*) FROM candidate_phrases WHERE status = '已核验'"
            ).fetchone()[0],
        }
    return 统计


@应用.post("/api/name-runs/{run_id}/model-candidates")
def 生成模型候选(run_id: str) -> dict:
    配置 = 读取环境配置()
    if not 模型已配置(配置):
        raise HTTPException(status_code=503, detail="起名模型尚未配置")
    with 连接数据库() as 连接:
        任务 = 连接.execute(
            "SELECT request_json FROM name_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if 任务 is None:
            raise HTTPException(status_code=404, detail="起名任务不存在")
        请求摘要 = json.loads(任务[0])
        证据行 = 连接.execute(
            """
            SELECT DISTINCT p.id, p.text, b.name, p.section_title
            FROM candidates c
            JOIN passages p ON p.id = c.source_passage_id
            JOIN books b ON b.id = p.book_id
            WHERE c.run_id = ? AND p.can_generate = 1
            """,
            (run_id,),
        ).fetchall()
        证据 = [语料证据(行[0], 行[1], 行[2], 行[3]) for 行 in 证据行]
    开始时间 = time.perf_counter()
    if not 证据:
        raise HTTPException(status_code=422, detail="没有可用于模型生成的已核验出处")
    if not 模型并发.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="模型服务正在忙，请稍后重试")
    try:
        候选 = 调用兼容模型(请求摘要, 证据, 配置)
    except RuntimeError as 异常:
        记录模型指标(run_id, 配置, 开始时间, "失败", str(异常))
        raise HTTPException(status_code=502, detail=str(异常)) from 异常
    finally:
        模型并发.release()
    记录模型指标(run_id, 配置, 开始时间, "完成")
    证据表 = {项目.编号: 项目 for 项目 in 证据}
    with 连接数据库() as 连接:
        for 项目 in 候选:
            当前证据 = 证据表[项目["语料编号"]]
            连接.execute(
                """
                INSERT INTO model_candidates(
                    run_id, name, passage_id, origin_type, meaning,
                    style_json, risks_json, source_offset, provider, model,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '已校验', ?)
                ON CONFLICT(run_id, name) DO UPDATE SET
                    passage_id = excluded.passage_id,
                    origin_type = excluded.origin_type,
                    meaning = excluded.meaning,
                    style_json = excluded.style_json,
                    risks_json = excluded.risks_json,
                    source_offset = excluded.source_offset,
                    provider = excluded.provider,
                    model = excluded.model,
                    status = excluded.status
                """,
                (
                    run_id,
                    项目["名字"],
                    项目["语料编号"],
                    项目["取字方式"],
                    项目["现代释义"],
                    json.dumps(项目["风格标签"], ensure_ascii=False),
                    json.dumps(项目["风险提示"], ensure_ascii=False),
                    项目["原文位置"],
                    配置.地址,
                    配置.模型,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
    return {"状态": "完成", "任务编号": run_id, "候选": 候选, "保存数量": len(候选)}


@应用.get("/api/name-runs/{run_id}/model-candidates")
def 获取模型候选(run_id: str) -> dict:
    with 连接数据库() as 连接:
        结果 = [
            dict(行)
            for 行 in 连接.execute(
                """
                SELECT m.*, p.text AS evidence_text FROM model_candidates m
                JOIN passages p ON p.id = m.passage_id
                WHERE m.run_id = ? ORDER BY m.id
                """,
                (run_id,),
            ).fetchall()
        ]
    for 项目 in 结果:
        项目["风格标签"] = json.loads(项目.pop("style_json"))
        项目["风险提示"] = json.loads(项目.pop("risks_json"))
        项目["取字位置"] = 取字位置(项目["name"], 项目.pop("evidence_text"), 项目["origin_type"])
        项目.pop("provider", None)
    return {"任务编号": run_id, "数量": len(结果), "候选": 结果}


应用.mount("/static", StaticFiles(directory=前端目录), name="static")
