from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pypinyin import Style, pinyin


根目录 = Path(__file__).resolve().parents[1]
默认资料目录 = 根目录 / "古籍与东亚年号参考资料"
默认数据库 = 根目录 / "构建产物" / "起名系统.sqlite3"
报告文件 = 根目录 / "构建产物" / "参考资料审计报告.json"
配置目录 = 根目录 / "资料配置"
初始核验文件 = 配置目录 / "初始核验片段.json"
初始词组文件 = 配置目录 / "初始典故词组.json"
初始五行文件 = 配置目录 / "初始汉字五行.json"

古籍标题正则 = re.compile(r"^【([^】]+)】$")
纯噪声正则 = re.compile(r"^[ⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ]+$")

方向关键词 = {
    "温润君子": ("玉", "和", "谦", "修", "文"),
    "胸怀天下": ("济", "川", "岳", "远", "怀"),
    "智慧通达": ("明", "哲", "睿", "知"),
    "坚毅担当": ("毅", "恒", "刚", "正"),
    "自由洒脱": ("云", "风", "逸", "清"),
    "文采气质": ("章", "华", "辞", "翰"),
    "安宁福泽": ("安", "宁", "嘉", "瑞"),
}


def 读取文本(路径: Path) -> tuple[str, str, list[str]]:
    字节 = 路径.read_bytes()
    编码 = "utf-8"
    if 字节.startswith((b"\xff\xfe", b"\xfe\xff")):
        编码 = "utf-16"
    try:
        正文 = 字节.decode(编码)
    except UnicodeDecodeError:
        编码 = "gb18030"
        正文 = 字节.decode(编码, errors="replace")
    return 正文, 编码, 正文.splitlines()


def 规范化行(行: str) -> str:
    行 = 行.replace("\ufeff", "").replace("\u200b", "").strip()
    行 = re.sub(r"[ \t]+", " ", 行)
    return 行


def 规范化篇章标题(书名: str, 标题: str) -> str:
    """只规范展示用章节标题，不改写出处正文和原始文件。"""
    if 书名 == "周易" and 标题 == "01. 干（卦一）":
        return "01. 乾（卦一）"
    return 标题


def 切分古籍(书名: str, 路径: Path, 书籍编号: int, 来源编号: int) -> list[dict]:
    _, _, 行列表 = 读取文本(路径)
    片段 = []
    当前篇章 = "全文"
    序号 = 0
    for 行号, 原行 in enumerate(行列表, 1):
        行 = 规范化行(原行)
        if not 行 or 纯噪声正则.fullmatch(行):
            continue
        标题匹配 = 古籍标题正则.match(行)
        if 标题匹配:
            当前篇章 = 规范化篇章标题(
                书名, 标题匹配.group(1).strip()
            )
            continue
        # 保留原始行号。过长行分块，但不把文本改写成新的句子。
        最大长度 = 240
        for 起点 in range(0, len(行), 最大长度):
            内容 = 行[起点 : 起点 + 最大长度]
            if not 内容:
                continue
            序号 += 1
            片段.append(
                {
                    "来源编号": 来源编号,
                    "书籍编号": 书籍编号,
                    "篇章": 当前篇章,
                    "序号": 序号,
                    "正文": 内容,
                    "原始起始行": 行号,
                    "原始结束行": 行号,
                    "状态": "待核验",
                    "可用于生成": 0,
                }
            )
    return 片段


