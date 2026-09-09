from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from time import monotonic


class TTL缓存:
    def __init__(self, 有效秒数: int = 60, 最大数量: int = 128) -> None:
        self.有效秒数 = max(1, 有效秒数)
        self.最大数量 = max(1, 最大数量)
        self._数据: OrderedDict[object, tuple[float, object]] = OrderedDict()
        self._锁 = RLock()

    def 读取(self, 键: object):
        当前时间 = monotonic()
        with self._锁:
            项目 = self._数据.get(键)
            if 项目 is None:
                return None
            到期时间, 内容 = 项目
            if 到期时间 <= 当前时间:
                self._数据.pop(键, None)
                return None
            self._数据.move_to_end(键)
            return deepcopy(内容)

    def 写入(self, 键: object, 内容: object) -> None:
        with self._锁:
            self._数据[键] = (monotonic() + self.有效秒数, deepcopy(内容))
            self._数据.move_to_end(键)
            while len(self._数据) > self.最大数量:
                self._数据.popitem(last=False)

    def 删除(self, 键: object) -> None:
        with self._锁:
            self._数据.pop(键, None)

    def 清空(self) -> None:
        with self._锁:
            self._数据.clear()

    def 数量(self) -> int:
        with self._锁:
            return len(self._数据)
