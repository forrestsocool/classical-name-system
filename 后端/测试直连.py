"""仅供微信测试号体验的 HTTPS 直连会话。

正式小程序继续使用 CloudBase 云函数。微信测试号按平台规则不能使用云开发，
因此这里用 wx.login 的 code 换取 openid，再用服务器签发的短期令牌调用同一套业务动作。
该路由默认关闭，必须显式设置 ENABLE_TEST_HTTP_BRIDGE=1。
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request

from fastapi import HTTPException
from pydantic import Field

from .小程序业务 import 严格参数, 动作
from .网关鉴权 import 登记与限流, 用户身份


class 测试登录请求(严格参数):
    code: str = Field(min_length=1, max_length=512)


class 测试分发请求(严格参数):
    action: str = Field(max_length=32)
    data: dict = Field(default_factory=dict)


def 已启用():
    return os.getenv("ENABLE_TEST_HTTP_BRIDGE", "0") == "1"


def _secret():
    secret = os.getenv("GATEWAY_SECRET", "")
    if len(secret) < 32 or not secret.isascii():
        raise HTTPException(503, "接入服务尚未配置")
    return secret.encode()


def _编码(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _解码(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def 签发令牌(appid, openid):
    payload = json.dumps({"appid": appid, "openid": openid,
                          "exp": int(time.time()) + int(os.getenv("TEST_SESSION_TTL", "86400"))},
                         separators=(",", ":"), ensure_ascii=False).encode()
    encoded = _编码(payload).encode()
    signature = hmac.new(_secret(), encoded, hashlib.sha256).digest()
    return encoded.decode() + "." + _编码(signature)


def 解析令牌(token):
    try:
        encoded, encoded_signature = token.split(".", 1)
        expected = hmac.new(_secret(), encoded.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _解码(encoded_signature)):
            raise ValueError
        payload = json.loads(_解码(encoded))
        if payload.get("appid") != os.getenv("WECHAT_APP_ID", "") or int(payload["exp"]) < int(time.time()):
            raise ValueError
        return payload["appid"], payload["openid"]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeError):
        raise HTTPException(401, "测试会话无效或已过期") from None


def 换取开放身份(code):
    appid = os.getenv("WECHAT_APP_ID", "")
    secret = os.getenv("WECHAT_APP_SECRET", "")
    if not appid or not secret:
        raise HTTPException(503, "微信登录尚未配置")
    query = urllib.parse.urlencode({"appid": appid, "secret": secret,
                                    "js_code": code, "grant_type": "authorization_code"})
    request = urllib.request.Request("https://api.weixin.qq.com/sns/jscode2session?" + query,
                                     headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            result = json.loads(response.read(64 * 1024).decode("utf-8"))
    except Exception:
        raise HTTPException(503, "微信登录服务暂时不可用") from None
    if result.get("errcode") or not result.get("openid"):
        raise HTTPException(401, "微信登录失败，请重新打开小程序")
    return appid, result["openid"]


def 测试分发(token, request: 测试分发请求):
    appid, openid = 解析令牌(token)
    owner = 用户身份(appid, openid)
    if request.action not in 动作:
        raise HTTPException(404, "操作不存在")
    类型, 函数 = 动作[request.action]
    参数 = 类型.model_validate(request.data)
    登记与限流(owner)
    return 函数(owner, 参数)