def 建立表结构(连接: sqlite3.Connection) -> None:
    连接.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS schema_version (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version TEXT NOT NULL,
            built_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            file_name TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            encoding TEXT NOT NULL,
            source_type TEXT NOT NULL,
            status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES sources(id),
            name TEXT NOT NULL,
            UNIQUE(source_id, name)
        );

        CREATE TABLE IF NOT EXISTS passages (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES sources(id),
            book_id INTEGER NOT NULL REFERENCES books(id),
            section_title TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            text TEXT NOT NULL,
            source_line_start INTEGER NOT NULL,
            source_line_end INTEGER NOT NULL,
            status TEXT NOT NULL,
            can_generate INTEGER NOT NULL DEFAULT 0 CHECK (can_generate IN (0, 1)),
            reviewed_at TEXT,
            reviewer TEXT,
            review_note TEXT
        );

        CREATE TABLE IF NOT EXISTS eras (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES sources(id),
            region TEXT NOT NULL,
            category TEXT NOT NULL,
            era_name TEXT NOT NULL,
            period TEXT NOT NULL,
            duration TEXT NOT NULL,
            status TEXT NOT NULL,
            source_line INTEGER NOT NULL DEFAULT 0,
            record_type TEXT NOT NULL DEFAULT '正式年号',
            person TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS directions (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS direction_keywords (
            direction_id INTEGER NOT NULL REFERENCES directions(id),
            keyword TEXT NOT NULL,
            PRIMARY KEY(direction_id, keyword)
        );

        CREATE TABLE IF NOT EXISTS audit_issues (
            id INTEGER PRIMARY KEY,
            source_id INTEGER REFERENCES sources(id),
            issue_type TEXT NOT NULL,
            detail TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '待处理',
            reviewed_at TEXT,
            reviewer TEXT,
            review_note TEXT
        );

        CREATE TABLE IF NOT EXISTS name_runs (
            id TEXT PRIMARY KEY,
            request_json TEXT NOT NULL,
            bazi_json TEXT,
            random_seed INTEGER,
            rule_version TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES name_runs(id),
            full_name TEXT NOT NULL,
            given_name TEXT NOT NULL,
            book TEXT,
            section_title TEXT,
            source_passage_id INTEGER REFERENCES passages(id),
            source_text TEXT,
            source_offset INTEGER NOT NULL DEFAULT 0,
            direction TEXT,
            wuxing_json TEXT,
            pinyin TEXT,
            pinyin_tone TEXT,
            origin_type TEXT NOT NULL,
            base_score INTEGER NOT NULL,
            UNIQUE(run_id, full_name)
        );

        CREATE TABLE IF NOT EXISTS candidate_phrases (
            id INTEGER PRIMARY KEY,
            passage_id INTEGER NOT NULL REFERENCES passages(id),
            phrase TEXT NOT NULL,
            source_offset INTEGER NOT NULL,
            direction TEXT NOT NULL,
            origin_type TEXT NOT NULL,
            quality_score INTEGER NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            UNIQUE(passage_id, phrase, direction)
        );

        CREATE TABLE IF NOT EXISTS characters (
            char TEXT PRIMARY KEY,
            pinyin TEXT NOT NULL,
            pinyin_tone TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS character_elements (
            char TEXT NOT NULL REFERENCES characters(char),
            element TEXT NOT NULL,
            method TEXT NOT NULL,
            confidence TEXT NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            reviewed_at TEXT,
            reviewer TEXT,
            PRIMARY KEY(char, method)
        );

        CREATE TABLE IF NOT EXISTS model_candidates (
            id INTEGER PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES name_runs(id),
            name TEXT NOT NULL,
            passage_id INTEGER REFERENCES passages(id),
            origin_type TEXT NOT NULL,
            meaning TEXT NOT NULL,
            style_json TEXT NOT NULL,
            risks_json TEXT NOT NULL,
            source_offset INTEGER NOT NULL DEFAULT -1,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(run_id, name)
        );

        CREATE TABLE IF NOT EXISTS model_metrics (
            id INTEGER PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES name_runs(id),
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            latency_ms INTEGER NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            estimated_cost REAL,
            status TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY,
            collection_id TEXT NOT NULL,
            run_id TEXT,
            full_name TEXT NOT NULL,
            given_name TEXT NOT NULL,
            pinyin TEXT,
            pinyin_tone TEXT,
            book TEXT,
            section_title TEXT,
            source_passage_id INTEGER,
            source_text TEXT,
            source_offset INTEGER,
            direction TEXT,
            wuxing_json TEXT,
            origin_type TEXT,
            base_score INTEGER,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(collection_id, full_name)
        );

        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY,
            collection_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            full_name TEXT NOT NULL,
            feedback_type TEXT NOT NULL,
            score INTEGER,
            comment TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(collection_id, run_id, full_name)
        );

        CREATE INDEX IF NOT EXISTS idx_passages_book ON passages(book_id);
        CREATE INDEX IF NOT EXISTS idx_passages_section ON passages(section_title);
        CREATE INDEX IF NOT EXISTS idx_passages_text ON passages(text);
        CREATE INDEX IF NOT EXISTS idx_eras_region ON eras(region);
        """
    )
    现有列 = {
        行[1]
        for 行 in 连接.execute("PRAGMA table_info(name_runs)").fetchall()
    }
    if "bazi_json" not in 现有列:
        连接.execute("ALTER TABLE name_runs ADD COLUMN bazi_json TEXT")
    片段现有列 = {
        行[1]
        for 行 in 连接.execute("PRAGMA table_info(passages)").fetchall()
    }
    for 列名 in ("reviewed_at", "reviewer", "review_note"):
        if 列名 not in 片段现有列:
            连接.execute(f"ALTER TABLE passages ADD COLUMN {列名} TEXT")
    候选现有列 = {
        行[1]
        for 行 in 连接.execute("PRAGMA table_info(candidates)").fetchall()
    }
    if "source_offset" not in 候选现有列:
        连接.execute(
            "ALTER TABLE candidates ADD COLUMN source_offset INTEGER NOT NULL DEFAULT 0"
        )
    for 列名 in ("direction", "wuxing_json"):
        if 列名 not in 候选现有列:
            连接.execute(f"ALTER TABLE candidates ADD COLUMN {列名} TEXT")
    for 列名 in ("pinyin", "pinyin_tone"):
        if 列名 not in 候选现有列:
            连接.execute(f"ALTER TABLE candidates ADD COLUMN {列名} TEXT")
    五行现有列 = {
        行[1]
        for 行 in 连接.execute("PRAGMA table_info(character_elements)").fetchall()
    }
    for 列名 in ("reviewed_at", "reviewer"):
        if 列名 not in 五行现有列:
            连接.execute(f"ALTER TABLE character_elements ADD COLUMN {列名} TEXT")
    问题现有列 = {
        行[1]
        for 行 in 连接.execute("PRAGMA table_info(audit_issues)").fetchall()
    }
    for 列名 in ("reviewed_at", "reviewer", "review_note"):
        if 列名 not in 问题现有列:
            连接.execute(f"ALTER TABLE audit_issues ADD COLUMN {列名} TEXT")
    年号现有列 = {
        行[1]
        for 行 in 连接.execute("PRAGMA table_info(eras)").fetchall()
    }
    for 列名, 定义 in (
        ("source_line", "INTEGER NOT NULL DEFAULT 0"),
        ("record_type", "TEXT NOT NULL DEFAULT '正式年号'"),
        ("person", "TEXT NOT NULL DEFAULT ''"),
        ("note", "TEXT NOT NULL DEFAULT ''"),
    ):
        if 列名 not in 年号现有列:
            连接.execute(f"ALTER TABLE eras ADD COLUMN {列名} {定义}")


def 清空可重建表(连接: sqlite3.Connection) -> None:
    for 表名 in (
        "feedback",
        "favorites",
        "model_metrics",
        "model_candidates",
        "candidates",
        "candidate_phrases",
        "name_runs",
        "audit_issues",
        "character_elements",
        "characters",
        "direction_keywords",
        "eras",
        "passages",
        "directions",
        "books",
        "sources",
    ):
        连接.execute(f"DELETE FROM {表名}")


def 读入古籍(连接: sqlite3.Connection, 资料目录: Path) -> int:
    数量 = 0
    古籍目录 = 资料目录 / "古籍全文"
    for 路径 in sorted(古籍目录.glob("*.txt")):
        正文, 编码, _ = 读取文本(路径)
        哈希 = hashlib.sha256(路径.read_bytes()).hexdigest()
        游标 = 连接.execute(
            """
            INSERT INTO sources(path, file_name, sha256, encoding, source_type, status)
            VALUES (?, ?, ?, ?, '古籍', '待核验')
            """,
            (str(路径), 路径.name, 哈希, 编码),
        )
        来源编号 = 游标.lastrowid
        游标 = 连接.execute(
            "INSERT INTO books(source_id, name) VALUES (?, ?)",
            (来源编号, 路径.stem),
        )
        书籍编号 = 游标.lastrowid
        片段 = 切分古籍(路径.stem, 路径, 书籍编号, 来源编号)
        连接.executemany(
            """
            INSERT INTO passages(
                source_id, book_id, section_title, ordinal, text,
                source_line_start, source_line_end, status, can_generate
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    项目["来源编号"],
                    项目["书籍编号"],
                    项目["篇章"],
                    项目["序号"],
                    项目["正文"],
                    项目["原始起始行"],
                    项目["原始结束行"],
                    项目["状态"],
                    项目["可用于生成"],
                )
                for 项目 in 片段
            ],
        )
        if 路径.stem == "周易" and "干" in 正文:
            连接.execute(
                "INSERT INTO audit_issues(source_id, issue_type, detail) VALUES (?, ?, ?)",
                (来源编号, "字形核验", "文本包含“干”，需要逐处核对是否应为“乾”"),
            )
        数量 += len(片段)
    return 数量


