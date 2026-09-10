from __future__ import annotations

import random
import re
import sqlite3
from .名字校验 import 满足约束


中文串正则 = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def 取得关键词(连接: sqlite3.Connection, 方向: list[str]) -> set[str]:
    if not 方向:
        return set()
    占位符 = ",".join("?" for _ in 方向)
    查询 = f"""
        SELECT DISTINCT k.keyword
        FROM direction_keywords k
        JOIN directions d ON d.id = k.direction_id
        WHERE d.name IN ({占位符})
    """
    return {行[0] for 行 in 连接.execute(查询, 方向).fetchall()}


def 取得五行(连接: sqlite3.Connection, 名字: str) -> tuple[dict[str, str], list[str]]:
    已知: dict[str, str] = {}
    未知 = []
    for 字符 in 名字:
        行 = 连接.execute(
            """
            SELECT element FROM character_elements
            WHERE char = ? AND status = '已核验'
            ORDER BY method LIMIT 1
            """,
            (字符,),
        ).fetchone()
        if 行 is None:
            未知.append(字符)
        else:
            已知[字符] = 行[0]
    return 已知, 未知


def 取得读音(连接: sqlite3.Connection, 名字: str) -> tuple[str, str]:
    结果 = []
    声调结果 = []
    for 字符 in 名字:
        行 = 连接.execute(
            "SELECT pinyin, pinyin_tone FROM characters WHERE char = ?",
            (字符,),
        ).fetchone()
        if 行 is None:
            结果.append("")
            声调结果.append("")
        else:
            结果.append(行[0])
            声调结果.append(行[1])
    return " ".join(结果), " ".join(声调结果)


def 提取名字(正文: str, 名字长度: int) -> list[str]:
    结果 = []
    for 中文段 in 中文串正则.findall(正文):
        if 名字长度 == 1:
            结果.extend(中文段)
        else:
            结果.extend(
                中文段[位置 : 位置 + 名字长度]
                for 位置 in range(0, len(中文段) - 名字长度 + 1)
            )
    return 结果


def 生成基础候选(
    连接: sqlite3.Connection,
    姓氏: str,
    名字长度: int,
    方向: list[str],
    必须包含: str,
    避用字: str,
    关键词: str,
    随机种子: int | None,
    五行偏好: list[str] | None = None,
    数量: int = 12,
    排除名字: list[str] | None = None,
) -> list[dict]:
    方向关键词 = 取得关键词(连接, 方向)
    用户关键词 = set(关键词)
    五行偏好 = 五行偏好 or []
    排除名字集合 = set(排除名字 or [])
    过滤字 = set(避用字)
    查询 = """
        SELECT p.id, p.text, p.section_title, b.name AS book,
               cp.phrase, cp.source_offset, cp.origin_type, cp.quality_score,
               cp.direction
        FROM candidate_phrases cp
        JOIN passages p ON p.id = cp.passage_id
        JOIN books b ON b.id = p.book_id
        WHERE p.can_generate = 1 AND cp.status = '已核验'
        ORDER BY cp.quality_score DESC, cp.id
    """
    候选: dict[str, dict] = {}
    来源行 = []
    for 原行 in 连接.execute(查询):
        if 名字长度 == 1 and 原行["origin_type"] == "原文连取":
            for 偏移, 字 in enumerate(原行["phrase"]):
                行 = dict(原行)
                行["phrase"] = 字
                行["source_offset"] += 偏移
                来源行.append(行)
        else:
            来源行.append(原行)
    # 已核验片段是第二层候选池，避免少量人工精选词组耗尽后无法换一批。
    # 分数低于人工精选词组，仍然经过同样的出处、字形和用户约束校验。
    if 名字长度 in {1, 2}:
        补充查询 = """
            SELECT p.id, p.text, p.section_title, b.name AS book,
                   p.id AS source_offset, '原文连取' AS origin_type,
                   45 AS quality_score, '资料检索' AS direction
            FROM passages p
            JOIN books b ON b.id = p.book_id
            WHERE p.can_generate = 1
            ORDER BY p.id
        """
        for 原行 in 连接.execute(补充查询):
            正文 = 原行["text"]
            for 中文段匹配 in 中文串正则.finditer(正文):
                中文段 = 中文段匹配.group(0)
                for 偏移 in range(0, len(中文段) - 名字长度 + 1):
                    行 = dict(原行)
                    行["phrase"] = 中文段[偏移 : 偏移 + 名字长度]
                    行["source_offset"] = 中文段匹配.start() + 偏移
                    来源行.append(行)
    for 行 in 来源行:
        名字 = 行["phrase"]
        if not 满足约束(名字, {"姓氏": 姓氏, "名字长度": 名字长度, "必须包含": 必须包含, "避用字": 避用字, "排除名字": 排除名字 or []}):
            continue
        if 行["origin_type"] == "原文连取" and 行["text"][行["source_offset"]:行["source_offset"] + len(名字)] != 名字:
            continue
        if 名字 in 排除名字集合 or 姓氏 + 名字 in 排除名字集合:
            continue
        if len(名字) != 名字长度:
            continue
        if 必须包含 and not all(字 in 名字 for 字 in 必须包含):
            continue
        if any(字 in 名字 for 字 in 过滤字):
            continue
        评分 = 行["quality_score"]
        评分 += 3 * sum(字 in 方向关键词 for 字 in 名字)
        评分 += 2 * sum(字 in 用户关键词 for 字 in 名字)
        评分 += 1 if 名字[0] in 方向关键词 or 名字[-1] in 方向关键词 else 0
        已知五行, 未知五行 = 取得五行(连接, 名字)
        拼音, 拼音带调 = 取得读音(连接, 名字)
        评分 += 5 * sum(元素 in 五行偏好 for 元素 in 已知五行.values())
        项目 = {
            "姓名": 姓氏 + 名字,
            "名字": 名字,
            "拼音": 拼音,
            "拼音带调": 拼音带调,
            "书名": 行["book"],
            "篇章": 行["section_title"],
            "原文": 行["text"],
            "取字方式": 行["origin_type"],
            "来源片段编号": 行["id"],
            "原文位置": 行["source_offset"],
            "方向": 行["direction"],
            "五行匹配": {
                "偏好": 五行偏好,
                "已知字符": 已知五行,
                "未知字符": 未知五行,
            },
            "基础分": 评分,
        }
        旧项目 = 候选.get(名字)
        if 旧项目 is None or 项目["基础分"] > 旧项目["基础分"]:
            候选[名字] = 项目

    随机 = random.Random(随机种子)
    分组: dict[int, list[dict]] = {}
    for 项目 in 候选.values():
        分组.setdefault(项目["基础分"], []).append(项目)
    排序结果 = []
    for 分数 in sorted(分组, reverse=True):
        组 = 分组[分数]
        随机.shuffle(组)
        排序结果.extend(组)
    return 排序结果[:数量]
