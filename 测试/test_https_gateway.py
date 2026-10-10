import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from 后端 import HTTPS接入 as gateway
from 后端.小程序服务 import 应用
from 后端.网关鉴权 import 用户身份

APPID='wx3d9171fa1ecde642'
SECRET='test-http-session-secret-at-least-32-characters'


class HTTPSGatewayTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ, {'WECHAT_APP_ID':APPID, 'GATEWAY_SECRET':SECRET})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client=TestClient(应用)
        self.addCleanup(self.client.close)

    def test_login_uses_server_verified_wechat_identity_and_keeps_user_id(self):
        with patch.object(gateway,'换取开放身份',return_value=(APPID,'openid-A')), \
             patch.object(gateway,'登记与限流') as limit:
            response=self.client.post('/api/v1/dispatch',json={'action':'session.get','code':'wechat-code-123','data':{}})
        self.assertEqual(response.status_code,200)
        data=response.json()['data']
        self.assertEqual(data['user_id'],用户身份(APPID,'openid-A'))
        self.assertEqual(gateway.解析HTTPS令牌(data['sessionToken']),(APPID,'openid-A'))
        limit.assert_called_once_with(data['user_id'])
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertNotIn(SECRET,response.text)

    def test_business_requires_token_and_rejects_client_identity(self):
        response=self.client.post('/api/v1/dispatch',json={'action':'favorites.list','data':{}})
        self.assertEqual(response.status_code,401)
        self.assertFalse(response.json()['ok'])
        response=self.client.post('/api/v1/dispatch',json={'action':'session.get','code':'wechat-code-123','openid':'forged'})
        self.assertEqual(response.status_code,422)

    def test_tampered_expired_wrong_app_and_old_bridge_tokens_are_rejected(self):
        with patch.object(gateway.time,'time',return_value=100000):
            token=gateway.签发HTTPS令牌(APPID,'openid-A')
        for invalid in (token+'x', None, 'not-a-token'):
            with self.assertRaises(HTTPException) as caught:
                gateway.解析HTTPS令牌(invalid)
            self.assertEqual(caught.exception.status_code,401)
        with patch.object(gateway.time,'time',return_value=100000+gateway.SESSION_TTL):
            with self.assertRaises(HTTPException): gateway.解析HTTPS令牌(token)
        with patch.dict(os.environ,{'WECHAT_APP_ID':'wx1234567890abcdef'}):
            with self.assertRaises(HTTPException): gateway.解析HTTPS令牌(token)
        from 后端.测试直连 import 签发令牌
        with self.assertRaises(HTTPException): gateway.解析HTTPS令牌(签发令牌(APPID,'openid-A'))

    def test_verified_token_routes_same_actions_with_same_owner(self):
        token=gateway.签发HTTPS令牌(APPID,'openid-A')
        seen=[]
        with patch.object(gateway,'登记与限流'), patch.dict(gateway.动作, {
            'sources.list':(gateway.严格参数,lambda owner,p: seen.append(owner) or {'sources':[]})}):
            response=self.client.post('/api/v1/dispatch',json={'action':'sources.list','sessionToken':token,'data':{}})
        self.assertEqual(response.json(),{'ok':True,'data':{'sources':[]}})
        self.assertEqual(seen,[用户身份(APPID,'openid-A')])

    def test_validation_limits_and_login_failure_use_client_error_contract(self):
        for payload in ({'action':'session.get','code':'ab'}, {'action':'favorites.add','data':{'material_id':0}}):
            self.assertEqual(self.client.post('/api/v1/dispatch',json=payload).status_code,422)
        response=self.client.post('/api/v1/dispatch',content=b'x'*16385)
        self.assertEqual(response.status_code,413)
        with patch.object(gateway,'换取开放身份',side_effect=HTTPException(503,'微信登录尚未配置')):
            response=self.client.post('/api/v1/dispatch',json={'action':'session.get','code':'wechat-code-123'})
        self.assertEqual(response.json(),{'ok':False,'status':503,'message':'微信登录尚未配置'})