def 应用初始核验配置(连接: sqlite3.Connection) -> int:
    if not 初始核验文件.exists():
        return 0
    配置 = json.loads(初始核验文件.read_text(encoding="utf-8"))
    已核验数 = 0
    for 项目 in 配置:
        行号 = 项目["原始行"]
        锚点 = 项目.get("锚点", "")
        查询 = """
            SELECT p.id
            FROM passages p
            JOIN books b ON b.id = p.book_id
            WHERE b.name = ? AND p.source_line_start = ?
        """
        参数: list[object] = [项目["古籍"], 行号]
        if 锚点:
            查询 += " AND p.text LIKE ?"
            参数.append(f"%{锚点}%")
        行 = 连接.execute(查询, 参数).fetchone()
        if 行 is None:
            连接.execute(
                "INSERT INTO audit_issues(issue_type, detail) VALUES (?, ?)",
                (
                    "初始核验配置",
                    f"未找到片段：{项目['古籍']}第{行号}行，锚点：{锚点}",
                ),
            )
            continue
        连接.execute(
            """
            UPDATE passages
            SET status = '已核验', can_generate = 1,
                reviewed_at = ?, reviewer = ?, review_note = ?
            WHERE id = ?
            """,
            (
                项目.get("复核时间", "开发阶段"),
                项目.get("复核人", "开发阶段初步复核"),
                项目.get("备注", "已核对本地片段完整性，正式上线前建议二次校对。"),
                行[0],
            ),
        )
        已核验数 += 1
    return 已核验数


