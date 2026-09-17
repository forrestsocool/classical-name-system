from pathlib import Path

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .数据库 import 连接数据库
from .网关鉴权 import 校验签名, 用户身份, 登记与限流
from .小程序业务 import 严格参数, 动作
from .管理接口 import 路由 as 管理路由, 管理权限

应用 = FastAPI(title="古籍起名管理与小程序内部服务", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None)
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
    校验签名(headers, body)
    请求 = 网关请求.model_validate_json(body)
    owner = 用户身份(请求.appid, 请求.openid)
    if 请求.action not in 动作:
        raise HTTPException(404, "操作不存在")
    类型, 函数 = 动作[请求.action]
    参数 = 类型.model_validate(请求.data)
    登记与限流(owner)
    return 函数(owner, 参数)


@应用.post("/internal/v1/dispatch")
async def 内部接入(request: Request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise HTTPException(413, "请求过大")
    return await run_in_threadpool(分发, dict(request.headers), bytes(body))
