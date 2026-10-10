import unittest
from unittest.mock import MagicMock, patch

from 后端 import 数据库, 小程序业务, 网关鉴权


class DispatchPerformanceTests(unittest.TestCase):
    def test_only_request_path_uses_pool(self):
        pool = MagicMock()
        with patch.dict('os.environ', {'DATABASE_URL': 'postgresql://test/test'}), \
             patch.object(数据库, '_获取连接池', return_value=pool), \
             patch.object(数据库.psycopg, 'connect') as direct:
            数据库.连接数据库()
            direct.assert_called_once()
            pool.connection.assert_not_called()
            with 数据库.使用请求连接池():
                self.assertIs(数据库.连接数据库(), pool.connection.return_value)
            数据库.连接数据库()
            self.assertEqual(direct.call_count, 2)
            pool.connection.assert_called_once()

    def test_expired_nonces_are_not_deleted_on_every_request(self):
        cursor = MagicMock()
        with patch.object(网关鉴权, '_下次清理', 0), \
             patch.object(网关鉴权.time, 'monotonic', side_effect=[100, 110, 401]):
            for _ in range(3):
                网关鉴权._清理过期随机数(cursor)
        self.assertEqual(cursor.execute.call_count, 2)

    def test_favorite_list_uses_owner_material_index_and_cursor(self):
        cursor = MagicMock()
        cursor.execute.return_value.fetchall.return_value = []
        with patch.object(小程序业务, '连接数据库') as connect:
            connect.return_value.__enter__.return_value = cursor
            小程序业务.收藏列表('owner', 小程序业务.列表参数())
            query, params = cursor.execute.call_args.args
            self.assertNotIn('material_id<', query)
            self.assertEqual(params, ['owner'])
            小程序业务.收藏列表('owner', 小程序业务.列表参数(before_id=42))
            query, params = cursor.execute.call_args.args
            self.assertIn('f.material_id<%s', query)
            self.assertIn('ORDER BY f.material_id DESC', query)
            self.assertEqual(params, ['owner', 42])

    def test_repeated_surname_analysis_uses_one_connection_without_user_lock(self):
        cursor = MagicMock()
        cursor.execute.return_value.fetchall.return_value = [{'id': 1, 'given_name': '清熙'}]
        cursor.execute.return_value.fetchone.return_value = {'?column?': 1}
        with patch.object(小程序业务, '连接数据库') as connect, \
             patch.object(小程序业务, '分析姓名', return_value={'available': True}):
            connect.return_value.__enter__.return_value = cursor
            result = 小程序业务.姓名分析('owner', 小程序业务.姓名分析参数(material_ids=[1], surname='李'))
        self.assertEqual(connect.call_count, 1)
        self.assertEqual(result['results'][0]['wuxing'], {'available': True})
        queries = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(len(queries), 2)
        self.assertFalse(any('FOR UPDATE' in query for query in queries))

    def test_new_surname_still_locks_and_rechecks_quota(self):
        cursor = MagicMock()
        cursor.execute.return_value.fetchone.side_effect = [None, None, {'n': 15}]
        with patch.object(小程序业务, '连接数据库') as connect:
            connect.return_value.__enter__.return_value = cursor
            小程序业务.记录姓氏('owner', '李')
        self.assertEqual(connect.call_count, 1)
        queries = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(len(queries), 5)
        self.assertIn('FOR UPDATE', queries[1])
        self.assertIn('INSERT INTO app_surname_queries', queries[-1])


if __name__ == '__main__':
    unittest.main()
