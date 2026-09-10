from collections import Counter
import re

汉字正则 = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]{1,2}")


def 满足约束(名字: str, 请求: dict) -> bool:
    固定字 = Counter(请求.get("必须包含", ""))
    排除 = set(请求.get("排除名字", []))
    return bool(
        汉字正则.fullmatch(名字)
        and len(名字) == 请求.get("名字长度", 2)
        and not (固定字 - Counter(名字))
        and not (set(名字) & set(请求.get("避用字", "")))
        and 名字 not in 排除
        and 请求.get("姓氏", "") + 名字 not in 排除
    )


def 取字位置(名字: str, 正文: str, 方式: str) -> list[int] | None:
    if 方式 == "意境延展":
        return []
    if 方式 == "原文连取":
        起点 = 正文.find(名字)
        return list(range(起点, 起点 + len(名字))) if 起点 >= 0 else None
    句号 = []
    当前句 = 0
    for 字 in 正文:
        句号.append(当前句)
        当前句 += 字 in "。！？!?；;\n"
    def 搜索(索引, 已取):
        if 索引 == len(名字):
            同句 = len({句号[位置] for 位置 in 已取}) == 1
            return 已取 if (同句 if 方式 == "同句取字" else not 同句) else None
        for 位置, 字 in enumerate(正文):
            if 字 == 名字[索引] and 位置 not in 已取:
                结果 = 搜索(索引 + 1, 已取 + [位置])
                if 结果 is not None:
                    return 结果
        return None
    return 搜索(0, [])
