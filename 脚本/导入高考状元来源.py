"""Import the normalized 1996--2026 gaokao champion name source.

The source is intentionally kept as a separate, non-model-produced pool.  It
uses the shared empty-surname profiles, so the app can apply the user's
surname at display time while preserving the original champion name and its
year/province/subject metadata in the payload.

Default mode is a dry run.  Before ``--apply`` stop the producer and take a
PostgreSQL backup.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pypinyin import Style, lazy_pinyin, pinyin
from psycopg.types.json import Jsonb

from 后端.数据库 import 连接数据库

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "gaokao_top_rankings_1996_2026" / "data" / "gaokao_champions_1996_2026.json"
BOOK_NAME = "历年高考状元"
SOURCE_TYPE = "高考状元"


def 读取高考资料(path: Path = DATA) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    manifest = data.get("manifest") or {}
    rows = data.get("rows") or []
    if manifest.get("year_start") != 1996 or manifest.get("year_end") != 2026:
        raise ValueError("高考资料年份范围不是 1996—2026")
    if "文科" not in manifest.get("subjects", []) or "理科" not in manifest.get("subjects", []):
        raise ValueError("高考资料缺少文科或理科类别")
    required = {"year", "province", "subject", "full_name", "given_name", "school", "source_line"}
    for row in rows:
        if not required <= row.keys():
            raise ValueError("高考资料字段不完整")
        if not row["subject"] or not 1996 <= int(row["year"]) <= 2026:
            raise ValueError("高考资料含有范围外的记录")
        if not row["given_name"] or len(row["given_name"]) not in {1, 2}:
            raise ValueError("高考资料含有不支持的名字长度")
    if len(rows) != manifest.get("accepted_rows"):
        raise ValueError("高考资料清单数量不一致")
    return data


def _pinyin(name: str) -> tuple[str, str]:
    return " ".join(lazy_pinyin(name)), " ".join(pinyin(name, style=Style.TONE3, heteronym=False)[i][0] for i in range(len(name)))


def _text(row: dict) -> str:
    school = f"；学校：{row['school']}" if row.get("school") else ""
    score = f"；分数：{row['score']}" if row.get("score") is not None else ""
    return f"{row['year']}年，{row['province']}{row['subject']}高考状元：{row['full_name']}{school}{score}。"


def _section(row: dict) -> str:
    return f"{row['year']}·{row['province']}·{row['subject']}·{row['full_name']}"


def _payload(given_name: str, row: dict, passage_id: int, related: list[dict]) -> dict:
    plain, toned = _pinyin(given_name)
    source_items = [{
        "year": x["year"], "province": x["province"], "subject": x["subject"],
        "full_name": x["full_name"], "school": x.get("school", ""), "score": x.get("score"),
    } for x in related]
    first = source_items[0]
    return {
        "姓名": given_name,
        "名字": given_name,
        "拼音": plain,
        "拼音带调": toned,
        "书名": BOOK_NAME,
        "篇章": _section(row),
        "原文": _text(row),
        "取字方式": "高考状元名录",
        "来源片段编号": passage_id,
        "原文位置": 0,
        "方向": f"{first['year']}年 · {first['province']} · {first['subject']}",
        "现代释义": f"记录{first['year']}年{first['province']}{first['subject']}高考状元姓名“{first['full_name']}”，保留其学校与地区的时代信息。",
        "文化标签": ["高考状元", first["subject"], first["province"]],
        "男孩适配分": 50,
        "女孩适配分": 50,
        "基础分": 90,
        "高考来源": source_items,
    }


def 导入(连接, path: Path = DATA, apply: bool = False) -> dict:
    data = 读取高考资料(path)
    manifest = data["manifest"]
    rows = data["rows"]
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["given_name"]].append(row)
    summary = {"applied": apply, "source": BOOK_NAME, "rows": len(rows),
               "unique_given_names": len(grouped), "inserted_passages": 0,
               "upserted_materials": 0, "profiles": {}}
    source_path = "web-sources/gaokao-champions-1996-2026.json"
    with 连接.transaction(force_rollback=not apply):
        if not 连接.execute("SELECT pg_try_advisory_xact_lock(2026091702) AS locked").fetchone()["locked"]:
            raise RuntimeError("生产器正在运行，请先停止后再导入")
        连接.execute("LOCK TABLE sources, books, passages, characters, app_materials IN SHARE ROW EXCLUSIVE MODE")
        existing = 连接.execute("SELECT id,sha256 FROM sources WHERE path=%s", (source_path,)).fetchone()
        if existing and existing["sha256"] != manifest["source_sha256"]:
            raise ValueError("高考原始来源哈希已变化，需人工审查后再升级")
        sid = existing["id"] if existing else 连接.execute(
            """INSERT INTO sources(path,file_name,sha256,encoding,source_type,status)
               VALUES (%s,%s,%s,'utf-8',%s,'待核验') RETURNING id""",
            (source_path, "gaokao_champions_1996_2026.json", manifest["source_sha256"], SOURCE_TYPE)).fetchone()["id"]
        bid = 连接.execute("""INSERT INTO books(source_id,name) VALUES (%s,%s)
            ON CONFLICT(source_id,name) DO UPDATE SET name=EXCLUDED.name RETURNING id""", (sid, BOOK_NAME)).fetchone()["id"]
        existing_passages = {x["ordinal"]: x for x in 连接.execute(
            "SELECT id,ordinal,text,section_title FROM passages WHERE source_id=%s AND book_id=%s", (sid, bid))}
        passage_ids = {}
        for ordinal, row in enumerate(rows, 1):
            text = _text(row)
            section = _section(row)
            previous = existing_passages.get(ordinal)
            if previous:
                if previous["text"] != text or previous["section_title"] != section:
                    raise ValueError(f"高考资料原文定位冲突：第{ordinal}条")
                passage_id = previous["id"]
            else:
                passage_id = 连接.execute("""INSERT INTO passages(source_id,book_id,section_title,ordinal,text,
                    source_line_start,source_line_end,status,can_generate,active_for_recall)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'待核验',0,true) RETURNING id""",
                    (sid, bid, section, ordinal, text, row["source_line"], row["source_line"])).fetchone()["id"]
                summary["inserted_passages"] += 1
            passage_ids[ordinal] = passage_id
        chars = sorted({ch for row in rows for ch in row["given_name"] if "\u3400" <= ch <= "\u9fff"})
        with 连接.cursor() as cursor:
            cursor.executemany("""INSERT INTO characters(char,pinyin,pinyin_tone,source,status)
                VALUES (%s,%s,%s,'高考状元来源自动生成','待校对') ON CONFLICT(char) DO NOTHING""",
                [(ch, _pinyin(ch)[0], _pinyin(ch)[1]) for ch in chars])
        profiles = {}
        for length in (1, 2):
            profiles[length] = 连接.execute("""INSERT INTO app_profiles(surname,name_length)
                VALUES ('',%s) ON CONFLICT(surname,name_length) DO UPDATE SET enabled=true RETURNING id""", (length,)).fetchone()["id"]
            summary["profiles"][str(length)] = profiles[length]
        first_ordinal_by_name = {name: next(i for i, row in enumerate(rows, 1) if row["given_name"] == name)
                                 for name in grouped}
        for given_name, related in grouped.items():
            first = related[0]
            ordinal = first_ordinal_by_name[given_name]
            payload = _payload(given_name, first, passage_ids[ordinal], related)
            profile_id = profiles[len(given_name)]
            连接.execute("""INSERT INTO app_materials(profile_id,given_name,full_name,book,passage_id,payload)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO UPDATE SET full_name=EXCLUDED.full_name,passage_id=EXCLUDED.passage_id,payload=EXCLUDED.payload""",
                (profile_id, given_name, given_name, BOOK_NAME, passage_ids[ordinal], Jsonb(payload)))
            summary["upserted_materials"] += 1
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with 连接数据库() as connection:
        print(json.dumps(导入(connection, args.data, args.apply), ensure_ascii=False, indent=2))
