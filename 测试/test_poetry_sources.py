import os
import tempfile
import unittest
from pathlib import Path
from shutil import copytree

from 脚本.导入诗词来源 import CORPUS, 读取诗词资料
from 后端.智能筛选 import 可召回正文


class PoetrySourcesTests(unittest.TestCase):
    def test_both_collections_have_real_text_and_author_title(self):
        collections = 读取诗词资料()
        self.assertEqual([(x['name'],x['poems']) for x in collections], [('唐诗',366),('宋词',280)])
        for collection in collections:
            self.assertGreaterEqual(len(collection['passages']),collection['poems'])
            for passage in collection['passages']:
                self.assertIn('·',passage['篇章'])
                self.assertNotEqual(passage['篇章'],'全文')
                self.assertEqual(passage['状态'],'待核验')
                self.assertEqual(passage['可用于生成'],0)
                self.assertTrue(可召回正文({'text':passage['正文'],'book':collection['name'],
                    'active_for_recall':True,'status':'待核验','can_generate':0}))
        text = ''.join(x['正文'] for x in collections[0]['passages'])
        self.assertIn('明月松间照',text)
        self.assertIn('清泉石上流',text)

    def test_changed_text_cannot_reuse_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            copytree(CORPUS / '诗词来源', target / '诗词来源')
            (target / '古籍全文').mkdir()
            for name in ('唐诗','宋词'):
                source = CORPUS / '古籍全文' / (name+'.txt')
                (target / '古籍全文' / source.name).write_bytes(source.read_bytes())
            with (target / '古籍全文/唐诗.txt').open('a',encoding='utf-8') as file:
                file.write('改动')
            with self.assertRaisesRegex(ValueError,'哈希'):
                读取诗词资料(target)

    @unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), '需要本地 PostgreSQL 测试库')
    def test_import_is_transactional_idempotent_and_recallable(self):
        import uuid
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from 后端.数据库 import 初始化数据库, 资料查询
        from 后端.智能筛选 import 批量召回
        from 脚本.导入诗词来源 import 导入
        schema = 'poetry_test_' + uuid.uuid4().hex
        with psycopg.connect(os.environ['TEST_DATABASE_URL'], autocommit=True,row_factory=dict_row) as connection:
            connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            try:
                connection.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
                初始化数据库(connection)
                导入(connection)
                self.assertEqual(connection.execute('SELECT count(*) AS n FROM books').fetchone()['n'],0)
                first = 导入(connection,apply=True)
                self.assertGreater(sum(x['inserted_passages'] for x in first['sources']),600)
                second = 导入(connection,apply=True)
                self.assertEqual(sum(x['inserted_passages'] for x in second['sources']),0)
                for name in ('唐诗','宋词'):
                    candidates = 批量召回(资料查询(connection),{'来源书名':name,'姓氏':'','名字长度':2,'随机种子':42},25)
                    self.assertTrue(candidates)
                    self.assertTrue(all(x['书名']==name for x in candidates))
            finally:
                connection.execute('SET search_path TO public')
                connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    unittest.main()
