from pathlib import Path
import logging
import time
import re

import psycopg
from psycopg_pool import PoolTimeout
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .数据库 import 连接数据库, 使用请求连接池
from .网关鉴权 import 校验签名, 用户身份, 登记与限流
from .小程序业务 import 严格参数, 动作
from .小程序业务 import 可分享物料
from .分享图片 import 渲染分享图片
from .测试直连 import 已启用, 测试分发, 测试分发请求, 测试登录请求, 换取开放身份, 签发令牌
from .管理接口 import 路由 as 管理路由, 管理权限

应用 = FastAPI(title="古籍起名管理与小程序内部服务", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None)
性能日志 = logging.getLogger("name_system.dispatch")
应用.include_router(管理路由)
目录 = Path(__file__).resolve().parents[1] / "管理前端"
应用.mount("/admin/static", StaticFiles(directory=目录), name="admin-static")


class 网关请求(严格参数):
    appid: str = Field(max_length=32)
    openid: str = Field(max_length=128)
    action: str = Field(max_length=32)
    data: dict = Field(default_factory=dict)


@应用.middleware("http")
async def 响应保护(request, call_next):
    response = await call_next(request)
    response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'"})
    return response


@应用.exception_handler(RequestValidationError)
@应用.exception_handler(ValidationError)
async def 参数异常(request, exc):
    return JSONResponse({"detail": "请求参数格式不正确"}, status_code=422)


@应用.exception_handler(psycopg.Error)
@应用.exception_handler(PoolTimeout)
async def 数据库异常(request, exc):
    return JSONResponse({"detail": "服务暂时不可用，请稍后重试"}, status_code=503)


@应用.get("/", include_in_schema=False)
def 根页面():
    return RedirectResponse("/admin")


@应用.get("/admin", include_in_schema=False)
def 管理首页():
    return FileResponse(目录 / "index.html")


@应用.get("/api/health")
def 健康检查():
    return {"status": "ok"}


@应用.get('/share-card/{token}.jpg', include_in_schema=False)
def 分享卡片图片(token: str):
    if not re.fullmatch(r'[A-Za-z0-9_-]{32}',token):
        raise HTTPException(404,'分享图片不可查看')
    with 使用请求连接池(), 连接数据库() as connection:
        row=可分享物料(connection,token=token)
    if not row:
        raise HTTPException(404,'分享图片不可查看')
    return Response(渲染分享图片(row),media_type='image/jpeg')


@应用.get("/api/ready")
def 就绪检查():
    try:
        with 连接数据库() as c:
            ready = c.execute("SELECT EXISTS(SELECT 1 FROM passages WHERE can_generate=1) AS ready").fetchone()["ready"]
            c.execute("SELECT 1 FROM app_materials LIMIT 1")
        if not ready:
            raise HTTPException(503, "资料尚未导入")
    except (psycopg.Error, RuntimeError):
        raise HTTPException(503, "数据库尚未就绪") from None
    return {"status": "ready"}


@应用.get("/metrics", dependencies=[Depends(管理权限)])
def 监控指标():
    with 连接数据库() as c:
        stock = c.execute("SELECT count(*) AS n FROM app_materials").fetchone()["n"]
        batches = c.execute("SELECT COALESCE(sum(batches),0) AS n FROM app_budget WHERE day=CURRENT_DATE").fetchone()["n"]
        worker = c.execute("SELECT heartbeat>now()-interval '5 minutes' AND status<>'已停止' AS alive FROM app_worker WHERE id=1").fetchone()
        failures = c.execute("SELECT count(*) AS n FROM app_source_progress WHERE failures>0").fetchone()["n"]
    lines = []
    for name, value in {"name_inventory_total": stock, "name_producer_batches_today": batches,
                        "name_producer_alive": int(bool(worker and worker["alive"])), "name_producer_failing_sources": failures}.items():
        lines.extend([f"# TYPE {name} gauge", f"{name} {value}"])
    return PlainTextResponse("\n".join(lines)+"\n", media_type="text/plain; version=0.0.4")


def 分发(headers, body):
    started = time.perf_counter()
    authenticated = limited = started
    action = "unknown"
    with 使用请求连接池():
        try:
            校验签名(headers, body)
            请求 = 网关请求.model_validate_json(body)
            owner = 用户身份(请求.appid, 请求.openid)
            if 请求.action not in 动作:
                raise HTTPException(404, "操作不存在")
            action = 请求.action
            类型, 函数 = 动作[action]
            参数 = 类型.model_validate(请求.data)
            authenticated = time.perf_counter()
            登记与限流(owner)
            limited = time.perf_counter()
            return 函数(owner, 参数)
        finally:
            finished = time.perf_counter()
            # No user id, request parameters or response payload in logs.
            if finished - started >= 0.5:
                性能日志.info("action=%s auth_ms=%.0f rate_ms=%.0f business_ms=%.0f total_ms=%.0f",
                    action, (authenticated-started)*1000, (limited-authenticated)*1000,
                    (finished-limited)*1000, (finished-started)*1000)


@应用.post("/internal/v1/dispatch")
async def 内部接入(request: Request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise HTTPException(413, "请求过大")
    return await run_in_threadpool(分发, dict(request.headers), bytes(body))


@应用.post("/api/test/session", include_in_schema=False)
async def 测试号登录(body: 测试登录请求):
    if not 已启用():
        raise HTTPException(404, "测试接入未启用")
    appid, openid = await run_in_threadpool(换取开放身份, body.code)
    return {"token": 签发令牌(appid, openid), "user_id": 用户身份(appid, openid)}


@应用.post("/api/test/dispatch", include_in_schema=False)
async def 测试号分发(body: 测试分发请求, authorization: str = Header(default="")):
    if not 已启用():
        raise HTTPException(404, "测试接入未启用")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "测试会话无效或已过期")
    return {"ok": True, "data": await run_in_threadpool(测试分发, token, body)}
