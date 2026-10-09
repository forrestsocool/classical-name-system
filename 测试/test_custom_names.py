import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from 后端 import 自定义名字 as enrich, 小程序业务 as service
from 后端.模型接口 import 模型配置


class CustomNameTests(unittest.TestCase):
    def test_validation(self):
        for name in ('', 'abc', '清和安', '清 和', '<清>'):
            with self.assertRaises(ValueError):
                service.自定义名字参数(name=name)
        self.assertEqual(service.自定义名字参数(name='清和').name, '清和')

    def test_enrichment_preserves_source_and_normalizes_scores(self):
        output = {'释义': '清润平和，寓意从容。', '拼音带调': 'qīng hé', '男孩适配分': 80, '女孩适配分': 40}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {'choices': [{'message': {'content': json.dumps(output)}}]}).encode()
        opener = MagicMock()
        opener.open.return_value = response
        config = 模型配置(地址='https://example.com/api', 密钥='test-only', 模型='test')
        with patch.object(enrich, '读取环境配置', return_value=config), \
             patch.object(enrich, '验证模型地址'), \
             patch.object(enrich.urllib.request, 'build_opener', return_value=opener), \
             patch.object(enrich, '分析姓名', return_value={'analyzed_name': '清和'}):
            result = enrich.补全自定义名字('清和')
        self.assertEqual(result['姓名'], '清和')
        self.assertEqual(result['书名'], '用户自定义')
        self.assertEqual(result['原文'], '')
        self.assertEqual(result['男孩适配分'] + result['女孩适配分'], 100)
        self.assertEqual(result['wuxing']['analyzed_name'], '清和')
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 12)

    def test_model_failure_hides_internal_error(self):
        config = 模型配置(地址='https://example.com/api', 密钥='secret', 模型='test')
        with patch.object(enrich, '读取环境配置', return_value=config), \
             patch.object(enrich, '验证模型地址'), \
             patch.object(enrich.urllib.request, 'build_opener', side_effect=ValueError('secret')):
            with self.assertRaisesRegex(RuntimeError, '^名字信息补全失败，请稍后重试$'):
                enrich.补全自定义名字('清和')

    def test_repeat_reuses_private_material_and_restores_favorite(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchone.return_value = {'id': 123, 'payload': {'姓名': '清和', '书名': '用户自定义'}}
        with patch.object(service, '连接数据库', return_value=connection), \
             patch.object(service, '分析姓名', return_value={}), \
             patch.object(enrich, '补全自定义名字') as model:
            result = service.自定义收藏('user-A', service.自定义名字参数(name='清和'))
        model.assert_not_called()
        self.assertEqual(result['card']['id'], 123)
        first = connection.execute.call_args_list[0]
        self.assertIn('custom_owner=%s', first.args[0])
        self.assertEqual(first.args[1], ('user-A', '清和'))
        self.assertTrue(any('INSERT INTO app_favorites' in call.args[0] for call in connection.execute.call_args_list))

    def test_failed_enrichment_does_not_insert_material(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchone.return_value = None
        with patch.object(service, '连接数据库', return_value=connection), \
             patch('后端.持续生产.预留模型调用', return_value=None), \
             patch.object(enrich, '补全自定义名字', side_effect=RuntimeError('secret')):
            with self.assertRaises(HTTPException) as caught:
                service.自定义收藏('user-A', service.自定义名字参数(name='清和'))
        self.assertEqual(caught.exception.status_code, 503)
        self.assertFalse(any('INSERT INTO app_materials' in call.args[0] for call in connection.execute.call_args_list))

    def test_success_writes_owned_material_delivery_and_favorite(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        row = {'id': 321, 'payload': {'姓名': '清和', '书名': '用户自定义'}}
        connection.execute.return_value.fetchone.side_effect = [None, row]
        with patch.object(service, '连接数据库', return_value=connection), \
             patch('后端.持续生产.预留模型调用', return_value=None), \
             patch.object(service, '分析姓名', return_value={}), \
             patch.object(enrich, '补全自定义名字', return_value=row['payload']):
            result = service.自定义收藏('user-A', service.自定义名字参数(name='清和'))
        self.assertEqual(result['card']['id'], 321)
        writes = connection.execute.call_args_list
        insert = next(call for call in writes if 'INSERT INTO app_materials' in call.args[0])
        self.assertEqual(insert.args[1][-1], 'user-A')
        for table in ('app_seen_names', 'app_deliveries', 'app_favorites'):
            call = next(call for call in writes if 'INSERT INTO ' + table in call.args[0])
            self.assertEqual(call.args[1][0], 'user-A')

    def test_quota_blocks_enrichment_before_network_call(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchone.return_value = None
        with patch.object(service, '连接数据库', return_value=connection), \
             patch('后端.持续生产.预留模型调用', return_value='额度已用完'), \
             patch.object(enrich, '补全自定义名字') as model:
            with self.assertRaises(HTTPException) as caught:
                service.自定义收藏('user-A', service.自定义名字参数(name='清和'))
        self.assertEqual(caught.exception.status_code, 429)
        model.assert_not_called()
