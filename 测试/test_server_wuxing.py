import unittest
from unittest.mock import patch

from fastapi import HTTPException

from 后端 import 小程序业务
from 后端.姓名五行 import 分析姓名, 逐字出处, 知识库
from 后端 import 姓名五行


class ServerWuxingTests(unittest.TestCase):
    def test_character_uses_explicit_element_or_profile_dominant_without_claiming_source(self):
        corpus = {
            '清': {'energy_profile': {'supported': True, 'scores': {'金': 1, '木': 2, '水': 70, '火': 3, '土': 4}}},
            '熙': {'element': '火', 'energy_profile': {'supported': True, 'scores': {'金': 1, '木': 2, '水': 3, '火': 60, '土': 4}}},
        }
        with patch.object(姓名五行, '知识库', return_value=(corpus, 'digest')):
            rows = 逐字出处('清熙未')
            explanation = 分析姓名('清熙未')['explanation']
        self.assertEqual(len(rows), 3)
        self.assertEqual((rows[0]['display_element'], rows[0]['element_basis'], rows[0]['emoji']), ('水', '主象', '💧'))
        self.assertEqual((rows[1]['display_element'], rows[1]['element_basis'], rows[1]['emoji']), ('火', '字源', '🔥'))
        self.assertEqual(rows[2]['display_element'], '')
        self.assertIn('清·水（主象）', explanation)
        self.assertIn('熙·火（字源）', explanation)
        self.assertNotIn('字源归类', explanation)

    def test_overlay_loaded_and_each_dimension_summed_then_capped(self):
        merged, _ = 知识库()
        self.assertTrue(merged['鸿']['energy_profile']['supported'])
        self.assertTrue(merged['李']['energy_profile']['supported'])
        for name in ('李', '李李', '杨鸿渐', '欧阳嘉宁'):
            result = 分析姓名(name)
            self.assertEqual(result['analyzed_name'], name)
            for row in result['items']:
                label = row['label']
                raw = sum((merged[ch].get('energy_profile') or {}).get('scores', {}).get(label, 0)
                          for ch in name if ch in merged and (merged[ch].get('energy_profile') or {}).get('supported'))
                self.assertEqual(row['percent'], min(100, round(raw)), (name, label))
        self.assertGreater(sum(x['percent'] for x in 分析姓名('李李')['items']), 100)

    def test_partial_coverage_and_character_source_order(self):
        result = 分析姓名('李𠮷')
        self.assertEqual(result['supported'], 1)
        self.assertIn('𠮷', result['status'] + result['explanation'])
        self.assertEqual([x['id'] for x in 逐字出处('李李')], [0, 1])
        self.assertEqual(逐字出处('李')[0]['citations'][0]['book'], '说文解字')

    def test_cannot_query_undelivered_names_or_arbitrary_text(self):
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def execute(self, query, params):
                self.query, self.params = query, params
                return self
            def fetchall(self): return []
        with patch.object(小程序业务, '连接数据库', return_value=Cursor()):
            with self.assertRaises(HTTPException) as caught:
                小程序业务.姓名详情('owner', 小程序业务.姓名详情参数(material_id=1, surname='李'))
            self.assertEqual(caught.exception.status_code, 404)
        with self.assertRaises(ValueError):
            小程序业务.姓名分析参数(material_ids=[1], surname='abc')
        with self.assertRaises(ValueError):
            小程序业务.姓名分析参数(material_ids=[1,2,3])

    def test_distinct_surname_quota_blocks_bulk_character_enumeration(self):
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def execute(self, query, params):
                self.query = query
                return self
            def fetchone(self):
                if 'count(*)' in self.query:
                    return {'n': 16}
                return None
        with patch.object(小程序业务, '连接数据库', return_value=Cursor()):
            with self.assertRaises(HTTPException) as caught:
                小程序业务.记录姓氏('owner', '欧阳')
            self.assertEqual(caught.exception.status_code, 429)

    def test_favorites_do_not_bulk_return_five_element_profiles(self):
        row = {'id': 1, 'payload': {'姓名': '李', '现代释义': '示例', '五行匹配': {'李': '火'}}}
        card = 小程序业务.卡片(row)
        self.assertNotIn('wuxing', card['item'])
        self.assertNotIn('五行匹配', card['item'])
        self.assertIn('wuxing', 小程序业务.卡片(row, include_wuxing=True)['item'])


if __name__ == '__main__':
    unittest.main()