def 读入典故词组(连接: sqlite3.Connection) -> int:
    if not 初始词组文件.exists():
        return 0
    配置 = json.loads(初始词组文件.read_text(encoding="utf-8"))
    词组数 = 0
    for 项目 in 配置:
        行 = 连接.execute(
            """
            SELECT p.id, p.text
            FROM passages p
            JOIN books b ON b.id = p.book_id
            WHERE b.name = ? AND p.source_line_start = ?
              AND p.can_generate = 1 AND p.text LIKE ?
            """,
            (项目["古籍"], 项目["原始行"], f"%{项目['词组']}%"),
        ).fetchone()
        if 行 is None:
            连接.execute(
                "INSERT INTO audit_issues(issue_type, detail) VALUES (?, ?)",
                (
                    "典故词组配置",
                    f"未找到已核验词组：{项目['古籍']}第{项目['原始行']}行，{项目['词组']}",
                ),
            )
            continue
        偏移 = 行[1].find(项目["词组"])
        连接.execute(
            """
            INSERT INTO candidate_phrases(
                passage_id, phrase, source_offset, direction,
                origin_type, quality_score, status, note
            ) VALUES (?, ?, ?, ?, ?, ?, '已核验', ?)
            """,
            (
                行[0],
                项目["词组"],
                偏移,
                项目["方向"],
                项目.get("出处类型", "原文连取"),
                项目.get("质量分", 80),
                项目.get("备注", "初始词组，正式上线前建议二次校对。"),
            ),
        )
        词组数 += 1
    return 词组数


def 是汉字(字符: str) -> bool:
    return "\u3400" <= 字符 <= "\u9fff" or "\uf900" <= 字符 <= "\ufaff"


