"""Production wx.login + HTTPS session gateway, independent of CloudBase."""
import base64
import hashlib
import hmac
import json
import os
import re
import time

from fastapi import HTTPException
from pydantic import Field

from .数据库 import 使用请求连接池
from .小程序业务 import 严格参数, 动作
from .网关鉴权 import 用户身份, 登记与限流
from .测试直连 import 换取开放身份

SESSION_TTL = 12 * 60 * 60


class HTTPS请求(严格参数):
    action: str = Field(min_length=1, max_length=32)
    data: dict = Field(default_factory=dict)
    code: str | None = Field(default=None, min_length=8, max_length=512, pattern=r'^[A-Za-z0-9_-]+$')
    sessionToken: str | None = Field(default=None, max_length=1024)


def _密钥():
    secret = os.getenv('GATEWAY_SECRET', '')
    if len(secret) < 32 or not secret.isascii():
        raise HTTPException(503, '接入服务尚未配置')
    return secret.encode()


def _编码(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def 签发HTTPS令牌(appid, openid):
    用户身份(appid, openid)
    now = int(time.time())
    payload = _编码(json.dumps({'v':1, 'appid':appid, 'openid':openid, 'iat':now,
        'exp':now+SESSION_TTL}, separators=(',', ':')).encode())
    signature = hmac.new(_密钥(), ('miniprogram-http-v1\n'+payload).encode(), hashlib.sha256).digest()
    return payload+'.'+_编码(signature)


def 解析HTTPS令牌(token):
    secret = _密钥()
    try:
        if not isinstance(token, str) or len(token)>1024 or not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', token):
            raise ValueError
        payload, signature = token.split('.')
        expected = _编码(hmac.new(secret, ('miniprogram-http-v1\n'+payload).encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
        now = int(time.time())
        if data['v']!=1 or type(data['iat']) is not int or type(data['exp']) is not int or not data['iat']<=now<data['exp'] or data['exp']-data['iat']!=SESSION_TTL:
            raise ValueError
        用户身份(data['appid'], data['openid'])
        return data['appid'], data['openid']
    except (ValueError, KeyError, TypeError, UnicodeError, HTTPException):
        raise HTTPException(401, '会话无效或已过期，请重新登录') from None


def HTTPS分发(request):
    if request.action not in 动作:
        raise HTTPException(404, '操作不存在')
    类型, 函数 = 动作[request.action]
    参数 = 类型.model_validate(request.data)
    if request.action == 'session.get' and request.code:
        appid, openid = 换取开放身份(request.code)
        token = 签发HTTPS令牌(appid, openid)
    else:
        if request.code:
            raise HTTPException(422, '登录码仅用于创建会话')
        appid, openid = 解析HTTPS令牌(request.sessionToken)
        token = request.sessionToken
    owner = 用户身份(appid, openid)
    with 使用请求连接池():
        登记与限流(owner)
        if request.action == 'session.get':
            return {'user_id':owner, 'openid':openid, 'sessionToken':token}
        return 函数(owner, 参数)
