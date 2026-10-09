"""Real PostgreSQL contract tests. TEST_DATABASE_URL must allow CREATE DATABASE."""
import hashlib
import hmac
import json
import os
import shutil
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
from 后端.数据库 import 连接数据库, 资料查询
from 后端.智能筛选 import 批量召回
from 后端.小程序服务 import 应用
from 后端.网关鉴权 import 签名原文, 用户身份
from 后端.模型接口 import 模型配置
from 脚本.迁移PostgreSQL import 迁移
from 脚本.升级共享名字队列 import 升级

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
            "起名管理密钥": "test-admin-key-2026", "起名管理密钥文件": "", "USER_REQUESTS_PER_MINUTE": "1000", "PRODUCER_DAILY_BATCHES": "0"})
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
            self.single_profile = c.execute("INSERT INTO app_profiles(surname,name_length) VALUES ('',1) RETURNING id").fetchone()["id"]
            self.double_profile = c.execute("INSERT INTO app_profiles(surname,name_length) VALUES ('',2) RETURNING id").fetchone()["id"]
            p = c.execute("""SELECT p.id,p.text,p.section_title,b.name AS book FROM passages p
                JOIN books b ON b.id=p.book_id WHERE p.can_generate=1 AND p.active_for_recall AND b.name<>'东亚年号'
                ORDER BY p.id LIMIT 1""").fetchone()
            self.passage = p
            names = ((self.single_profile, ("宁", "安", "和", "清", "嘉", "远")),
                     (self.double_profile, ("清和", "知远", "明德", "清清", "文轩", "思齐", "望舒", "嘉宁", "云舟", "书涵", "怀瑾", "如玉")))
            for profile, values in names:
                for index, name in enumerate(values):
                    male_score, female_score = ((78,22) if index % 2 == 0 else (31,69))
                    payload = {"姓名": name, "名字": name, "书名": p["book"], "篇章": p["section_title"], "原文": p["text"],
                        "来源片段编号": p["id"], "原文位置": 0, "取字方式": "原文连取", "出处核验状态": "已核验", "基础分": 90,
                        "现代释义": "测试释义", "文化标签": ["清朗"], "拼音带调": "qīng hé",
                        "男孩适配分": male_score, "女孩适配分": female_score}
                    c.execute("INSERT INTO app_materials(profile_id,given_name,full_name,book,passage_id,payload) VALUES (%s,%s,%s,%s,%s,%s)",
                              (profile,name,name,p["book"],p["id"],Jsonb(payload)))

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
        return {"request_id": str(uuid.uuid4()),"name_length":2,**kw}

    def test_custom_favorites_are_private_idempotent_and_have_details(self):
        payload = {'姓名': '清和', '书名': '用户自定义', '现代释义': '清润平和',
                   '拼音带调': 'qīng hé', '男孩适配分': 60, '女孩适配分': 40}
        with patch('后端.自定义名字.补全自定义名字', return_value=payload), \
             patch('后端.小程序业务.分析姓名', return_value={'version': 'server-v1', 'analyzed_name': '清和'}), \
             patch('后端.小程序业务.逐字出处', return_value=[]):
            first = self.request('favorites.custom', {'name': '清和'}, user='custom-A')
            self.assertEqual(first.status_code, 200, first.text)
            id = first.json()['card']['id']
            self.assertEqual(self.request('favorites.custom', {'name': '清和'}, user='custom-A').json()['card']['id'], id)
            other = self.request('favorites.custom', {'name': '清和'}, user='custom-B')
            self.assertNotEqual(other.json()['card']['id'], id)
            self.assertEqual(self.request('names.detail', {'material_id': id}, user='custom-B').status_code, 404)
            self.assertEqual(self.request('names.detail', {'material_id': id}, user='custom-A').status_code, 200)
            self.assertEqual(self.request('shares.create', {'material_id': id, 'include_image': False}, user='custom-A').status_code, 404)
            favorites = self.request('favorites.list', user='custom-A').json()['cards']
            self.assertEqual([card['id'] for card in favorites], [id])
            self.assertEqual(favorites[0]['item']['书名'], '用户自定义')
            self.assertEqual(self.request('favorites.remove', {'material_id': id}, user='custom-A').status_code, 200)
            self.assertEqual(self.request('favorites.custom', {'name': '清和'}, user='custom-A').json()['card']['id'], id)
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM app_materials WHERE custom_owner IS NOT NULL').fetchone()['n'], 2)

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

    def test_recall_migration_is_repeatable_and_pending_years_use_only_era_name(self):
        migration = (ROOT / '后端/迁移/005_召回恢复.sql').read_text(encoding='utf-8')
        with self.connect() as c:
            before = c.execute('SELECT count(*) AS n FROM app_materials').fetchone()['n']
            c.execute(migration)
            c.execute(migration)
            self.assertEqual(c.execute('SELECT count(*) AS n FROM app_materials').fetchone()['n'], before)
            pending = c.execute("""SELECT p.text FROM passages p JOIN books b ON b.id=p.book_id
                WHERE b.name='东亚年号' AND p.status='待核验' AND p.active_for_recall LIMIT 1""").fetchone()
            self.assertIsNotNone(pending)
            items = 批量召回(资料查询(c), {'姓氏':'', '名字长度':1,
                '来源书名':'东亚年号', '随机种子':23}, 100)
            self.assertTrue(items)
            self.assertTrue(all(item['名字'] == item['原文'][item['原文位置']] for item in items))
            self.assertTrue(all(item['原文位置'] < item['原文'].find('：') if '：' in item['原文']
                else item['原文位置'] < item['原文'].find(':') for item in items))

    def test_two_sources_can_store_same_name_but_one_user_sees_it_once(self):
        with self.connect() as c:
            year = c.execute("""SELECT p.id FROM passages p JOIN books b ON b.id=p.book_id
                WHERE b.name='东亚年号' AND p.status='待核验' AND p.active_for_recall LIMIT 1""").fetchone()
            self.assertIsNotNone(year)
            original = c.execute("SELECT payload FROM app_materials WHERE profile_id=%s AND given_name='清和'",
                (self.double_profile,)).fetchone()['payload']
            second = c.execute("""INSERT INTO app_materials(profile_id,given_name,full_name,book,passage_id,payload)
                VALUES (%s,'清和','清和','东亚年号',%s,%s) RETURNING id""",
                (self.double_profile,year['id'],Jsonb(original))).fetchone()['id']
            self.assertIsInstance(second, int)
        names = []
        for _ in range(3):
            cards = self.request('feed.pull',self.pull(count=8),user='two-source-user')
            self.assertEqual(cards.status_code,200,cards.text)
            names.extend(card['item']['名字'] for card in cards.json()['cards'])
        self.assertEqual(len(names), len(set(names)))
        self.assertIn('清和', names, names)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT count(*) AS n FROM app_seen_names WHERE owner=%s AND given_name='清和'",
                (用户身份(APPID, 'two-source-user'),)).fetchone()['n'],1)

    def test_signature_replay_expiry_and_tampering(self):
        nonce = uuid.uuid4().hex
        self.assertEqual(self.request("session.get", nonce=nonce).status_code,200)
        self.assertEqual(self.request("session.get", nonce=nonce).status_code,409)
        self.assertEqual(self.request("session.get", timestamp=1000000000).status_code,401)
        self.assertEqual(self.request("session.get", tamper=True).status_code,401)
        self.assertEqual(self.client.post('/internal/v1/dispatch',json={}).status_code,401)
        self.assertEqual(self.client.post('/internal/v1/dispatch',content=b'x'*17000).status_code,413)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is not installed in the Python test image')
    def test_node_gateway_signature_matches_python_for_unicode_payload(self):
        body=json.dumps({'appid':APPID,'openid':'unicode-user','action':'feed.pull','data':self.pull()},ensure_ascii=False).encode()
        script="const fs=require('node:fs');const {signedHeaders}=require('./云函数/nameGateway/gateway');const body=fs.readFileSync(0);process.stdout.write(JSON.stringify(signedHeaders(body,process.env.GATEWAY_SECRET)));"
        result=subprocess.run(['node','-e',script],input=body,capture_output=True,check=True,cwd=ROOT)
        headers=json.loads(result.stdout)
        response=self.client.post('/internal/v1/dispatch',content=body,headers={k:str(v) for k,v in headers.items()})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['cards'])

    def test_identifier_bounds_are_rejected_before_database_queries(self):
        for value in (0, -1, "9223372036854775808", "9" * 100):
            cases = (("favorites.list", {"before_id": value}),
                     ("favorites.add", {"material_id": value}),
                     ("favorites.remove", {"material_id": value}),
                     ("favorites.compare", {"material_ids": [1, value]}),
                     ("feedback.save", {"material_id": value, "kind": "不喜欢"}))
            for action, data in cases:
                with self.subTest(action=action, value=value):
                    response = self.request(action, data)
                    self.assertEqual(response.status_code, 422, response.text)
        for cursor in (None, 1, 9223372036854775807):
            self.assertEqual(self.request("favorites.list", {"before_id": cursor}).status_code, 200)

    def test_idempotency_default_length_and_strict_parameters(self):
        data = self.pull(count=3)
        first = self.request("feed.pull",data)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(len(first.json()["cards"]),3)
        self.assertTrue(all(len(x["item"]["名字"])==2 for x in first.json()["cards"]))
        self.assertEqual(self.request("feed.pull",data).json(),first.json())
        self.assertEqual(self.request("feed.pull",{**data,"name_length":1}).status_code,409)
        legacy = self.request("feed.pull",self.pull(surname="李",required="清",excluded="和"),user="legacy-build")
        self.assertEqual(legacy.status_code,200,legacy.text)
        self.assertTrue(all(len(x["item"]["名字"])==2 for x in legacy.json()["cards"]))
        default = {"request_id":str(uuid.uuid4()),"count":2}
        response = self.request("feed.pull",default,user="default-length")
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(all(len(x["item"]["名字"])==2 for x in response.json()["cards"]))
        singles = self.request("feed.pull",self.pull(name_length=1,count=3),user="single-user").json()["cards"]
        self.assertTrue(all(len(x["item"]["名字"])==1 for x in singles))

    def test_concurrent_pulls_exactly_once_per_user(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _:self.request("feed.pull",self.pull(count=4)),range(4)))
        self.assertTrue(all(x.status_code==200 for x in results))
        names=[x["item"]["姓名"] for r in results for x in r.json()["cards"]]
        self.assertEqual(len(names),12)
        self.assertEqual(len(names),len(set(names)))

    def test_gender_filter_uses_model_scores_and_any_keeps_both(self):
        male = self.request("feed.pull", self.pull(gender="male", count=6), user="male-user").json()["cards"]
        female = self.request("feed.pull", self.pull(gender="female", count=6), user="female-user").json()["cards"]
        any_gender = self.request("feed.pull", self.pull(gender="any", count=8), user="any-user").json()["cards"]
        self.assertTrue(male)
        self.assertTrue(female)
        self.assertTrue(all(x["item"]["男孩适配分"] >= x["item"]["女孩适配分"] for x in male))
        self.assertTrue(all(x["item"]["女孩适配分"] >= x["item"]["男孩适配分"] for x in female))
        self.assertTrue(any(x["item"]["男孩适配分"] > x["item"]["女孩适配分"] for x in any_gender))
        self.assertTrue(any(x["item"]["女孩适配分"] > x["item"]["男孩适配分"] for x in any_gender))

    def test_low_score_stays_hidden_but_era_source_is_enabled_by_default(self):
        with self.connect() as c:
            low=c.execute("SELECT id FROM app_materials WHERE profile_id=%s ORDER BY id LIMIT 1",(self.double_profile,)).fetchone()['id']
            era=c.execute("SELECT id FROM app_materials WHERE profile_id=%s ORDER BY id OFFSET 1 LIMIT 1",(self.double_profile,)).fetchone()['id']
            c.execute("UPDATE app_materials SET payload=jsonb_set(payload,'{基础分}','80'::jsonb) WHERE id=%s",(low,))
            c.execute("UPDATE app_materials SET book='东亚年号' WHERE id=%s",(era,))
        cards=self.request('feed.pull',self.pull(count=8),user='quality-user').json()['cards']
        ids={x['id'] for x in cards}
        self.assertNotIn(low,ids)
        self.assertIn(era,ids)
        filtered=self.request('feed.pull',self.pull(count=8,excluded_sources=['东亚年号']),user='without-era').json()['cards']
        self.assertNotIn(era,{x['id'] for x in filtered})

    def test_catalog_lists_all_books_even_without_inventory_and_all_off_returns_empty(self):
        response = self.request('sources.list')
        self.assertEqual(response.status_code,200,response.text)
        sources = response.json()['sources']
        with self.connect() as c:
            names = {x['name'] for x in c.execute('SELECT DISTINCT name FROM books')}
        self.assertEqual({x['name'] for x in sources},names)
        self.assertIn({'name':'东亚年号','kind':'年号'},sources)
        self.assertTrue(all(set(x)=={'name','kind'} for x in sources))
        self.assertEqual(self.request('feed.pull',self.pull(excluded_sources=list(names))).json()['cards'],[])
        # Excluded rows were not marked as seen; relaxing settings still yields names.
        self.assertTrue(self.request('feed.pull',self.pull()).json()['cards'])

    def test_character_filters_are_all_required_any_excluded_and_ignore_surname(self):
        selected=self.request('feed.pull',self.pull(required='清',excluded='和',surname='李')).json()['cards']
        self.assertEqual([x['item']['名字'] for x in selected],['清清'])
        both=self.request('feed.pull',self.pull(required='和清'),user='both').json()['cards']
        self.assertEqual([x['item']['名字'] for x in both],['清和'])
        surname=self.request('feed.pull',self.pull(surname='李',required='李'),user='surname').json()['cards']
        self.assertEqual(surname,[])
        impossible=self.request('feed.pull',self.pull(name_length=1,required='清宁'),user='two-for-single')
        self.assertEqual(impossible.status_code,200)
        self.assertEqual(impossible.json()['cards'],[])
        no_avoid=self.request('feed.pull',self.pull(excluded='清远'),user='avoid').json()['cards']
        self.assertTrue(no_avoid)
        self.assertTrue(all(not set('清远') & set(x['item']['名字']) for x in no_avoid))

    def test_filtered_receipts_normalize_settings_but_reject_changed_conditions(self):
        data=self.pull(required='清和',excluded_sources=['东亚年号','楚辞'])
        first=self.request('feed.pull',data)
        self.assertEqual(first.status_code,200,first.text)
        replay=self.request('feed.pull',{**data,'required':'和清','excluded_sources':['楚辞','东亚年号','楚辞']})
        self.assertEqual(first.json(),replay.json())
        for changes in ({'required':'清'},{'excluded':'宁'},{'excluded_sources':[]}):
            self.assertEqual(self.request('feed.pull',{**data,**changes}).status_code,409)
        old=self.pull()
        receipt=self.request('feed.pull',old,user='old-receipt')
        self.assertEqual(self.request('feed.pull',{**old,'required':'','excluded':'','excluded_sources':[]},user='old-receipt').json(),receipt.json())

    def test_filter_validation_and_combination_with_gender_and_length(self):
        for invalid in ({'required':'清清宁'},{'excluded':'x%'},{'required':'清','excluded':'清'},
                        {'excluded_sources':[1]},{'excluded_sources':['']},{'excluded_sources':['诗经']*257}):
            self.assertEqual(self.request('feed.pull',self.pull(**invalid)).status_code,422,invalid)
        cards=self.request('feed.pull',self.pull(required='清',gender='male',name_length=1),user='combined').json()['cards']
        self.assertEqual(cards,[])  # 单字“清”在夹具中为女孩适配分更高。
        cards=self.request('feed.pull',self.pull(required='清',gender='female',name_length=1),user='combined').json()['cards']
        self.assertEqual([x['item']['名字'] for x in cards],['清'])

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

    def test_share_link_opens_for_another_user_and_can_be_saved_without_leaking_surname(self):
        card = self.request("feed.pull", self.pull(count=1, surname="李"), user="share-A").json()["cards"][0]
        material_id = card["id"]
        self.assertEqual(self.request("shares.create", {"material_id": material_id}, user="share-B").status_code, 404)
        issued = self.request("shares.create", {"material_id": material_id}, user="share-A")
        self.assertEqual(issued.status_code, 200, issued.text)
        token = issued.json()["token"]
        self.assertEqual(len(token), 32)
        self.assertTrue(issued.json()['image_url'].endswith(f'/share-card/{token}.jpg'))
        image = self.client.get(f'/share-card/{token}.jpg')
        self.assertEqual(image.status_code,200)
        self.assertEqual(image.headers['content-type'],'image/jpeg')
        import base64
        self.assertEqual(base64.b64decode(issued.json()['image_base64']), image.content)
        lightweight = self.request('shares.create', {'material_id': material_id, 'include_image': False}, user='share-A')
        self.assertEqual(lightweight.status_code, 200)
        self.assertEqual(lightweight.json()['token'], token)
        self.assertNotIn('image_base64', lightweight.json())
        self.assertEqual(self.client.get('/share-card/invalid.jpg').status_code,404)
        self.assertEqual(self.request("shares.create", {"material_id": material_id}, user="share-A").json()["token"], token)
        self.assertEqual(self.request("shares.get", {"token": "z" * 32}, user="share-B").status_code, 404)
        self.assertEqual(self.request("shares.get", {"token": "short"}, user="share-B").status_code, 422)
        opened = self.request("shares.get", {"token": token}, user="share-B")
        self.assertEqual(opened.status_code, 200, opened.text)
        self.assertEqual(opened.json()["card"]["item"]["姓名"], card["item"]["姓名"])
        full = self.request('shares.get', {'token': token, 'surname': '欧阳', 'include_image': False}, user='share-B')
        self.assertEqual(full.status_code, 200, full.text)
        self.assertEqual(full.json()['card']['item']['displayName'], '欧阳' + card['item']['姓名'])
        self.assertEqual(full.json()['card']['item']['wuxing']['analyzed_name'], '欧阳' + card['item']['姓名'])
        self.assertNotIn("李" + card["item"]["姓名"], opened.text)
        self.assertEqual(self.request("favorites.add", {"material_id": material_id}, user="share-B").status_code, 404)
        self.assertEqual(self.request("shares.save", {"token": token}, user="share-B").status_code, 200)
        self.assertEqual(self.request("shares.save", {"token": token}, user="share-B").status_code, 200)
        favorite = self.request("favorites.list", user="share-B").json()["cards"]
        self.assertEqual([item["id"] for item in favorite], [material_id])
        with self.connect() as c:
            owner = 用户身份(APPID, "share-B")
            self.assertEqual(c.execute("SELECT count(*) AS n FROM app_seen_names WHERE owner=%s AND given_name=%s",
                (owner, card["item"]["姓名"])).fetchone()["n"], 1)
            c.execute("UPDATE app_materials SET payload=jsonb_set(payload,'{基础分}','80'::jsonb) WHERE id=%s",
                      (material_id,))
        self.assertEqual(self.request("shares.get", {"token": token}, user="share-B").status_code, 404)
        self.assertEqual(self.client.get(f'/share-card/{token}.jpg').status_code,404)

    def test_share_keeps_the_exact_source_even_if_receiver_saw_the_same_name_elsewhere(self):
        migration = (ROOT / "后端/迁移/007_名字分享.sql").read_text(encoding="utf-8")
        with self.connect() as c:
            c.execute(migration)
            c.execute(migration)
        original = self.request("feed.pull", self.pull(count=1), user="source-A").json()["cards"][0]
        with self.connect() as c:
            base = c.execute("SELECT profile_id,given_name,book,passage_id,payload FROM app_materials WHERE id=%s",
                             (original["id"],)).fetchone()
            second = c.execute("""INSERT INTO app_materials(profile_id,given_name,full_name,book,passage_id,payload)
                VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                (base["profile_id"], base["given_name"], base["given_name"], "另一出处",
                 base["passage_id"], Jsonb(base["payload"]))).fetchone()["id"]
        self.request("feed.pull", self.pull(count=8), user="source-B")
        with self.connect() as c:
            owner = 用户身份(APPID, "source-B")
            c.execute("INSERT INTO app_deliveries(owner,full_name,material_id) VALUES (%s,%s,%s)",
                      (owner, base["given_name"], second))
        token = self.request("shares.create", {"material_id": original["id"]}, user="source-A").json()["token"]
        saved = self.request("shares.save", {"token": token}, user="source-B")
        self.assertEqual(saved.status_code, 200, saved.text)
        with self.connect() as c:
            owner = 用户身份(APPID, "source-B")
            ids = {row["material_id"] for row in c.execute("SELECT material_id FROM app_deliveries WHERE owner=%s", (owner,))}
            self.assertIn(original["id"], ids)
            self.assertIn(second, ids)

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
        response = self.client.put('/api/admin/profiles',headers={'X-Admin-Key':'test-admin-key-2026'},json={'name_length':2,'enabled':False})
        self.assertEqual(response.status_code,200,response.text)
        self.request('feed.pull',self.pull())
        with self.connect() as c:
            self.assertFalse(c.execute('SELECT enabled FROM app_profiles WHERE id=%s',(self.double_profile,)).fetchone()['enabled'])

    def test_worker_persists_inventory_and_budget_without_active_users(self):
        config=模型配置(地址='https://example.com/v1/chat/completions',密钥='test-only',模型='test')
        sequence = {1: iter(("澄", "晏", "昭")), 2: iter(("澄明", "晏清", "昭华"))}
        requested_lengths=[]
        seeds=set()
        def recall(_, request, __):
            if request['随机种子'] in seeds:
                return []
            seeds.add(request['随机种子'])
            requested_lengths.append(request['名字长度'])
            name=next(sequence[request['名字长度']])
            return [{"姓名":name,"名字":name,"书名":request['来源书名'],"篇章":self.passage['section_title'],
                "原文":self.passage['text'],"来源片段编号":self.passage['id'],"原文位置":0,
                "取字方式":"原文连取","出处核验状态":"已核验"}]
        def approve(items, request, config):
            return [{**x,'基础分':90,'现代释义':'结合古籍语境的测试释义','文化标签':['清朗'],
                '男孩适配分':55,'女孩适配分':45} for x in items]
        with patch.object(producer,'读取环境配置',return_value=config), patch.object(producer,'验证模型地址'), \
             patch.object(producer,'批量召回',side_effect=recall), patch.object(producer,'补充解释',side_effect=lambda _,items,__:items), \
             patch.object(producer,'模型筛选单批',side_effect=approve) as model:
            self.assertTrue(producer.生产一次())
            self.assertTrue(producer.生产一次())
            self.assertTrue(producer.生产一次())
            self.assertEqual(model.call_count,3)
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT batches FROM app_budget').fetchone()['batches'],3)
            self.assertGreater(c.execute('SELECT count(*) AS n FROM app_attempts').fetchone()['n'],0)
            stocks=c.execute("""SELECT p.name_length,count(m.id) AS n FROM app_profiles p
                LEFT JOIN app_materials m ON m.profile_id=p.id WHERE p.surname='' GROUP BY p.name_length""").fetchall()
            self.assertGreater(dict((x['name_length'],x['n']) for x in stocks)[1],6)
            self.assertGreater(dict((x['name_length'],x['n']) for x in stocks)[2],12)
            self.assertEqual(set(requested_lengths[:2]),{1,2})
            self.assertEqual(c.execute('SELECT count(*) AS n FROM app_users').fetchone()['n'],0)
            self.assertEqual(c.execute("SELECT count(*) AS n FROM app_materials WHERE payload ? '男孩适配分' AND payload ? '女孩适配分'").fetchone()['n'],21)

    def test_worker_failure_consumes_budget_but_can_retry_candidates(self):
        config=模型配置(地址='https://example.com/v1/chat/completions',密钥='test-only',模型='test')
        candidate={"姓名":"澄","名字":"澄","书名":self.passage['book'],"篇章":self.passage['section_title'],
            "原文":self.passage['text'],"来源片段编号":self.passage['id'],"原文位置":0,
            "取字方式":"原文连取","出处核验状态":"已核验"}
        with patch.object(producer,'读取环境配置',return_value=config),patch.object(producer,'验证模型地址'), \
             patch.object(producer,'批量召回',return_value=[candidate]), \
             patch.object(producer,'模型筛选单批',side_effect=RuntimeError('must-not-leak-secret')):
            self.assertFalse(producer.生产一次())
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT batches FROM app_budget').fetchone()['batches'],1)
            self.assertEqual(c.execute('SELECT count(*) AS n FROM app_attempts').fetchone()['n'],0)
            row=c.execute('SELECT failures,last_error,retry_at>now() AS delayed FROM app_source_progress').fetchone()
            self.assertEqual(row['failures'],1)
            self.assertTrue(row['delayed'])
            self.assertNotIn('secret',row['last_error'])

    def test_worker_prefers_new_then_retries_rejected_after_one_hour(self):
        book = self.passage['book']
        with self.connect() as c:
            c.execute('UPDATE app_profiles SET enabled=false WHERE id=%s', (self.double_profile,))
            c.execute("""INSERT INTO app_source_progress(profile_id,book,retry_at)
                SELECT %s,b.name,now()+interval '1 day' FROM books b WHERE b.name<>%s GROUP BY b.name""",
                (self.single_profile,book))
            c.execute("""INSERT INTO app_attempts(profile_id,book,given_name,last_attempt_at)
                VALUES (%s,%s,'晏','epoch')""", (self.single_profile,book))
        config=模型配置(地址='https://example.com/v1/chat/completions',密钥='test-only',模型='test')
        def candidate(name):
            return {'姓名':name,'名字':name,'书名':book,'篇章':self.passage['section_title'],
                '原文':self.passage['text'],'来源片段编号':self.passage['id'],
                '原文位置':0,'取字方式':'原文连取','出处核验状态':'已核验'}
        def recall(_, request, __):
            excluded = set(request['排除名字'])
            if '澄' not in excluded:
                return [candidate('澄')]
            if '晏' not in excluded:
                return [candidate('晏')]
            return []
        batches=[]
        def reject(items, *_):
            batches.append([x['名字'] for x in items])
            return []
        with patch.object(producer,'读取环境配置',return_value=config), patch.object(producer,'验证模型地址'), \
             patch.object(producer,'批量召回',side_effect=recall), patch.object(producer,'补充解释',side_effect=lambda _,items,__:items), \
             patch.object(producer,'模型筛选单批',side_effect=reject):
            self.assertTrue(producer.生产一次())
            self.assertEqual(batches[0], ['澄','晏'])
            self.assertFalse(producer.生产一次())
            self.assertEqual(len(batches),1)
            with self.connect() as c:
                c.execute("UPDATE app_attempts SET last_attempt_at=now()-interval '61 minutes' WHERE profile_id=%s AND book=%s",
                    (self.single_profile,book))
                c.execute("UPDATE app_source_progress SET retry_at=now() WHERE profile_id=%s AND book=%s",
                    (self.single_profile,book))
            self.assertTrue(producer.生产一次())
            self.assertEqual(len(batches),2)

    def test_model_call_limits_are_atomic_and_rolling(self):
        def reserve():
            with self.connect() as c:
                return producer.预留模型调用(c, (5000, 480, 4))
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: reserve(), range(8)))
        self.assertEqual(results.count(None), 4)
        self.assertEqual(results.count('30秒额度已用完'), 4)
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT batches FROM app_budget').fetchone()['batches'], 4)
            c.execute("UPDATE app_model_call_reservations SET reserved_at=now()-interval '31 seconds'")
            self.assertEqual(producer.预留模型调用(c, (5000, 4, 4)), '小时额度已用完')
            c.execute("UPDATE app_model_call_reservations SET reserved_at=now()-interval '61 minutes'")
            self.assertIsNone(producer.预留模型调用(c, (5, 480, 4)))
            self.assertEqual(producer.预留模型调用(c, (5, 480, 4)), '今日额度已用完')

    def test_producer_singleton_lock(self):
        with self.connect() as a,self.connect() as b:
            self.assertTrue(a.execute('SELECT pg_try_advisory_lock(%s) AS ok',(producer.生产锁,)).fetchone()['ok'])
            self.assertFalse(b.execute('SELECT pg_try_advisory_lock(%s) AS ok',(producer.生产锁,)).fetchone()['ok'])

    def test_shared_pool_upgrade_preserves_favorites_backfills_exposure_and_is_idempotent(self):
        schema = 'shared_pool_' + uuid.uuid4().hex
        migration_002 = (ROOT / '后端/迁移/002_小程序.sql').read_text(encoding='utf-8')
        with self.connect() as c, self.connect() as lock_connection:
            c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            c.commit()
            c.execute(sql.SQL('SET search_path TO {},public').format(sql.Identifier(schema)))
            c.execute(migration_002)
            legacy_profile = c.execute("INSERT INTO app_profiles(surname,name_length) VALUES ('李',2) RETURNING id").fetchone()['id']
            c.execute("INSERT INTO app_users(id) VALUES ('legacy-user')")
            payload = Jsonb({'姓名':'李清和','名字':'清和','书名':self.passage['book']})
            material = c.execute("""INSERT INTO app_materials(profile_id,given_name,full_name,book,passage_id,payload)
                VALUES (%s,'清和','李清和',%s,%s,%s) RETURNING id""",
                (legacy_profile,self.passage['book'],self.passage['id'],payload)).fetchone()['id']
            c.execute("INSERT INTO app_deliveries(owner,full_name,material_id) VALUES ('legacy-user','李清和',%s)",(material,))
            c.execute("INSERT INTO app_favorites(owner,material_id) VALUES ('legacy-user',%s)",(material,))
            c.commit()

            lock_connection.execute('SELECT pg_advisory_lock(%s)',(producer.生产锁,))
            with self.assertRaisesRegex(Exception,'Stop the inventory producer'):
                升级(c)
            self.assertIsNone(c.execute("SELECT to_regclass(%s) AS name",(schema+'.app_seen_names',)).fetchone()['name'])
            lock_connection.execute('SELECT pg_advisory_unlock(%s)',(producer.生产锁,))

            rows=升级(c)
            self.assertEqual([x['name_length'] for x in rows],[1,2])
            self.assertFalse(c.execute("SELECT enabled FROM app_profiles WHERE id=%s",(legacy_profile,)).fetchone()['enabled'])
            self.assertEqual(c.execute("SELECT count(*) AS n FROM app_favorites").fetchone()['n'],1)
            self.assertEqual(c.execute("SELECT given_name FROM app_seen_names WHERE owner='legacy-user'").fetchone()['given_name'],'清和')
            c.execute("UPDATE app_profiles SET enabled=false WHERE surname='' AND name_length=1")
            c.commit()
            升级(c)
            self.assertFalse(c.execute("SELECT enabled FROM app_profiles WHERE surname='' AND name_length=1").fetchone()['enabled'])
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

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
        self.assertIn('name_inventory_total 18',r.text)


if __name__ == '__main__':
    unittest.main()
