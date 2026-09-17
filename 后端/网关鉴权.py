import hashlib
import hmac
import os
import re
import time
from datetime import datetime, timezone

from fastapi import HTTPException

from .数据库 import 连接数据库


def 签名原文(timestamp, nonce, body):
    return f"v1\n{timestamp}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode()


def 校验签名(headers, body):
    密钥 = os.getenv("GATEWAY_SECRET", "")
    if len(密钥) < 32 or not 密钥.isascii():
        raise HTTPException(503, "接入服务尚未配置")
    时间 = headers.get("x-gateway-timestamp", "")
    nonce = headers.get("x-gateway-nonce", "")
    签名 = headers.get("x-gateway-signature", "")
    if not re.fullmatch(r"[0-9]{10}", 时间) or not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise HTTPException(401, "接入凭据无效")
    if abs(time.time() - int(时间)) > 300:
        raise HTTPException(401, "接入凭据已过期")
    预期 = hmac.new(密钥.encode(), 签名原文(时间, nonce, body), hashlib.sha256).hexdigest()
    if not re.fullmatch(r"[a-f0-9]{64}", 签名) or not hmac.compare_digest(预期, 签名):
        raise HTTPException(401, "接入凭据无效")
    with 连接数据库() as c:
        c.execute("DELETE FROM app_nonces WHERE expires_at < now()")
        行 = c.execute("INSERT INTO app_nonces VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING nonce",
                      (nonce, datetime.fromtimestamp(int(时间) + 301, timezone.utc))).fetchone()
        if not 行:
            raise HTTPException(409, "接入请求已处理")


def 用户身份(appid, openid):
    if appid != os.getenv("WECHAT_APP_ID", "") or not re.fullmatch(r"wx[a-f0-9]{16}", appid):
        raise HTTPException(401, "小程序身份无效")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", openid):
        raise HTTPException(401, "用户身份无效")
    return hashlib.sha256(f"{appid}:{openid}".encode()).hexdigest()


def 登记与限流(owner):
    with 连接数据库() as c:
        c.execute("INSERT INTO app_users(id) VALUES (%s) ON CONFLICT DO NOTHING", (owner,))
        窗口 = int(time.time() // 60)
        次数 = c.execute("""INSERT INTO app_rate_limits VALUES (%s,%s,1)
            ON CONFLICT(owner) DO UPDATE SET minute_window=excluded.minute_window,
            requests=CASE WHEN app_rate_limits.minute_window=excluded.minute_window THEN app_rate_limits.requests+1 ELSE 1 END
            RETURNING requests""", (owner, 窗口)).fetchone()["requests"]
    if 次数 > int(os.getenv("USER_REQUESTS_PER_MINUTE", "120")):
        raise HTTPException(429, "操作太快，请稍后再试", headers={"Retry-After": "60"})