def 读入汉字(连接: sqlite3.Connection) -> int:
    字符集合: set[str] = set()
    for 行 in 连接.execute("SELECT text FROM passages"):
        字符集合.update(字符 for 字符 in 行[0] if 是汉字(字符))
    记录 = []
    for 字符 in sorted(字符集合):
        普通拼音 = pinyin(字符, style=Style.NORMAL, heteronym=False)[0][0]
        声调拼音 = pinyin(字符, style=Style.TONE3, heteronym=False)[0][0]
        记录.append((字符, 普通拼音, 声调拼音, "拼音库自动生成", "待校对"))
    连接.executemany(
        """
        INSERT INTO characters(char, pinyin, pinyin_tone, source, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        记录,
    )
    return len(记录)


def 读入五行规则(连接: sqlite3.Connection) -> int:
    if not 初始五行文件.exists():
        return 0
    配置 = json.loads(初始五行文件.read_text(encoding="utf-8"))
    数量 = 0
    for 项目 in 配置:
        是否存在 = 连接.execute(
            "SELECT 1 FROM characters WHERE char = ?", (项目["字符"],)
        ).fetchone()
        if not 是否存在:
            连接.execute(
                "INSERT INTO characters(char, pinyin, pinyin_tone, source, status) VALUES (?, ?, ?, ?, ?)",
                (项目["字符"], "", "", "五行配置补充", "待校对"),
            )
        连接.execute(
            """
            INSERT INTO character_elements(
                char, element, method, confidence, status, note
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                项目["字符"],
                项目["五行"],
                项目["方法"],
                项目.get("置信度", "待复核"),
                项目.get("状态", "待复核"),
                项目.get("备注", ""),
            ),
        )
        数量 += 1
    return 数量


def 年号地区(文本: str, 当前地区: str) -> str:
    if 文本 in {"中国", "朝鲜半岛", "越南", "日本"}:
        return 文本
    return 当前地区


年号网页标记正则 = re.compile(r"\{\{.*?\}\}")
年号属性标记正则 = re.compile(r"(?:rowspan|colspan)=\"[^\"]*\"\|")


def 清洗年号字段(字段: str) -> tuple[str, bool]:
    原字段 = 字段.strip()
    字段 = 年号网页标记正则.sub("", 原字段)
    字段 = 年号属性标记正则.sub("", 字段)
    字段 = re.sub(r"\s+", " ", 字段).strip()
    return 字段, 字段 != 原字段


def 是年数字段(字段: str) -> bool:
    return bool(
        re.fullmatch(
            r"[0-9０-９一二三四五六七八九十百千万？?－—-]+年?",
            字段,
        )
    ) or 字段 in {"现行", "未详", "未标注"}


def 解析年号字段(字段: list[str]) -> tuple[str, str, str, str, str, str]:
    """返回年号名、时期、年数、人物、记录类型和清洗备注。"""
    年号名, 名有标记 = 清洗年号字段(字段[0])
    时期, 期有标记 = 清洗年号字段(字段[1])
    备注: list[str] = []
    if 名有标记 or 期有标记:
        备注.append("原始字段含网页标记，已清洗展示字段")
    if len(字段) == 2:
        备注.append("原始资料未提供年数")
        年数 = "现行"
        人物 = ""
        记录类型 = "现行年号"
    else:
        第三字段, 第三字段有标记 = 清洗年号字段(字段[2])
        if 第三字段有标记:
            备注.append("原始人物字段含网页属性标记，已清洗展示字段")
        if 是年数字段(第三字段):
            年数 = 第三字段
            人物 = ""
            记录类型 = "正式年号"
        else:
            年数 = "未标注"
            人物 = 第三字段
            记录类型 = "其他政权年号"
            备注.append("第三字段按人物或政权处理")
    if any(
        "？" in 项目 or "?" in 项目 or "□" in 项目
        for 项目 in (年号名, 时期, 年数, 人物)
    ):
        记录类型 = "存疑记录"
        备注.append("含待核对字符")
    return 年号名, 时期, 年数, 人物, 记录类型, "；".join(备注)


