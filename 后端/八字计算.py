from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lunar_python import Solar


规则版本 = "八字规则0.2"
五行 = ("金", "木", "水", "火", "土")
天干五行 = {
    "甲": "木",
    "乙": "木",
    "丙": "火",
    "丁": "火",
    "戊": "土",
    "己": "土",
    "庚": "金",
    "辛": "金",
    "壬": "水",
    "癸": "水",
}


def 本地时间(时间: datetime, 时区: str) -> datetime:
    try:
        目标时区 = ZoneInfo(时区)
    except ZoneInfoNotFoundError as 异常:
        raise ValueError(f"不支持的时区：{时区}") from 异常
    if 时间.tzinfo is None:
        本地 = 时间.replace(tzinfo=目标时区)
        回转 = 本地.astimezone(timezone.utc).astimezone(目标时区).replace(tzinfo=None)
        if 回转 != 时间:
            raise ValueError("出生时间落在夏令时跳过区间，请核对当地时间")
        if 本地.utcoffset() != 本地.replace(fold=1).utcoffset():
            raise ValueError("出生时间存在夏令时重复，请提供带时区偏移的时间")
        return 本地
    return 时间.astimezone(目标时区)


def 柱信息(四柱, 名称: str) -> dict:
    天干 = getattr(四柱, f"get{名称}Gan")()
    地支 = getattr(四柱, f"get{名称}Zhi")()
    五行值 = getattr(四柱, f"get{名称}WuXing")()
    藏干 = getattr(四柱, f"get{名称}HideGan")()
    return {
        "柱": getattr(四柱, f"get{名称}")(),
        "天干": 天干,
        "地支": 地支,
        "五行": 五行值,
        "藏干": 藏干,
    }


def 计算五行(柱列表: list[dict]) -> dict:
    明显 = Counter()
    藏干 = Counter()
    for 柱 in 柱列表:
        for 元素 in 柱["五行"]:
            if 元素 in 五行:
                明显[元素] += 1
        for 天干 in 柱["藏干"]:
            元素 = 天干五行.get(天干)
            if 元素:
                藏干[元素] += 1
    return {
        "明干支": {元素: 明显[元素] for 元素 in 五行},
        "藏干": {元素: 藏干[元素] for 元素 in 五行},
    }


def 计算八字(
    时间: datetime,
    时区: str = "Asia/Shanghai",
    日界规则: str = "子初",
) -> dict:
    if 日界规则 not in {"子初", "午夜"}:
        raise ValueError("日界规则只能是子初或午夜")
    本地 = 本地时间(时间, 时区)
    if not 1900 <= 本地.year <= 2100:
        raise ValueError("当前历法模块支持1900年至2100年")
    太阳历 = Solar.fromYmdHms(
        本地.year,
        本地.month,
        本地.day,
        本地.hour,
        本地.minute,
        本地.second,
    )
    农历 = 太阳历.getLunar()
    四柱 = 农历.getEightChar()
    四柱.setSect(1 if 日界规则 == "子初" else 2)
    # 历法库的节气时刻使用北京时间，年柱、月柱按同一个绝对时刻计算。
    节气本地 = 本地.astimezone(timezone(timedelta(hours=8)))
    节气四柱 = Solar.fromYmdHms(
        节气本地.year, 节气本地.month, 节气本地.day,
        节气本地.hour, 节气本地.minute, 节气本地.second,
    ).getLunar().getEightChar()
    柱列表 = [
        柱信息(节气四柱, "Year"),
        柱信息(节气四柱, "Month"),
        柱信息(四柱, "Day"),
        柱信息(四柱, "Time"),
    ]
    return {
        "规则版本": f"{规则版本}-北京时间节气-当地{'子初' if 日界规则 == '子初' else '午夜'}换日",
        "输入时间": 时间.isoformat(),
        "计算本地时间": 本地.isoformat(),
        "时区": 时区,
        "日界规则": 日界规则,
        "农历日期": {
            "年": 农历.getYear(),
            "月": 农历.getMonth(),
            "日": 农历.getDay(),
        },
        "四柱": [柱["柱"] for 柱 in 柱列表],
        "柱详情": 柱列表,
        "五行统计": 计算五行(柱列表),
        "日主": 四柱.getDayGan(),
    }
