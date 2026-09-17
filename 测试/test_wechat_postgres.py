"""Real PostgreSQL contract tests. TEST_DATABASE_URL must allow CREATE DATABASE."""
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from 后端 import 持续生产 as producer
from 后端.数据库 import 连接数据库
from 后端.小程序服务 import 应用
from 后端.网关鉴权 import 签名原文
from 后端.模型接口 import 模型配置
from 脚本.迁移PostgreSQL import 迁移

ROOT = Path(__file__).resolve().parents[1]
APPID = "wx1234567890abcdef"
SECRET = "test-gateway-secret-2026-32-characters"


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "需要 TEST_DATABASE_URL 的真实 PostgreSQL 集成测试")
class PostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = os.environ["TEST_DATABASE_URL"]
        cls.dbname = "codex_names_test_" + uuid.uuid4().hex
        with psycopg.connect(cls.base, autocommit=True) as c:
            c.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(cls.dbname)))
        cfg = conninfo_to_dict(cls.base)
        cfg["dbname"] = cls.dbname
        cls.dsn = make_conninfo(**cfg)
        # Production entry accepts URL only; use test driver connection directly through module patch.
        cls.patches = []
        def connect():
            return psycopg.connect(cls.dsn, row_factory=dict_row, options="-c timezone=UTC -c statement_timeout=15000")
        cls.connect = staticmethod(connect)
        for module in ("后端.数据库", "后端.网关鉴权", "后端.小程序业务", "后端.小程序服务", "后端.管理接口", "后端.持续生产"):
            p = patch(module + ".连接数据库", connect)
            p.start()
            cls.patches.append(p)
        cls.env = patch.dict(os.environ, {"GATEWAY_SECRET": SECRET, "WECHAT_APP_ID": APPID,
            "起名管理密钥": "test-admin-key-2026", "起名管理密钥文件": "", "USER_REQUESTS_PER_MINUTE": "1000", "PRODUCER_DAILY_BATCHES": "2"})
        cls.env.start()
        with connect() as c:
            cls.counts = 迁移(ROOT / "构建产物/起名系统.sqlite3", c)
        cls.client = TestClient(应用)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        for p in cls.patches:
            p.stop()
        cls.env.stop()
        with psycopg.connect(cls.base, autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(cls.dbname)))

    def setUp(self):
        with self.connect() as c:
            tables = c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'app_%' AND tablename<>'app_migrations'").fetchall()
            c.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(sql.SQL(",").join(sql.Identifier(x["tablename"]) for x in tables)))
            self.profile = c.execute("INSERT INTO app_profiles(surname,name_length) VALUES ('李',2) RETURNING id").fetchone()["id"]
            p = c.execute("SELECT p.id,p.text,p.section_title,b.name AS book FROM passages p JOIN books b ON b.id=p.book_id WHERE p.can_generate=1 ORDER BY p.id LIMIT 1").fetchone()
            self.passage = p
            for index, name in enumerate(("清和", "知远", "明德", "清清", "文轩", "思齐", "望舒", "嘉宁", "云舟", "书涵", "怀瑾", "如玉")):
                payload = {"姓名": "李"+name, "名字": name, "书名": p["book"], "篇章": p["section_title"], "原文": p["text"],
                    "来源片段编号": p["id"], "原文位置": 0, "取字方式": "原文连取", "出处核验状态": "已核验", "基础分": 90,
                    "现代释义": "测试释义", "文化标签": ["清朗"], "拼音带调": "qīng hé"}
                c.execute("INSERT INTO app_materials(profile_id,given_name,full_name,book,passage_id,payload) VALUES (%s,%s,%s,%s,%s,%s)",
                          (self.profile,name,"李"+name,p["book"],p["id"],Jsonb(payload)))

    def request(self, action, data=None, user="user-A", **kw):
        import time
        body = json.dumps({"appid": APPID, "openid": user, "action": action, "data": data or {}}, ensure_ascii=False).encode()
        timestamp = str(kw.get("timestamp", int(time.time())))
        nonce = kw.get("nonce", uuid.uuid4().hex)
        signature = hmac.new(SECRET.encode(), 签名原文(timestamp,nonce,body), hashlib.sha256).hexdigest()
        headers = {"X-Gateway-Timestamp": timestamp,"X-Gateway-Nonce": nonce,"X-Gateway-Signature": signature,"Content-Type":"application/json"}
        if kw.get("tamper"):
            body += b" "
        return self.client.post("/internal/v1/dispatch", content=body, headers=headers)

    def pull(self, **kw):
        return {"request_id": str(uuid.uuid4()),"surname":"李","name_length":2,**kw}

    def test_migration_preserves_counts_and_sequences_and_rejects_repeat(self):
        self.assertGreater(self.counts["passages"], 9000)
        with self.connect() as c:
            count = c.execute("SELECT count(*) AS n FROM passages").fetchone()["n"]
            self.assertEqual(count, self.counts["passages"])
            with self.assertRaises(RuntimeError):
                迁移(ROOT / "构建产物/起名系统.sqlite3", c)
        with self.connect() as c:
            maximum = c.execute("SELECT max(id) AS n FROM books").fetchone()["n"]
            sequence = c.execute("SELECT last_value FROM books_id_seq").fetchone()["last_value"]
            self.assertEqual(maximum, sequence)

    def test_signature_replay_expiry_and_tampering(self):
        nonce = uuid.uuid4().hex
        self.assertEqual(self.request("session.get", nonce=nonce).status_code,200)
        self.assertEqual(self.request("session.get", nonce=nonce).status_code,409)
        self.assertEqual(self.request("session.get", timestamp=1000000000).status_code,401)
        self.assertEqual(self.request("session.get", tamper=True).status_code,401)
        self.assertEqual(self.client.post('/internal/v1/dispatch',json={}).status_code,401)
        self.assertEqual(self.client.post('/internal/v1/dispatch',content=b'x'*17000).status_code,413)

    def test_node_gateway_signature_matches_python_for_unicode_payload(self):
        body=json.dumps({'appid':APPID,'openid':'unicode-user','action':'feed.pull','data':self.pull(required='清')},ensure_ascii=False).encode()
        script="const fs=require('node:fs');const {signedHeaders}=require('./云函数/nameGateway/gateway');const body=fs.readFileSync(0);process.stdout.write(JSON.stringify(signedHeaders(body,process.env.GATEWAY_SECRET)));"
        result=subprocess.run(['node','-e',script],input=body,capture_output=True,check=True,cwd=ROOT)
        headers=json.loads(result.stdout)
        response=self.client.post('/internal/v1/dispatch',content=body,headers={k:str(v) for k,v in headers.items()})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['cards'])

    def test_idempotency_and_filter_multiplicity(self):
        data = self.pull(required="清清")
        first = self.request("feed.pull",data)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual([x["item"]["名字"] for x in first.json()["cards"]],["清清"])
        self.assertEqual(self.request("feed.pull",data).json(),first.json())
        self.assertEqual(self.request("feed.pull",{**data,"required":"清"}).status_code,409)
        filtered = self.request("feed.pull",self.pull(required="清",excluded="和")).json()
        self.assertEqual(filtered["cards"],[])

    def test_concurrent_pulls_exactly_once_per_user(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _:self.request("feed.pull",self.pull(count=4)),range(4)))
        self.assertTrue(all(x.status_code==200 for x in results))
        names=[x["item"]["姓名"] for r in results for x in r.json()["cards"]]
        self.assertEqual(len(names),12)
        self.assertEqual(len(names),len(set(names)))

    def test_user_ownership_favorite_retry_compare_and_feedback(self):
        cards=self.request("feed.pull",self.pull(count=2)).json()["cards"]
        ids=[x["id"] for x in cards]
        self.assertEqual(self.request("favorites.add",{"material_id":ids[0]},user="user-B").status_code,404)
        self.assertEqual(self.request("feedback.save",{"material_id":ids[0],"kind":"出处问题"},user="user-B").status_code,404)
        for id in ids:
            self.assertEqual(self.request("favorites.add",{"material_id":id}).status_code,200)
            self.assertEqual(self.request("favorites.add",{"material_id":id}).status_code,200)
        self.assertEqual(len(self.request("favorites.list").json()["cards"]),2)
        self.assertEqual(self.request("favorites.list",user="user-B").json()["cards"],[])
        self.assertEqual(self.request("favorites.compare",{"material_ids":ids},user="user-B").status_code,404)
        self.assertEqual(self.request("favorites.compare",{"material_ids":ids}).status_code,200)
        self.request("favorites.remove",{"material_id":ids[0]},user="user-B")
        self.assertEqual(len(self.request("favorites.list").json()["cards"]),2)
        self.assertEqual(self.request("feed.pull",self.pull(count=2),user="user-B").json()["cards"],cards)

    def test_admin_boundary_and_old_web_removed(self):
        for path in ('/api/feed/pull','/api/name-runs','/static/app.js','/docs','/api/model/status'):
            self.assertEqual(self.client.get(path).status_code,404,path)
        self.assertEqual(self.client.get('/api/admin/metrics').status_code,403)
        self.assertEqual(self.request('admin.metrics').status_code,404)
        self.assertEqual(self.client.get('/api/admin/metrics',headers={'X-Admin-Key':'test-admin-key-2026'}).status_code,200)
        self.assertEqual(self.client.get('/').url.path,'/admin')
        self.assertEqual(self.client.get('/api/ready').status_code,200)

    def test_parameter_validation_rate_limit_and_pause(self):
        self.assertEqual(self.request('feed.pull',self.pull(owner='someone')).status_code,422)
        with patch.dict(os.environ,{'USER_REQUESTS_PER_MINUTE':'1'}):
            self.assertEqual(self.request('session.get',user='limited').status_code,200)
            self.assertEqual(self.request('session.get',user='limited').status_code,429)
            self.assertEqual(self.request('session.get',user='independent').status_code,200)
        self.client.put('/api/admin/profiles',headers={'X-Admin-Key':'test-admin-key-2026'},json={'surname':'李','name_length':2,'enabled':False})
        self.request('feed.pull',self.pull())
        with self.connect() as c:
            self.assertFalse(c.execute('SELECT enabled FROM app_profiles WHERE id=%s',(self.profile,)).fetchone()['enabled'])

    def test_worker_persists_inventory_and_budget_without_active_users(self):
        config=模型配置(地址='https://example.com/v1/chat/completions',密钥='test-only',模型='test')
        def approve(items, request, config):
            return [{**x,'基础分':90,'现代释义':'结合古籍语境的测试释义','文化标签':['清朗']} for x in items[:2]]
        with patch.object(producer,'读取环境配置',return_value=config), patch.object(producer,'验证模型地址'), patch.object(producer,'模型筛选单批',side_effect=approve) as model:
            self.assertTrue(producer.生产一次())
            self.assertTrue(producer.生产一次())
            self.assertFalse(producer.生产一次())
            self.assertEqual(model.call_count,2)
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT batches FROM app_budget').fetchone()['batches'],2)
            self.assertGreater(c.execute('SELECT count(*) AS n FROM app_attempts').fetchone()['n'],0)
            self.assertGreater(c.execute('SELECT count(*) AS n FROM app_materials').fetchone()['n'],12)
            self.assertEqual(c.execute('SELECT count(*) AS n FROM app_users').fetchone()['n'],0)

    def test_worker_failure_consumes_budget_but_can_retry_candidates(self):
        config=模型配置(地址='https://example.com/v1/chat/completions',密钥='test-only',模型='test')
        with patch.object(producer,'读取环境配置',return_value=config),patch.object(producer,'验证模型地址'),patch.object(producer,'模型筛选单批',side_effect=RuntimeError('must-not-leak-secret')):
            self.assertFalse(producer.生产一次())
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT batches FROM app_budget').fetchone()['batches'],1)
            self.assertEqual(c.execute('SELECT count(*) AS n FROM app_attempts').fetchone()['n'],0)
            row=c.execute('SELECT failures,last_error,retry_at>now() AS delayed FROM app_source_progress').fetchone()
            self.assertEqual(row['failures'],1)
            self.assertTrue(row['delayed'])
            self.assertNotIn('secret',row['last_error'])

    def test_producer_singleton_lock(self):
        with self.connect() as a,self.connect() as b:
            self.assertTrue(a.execute('SELECT pg_try_advisory_lock(%s) AS ok',(producer.生产锁,)).fetchone()['ok'])
            self.assertFalse(b.execute('SELECT pg_try_advisory_lock(%s) AS ok',(producer.生产锁,)).fetchone()['ok'])

    def test_migration_failure_rolls_back_all_new_tables(self):
        # Deliberately incomplete input, isolated target namespace in the disposable database.
        schema = 'failed_migration_' + uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'incomplete.sqlite3'
            with closing(sqlite3.connect(source)) as c:
                c.execute('CREATE TABLE schema_version(id INTEGER PRIMARY KEY,version TEXT,built_at TEXT)')
                c.execute("INSERT INTO schema_version VALUES (1,'test','today')")
                c.commit()
            with self.connect() as c:
                c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
                c.commit()
                c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
                c.commit()
                with self.assertRaisesRegex(RuntimeError,'缺少表'):
                    迁移(source,c)
                self.assertIsNone(c.execute("SELECT to_regclass('sources') AS name").fetchone()['name'])
                self.assertIsNone(c.execute("SELECT to_regclass('schema_version') AS name").fetchone()['name'])
                c.execute(sql.SQL('DROP SCHEMA {}').format(sql.Identifier(schema)))

    def test_revoked_passages_are_not_served_and_metrics_are_private(self):
        with self.connect() as c:
            c.execute('UPDATE passages SET can_generate=0 WHERE id=%s',(self.passage['id'],))
        try:
            self.assertEqual(self.request('feed.pull',self.pull()).json()['cards'],[])
        finally:
            with self.connect() as c:
                c.execute('UPDATE passages SET can_generate=1 WHERE id=%s',(self.passage['id'],))
        self.assertEqual(self.client.get('/metrics').status_code,403)
        r=self.client.get('/metrics',headers={'Authorization':'Bearer test-admin-key-2026'})
        self.assertEqual(r.status_code,200)
        self.assertIn('name_inventory_total 12',r.text)


if __name__ == '__main__':
    unittest.main()