def 读入年号(连接: sqlite3.Connection, 资料目录: Path) -> int:
    路径 = 资料目录 / "儒家文化圈历史年号汇总.txt"
    if not 路径.exists():
        return 0
    正文, 编码, 行列表 = 读取文本(路径)
    哈希 = hashlib.sha256(路径.read_bytes()).hexdigest()
    来源编号 = 连接.execute(
        """
        INSERT INTO sources(path, file_name, sha256, encoding, source_type, status)
        VALUES (?, ?, ?, ?, '年号', '待核验')
        """,
        (str(路径), 路径.name, 哈希, 编码),
    ).lastrowid
    地区 = "未分类"
    分类 = "未分类"
    数量 = 0
    for 行号, 原行 in enumerate(行列表, 1):
        行 = 规范化行(原行)
        if not 行:
            continue
        if "｜" not in 行:
            新地区 = 年号地区(行, 地区)
            if 新地区 != 地区:
                地区 = 新地区
            else:
                分类, _ = 清洗年号字段(行)
            continue
        字段 = [项目.strip() for 项目 in 行.split("｜")]
        if len(字段) not in (2, 3):
            连接.execute(
                "INSERT INTO audit_issues(source_id, issue_type, detail) VALUES (?, ?, ?)",
                (来源编号, "年号字段", f"第{行号}行不是三字段记录：{行}"),
            )
            continue
        年号名, 时期, 年数, 人物, 记录类型, 备注 = 解析年号字段(字段)
        连接.execute(
            """
            INSERT INTO eras(
                source_id, region, category, era_name, period, duration, status,
                source_line, record_type, person, note
            ) VALUES (?, ?, ?, ?, ?, ?, '待核验', ?, ?, ?, ?)
            """,
            (
                来源编号,
                地区,
                分类,
                年号名,
                时期,
                年数,
                行号,
                记录类型,
                人物,
                备注,
            ),
        )
        数量 += 1
    return 数量


def 写入方向(连接: sqlite3.Connection) -> None:
    for 方向, 关键词 in 方向关键词.items():
        方向编号 = 连接.execute(
            "INSERT INTO directions(name) VALUES (?)", (方向,)
        ).lastrowid
        连接.executemany(
            "INSERT INTO direction_keywords(direction_id, keyword) VALUES (?, ?)",
            [(方向编号, 关键词项) for 关键词项 in 关键词],
        )


def 写入报告风险(连接: sqlite3.Connection) -> None:
    if not 报告文件.exists():
        return
    报告 = json.loads(报告文件.read_text(encoding="utf-8"))
    for 项目 in 报告.get("古籍", []):
        文件名 = Path(项目["文件"]).name
        来源 = 连接.execute(
            "SELECT id FROM sources WHERE file_name = ?", (文件名,)
        ).fetchone()
        if 来源:
            for 风险 in 项目.get("风险", []):
                连接.execute(
                    "INSERT INTO audit_issues(source_id, issue_type, detail) VALUES (?, ?, ?)",
                    (来源[0], "审计报告", 风险),
                )


def 建库(资料目录: Path, 数据库路径: Path) -> dict:
    数据库路径.parent.mkdir(parents=True, exist_ok=True)
    连接 = sqlite3.connect(数据库路径)
    try:
        建立表结构(连接)
        清空可重建表(连接)
        古籍片段数 = 读入古籍(连接, 资料目录)
        初始核验数 = 应用初始核验配置(连接)
        词组数 = 读入典故词组(连接)
        汉字数 = 读入汉字(连接)
        五行规则数 = 读入五行规则(连接)
        年号数 = 读入年号(连接, 资料目录)
        写入方向(连接)
        写入报告风险(连接)
        连接.execute(
            """
            INSERT INTO schema_version(id, version, built_at)
            VALUES (1, '0.1.0', ?)
            ON CONFLICT(id) DO UPDATE SET version=excluded.version, built_at=excluded.built_at
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )
        连接.commit()
        统计 = {
            "数据库": str(数据库路径),
            "古籍数": 连接.execute("SELECT COUNT(*) FROM books").fetchone()[0],
            "古籍片段数": 古籍片段数,
            "年号数": 年号数,
            "方向数": 连接.execute("SELECT COUNT(*) FROM directions").fetchone()[0],
            "待处理问题数": 连接.execute(
                "SELECT COUNT(*) FROM audit_issues WHERE status = '待处理'"
            ).fetchone()[0],
            "已核验片段数": 初始核验数,
            "已核验词组数": 词组数,
            "汉字数": 汉字数,
            "五行规则数": 五行规则数,
            "可用于生成片段数": 连接.execute(
                "SELECT COUNT(*) FROM passages WHERE can_generate = 1"
            ).fetchone()[0],
        }
        return 统计
    finally:
        连接.close()


def 主程序() -> int:
    解析器 = argparse.ArgumentParser(description="建立起名系统 SQLite 资料库")
    解析器.add_argument("--资料目录", type=Path, default=默认资料目录)
    解析器.add_argument("--数据库", type=Path, default=默认数据库)
    参数 = 解析器.parse_args()
    统计 = 建库(参数.资料目录, 参数.数据库)
    print(json.dumps(统计, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(主程序())
