"""Normalize the downloaded high-school entrance champion source.

The source is a secondary aggregate.  This script deliberately keeps the raw
file unchanged, emits 1996--2026 rows with their original category, and
rejects rows whose name cannot be safely represented by the app's one/two-
character given-name pool. Re-running it is deterministic.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "raw_data" / "pastebin-z3XiLUfa.txt"
DEFAULT_2026_INPUT = ROOT / "raw_data" / "sohu-2026.html"
DEFAULT_OUTPUT = ROOT / "data" / "gaokao_champions_1996_2026.json"
HAN = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff]+$")
COMPOUND_SURNAMES = {
    "欧阳", "司马", "上官", "诸葛", "令狐", "皇甫", "夏侯", "慕容", "尉迟",
    "长孙", "公孙", "轩辕", "司徒", "司空", "南宫", "宇文", "东郭", "西门",
    "闻人", "独孤", "万俟", "申屠", "呼延", "澹台", "端木", "东方", "公羊",
    "梁丘", "左丘", "羊舌", "微生", "宰父", "夹谷", "拓跋", "颛孙", "濮阳",
    "淳于", "单于", "太叔", "仲孙", "叔孙", "子车", "亓官", "司寇", "巫马",
    "公西", "第五",
}


def _given_name(full_name: str) -> str | None:
    if not HAN.fullmatch(full_name):
        return None
    if len(full_name) == 2:
        return full_name[1:]
    if len(full_name) == 3:
        return full_name[1:]
    if len(full_name) == 4 and full_name[:2] in COMPOUND_SURNAMES:
        return full_name[2:]
    return None


def _number(value: str) -> int | None:
    value = value.strip()
    return int(value) if value.isdigit() else None


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self._depth = 0
        self._parts: list[str] = []
        self.items: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self._depth += 1
            self._parts = []

    def handle_endtag(self, tag):
        if tag == "p" and self._depth:
            self.items.append("".join(self._parts).strip())
            self._depth = 0

    def handle_data(self, data):
        if self._depth:
            self._parts.append(data)


def _parse_2026_html(raw: bytes) -> list[dict]:
    parser = _Paragraphs()
    parser.feed(raw.decode("utf-8", errors="replace"))
    result = []
    line_number = 0
    for paragraph in parser.items:
        if "：" not in paragraph or "分" not in paragraph:
            continue
        province, body = paragraph.split("：", 1)
        province = re.sub(r"（.*?）", "", province).strip()
        if not province or len(province) > 4:
            continue
        matches = list(re.finditer(r"(文科|理科|物理类|历史类|综合)\s*([0-9]+)分?", body))
        for index, match in enumerate(matches):
            subject = match.group(1)
            score = int(match.group(2))
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            section = body[match.end():end]
            for parenthetical in re.findall(r"（([^）]+)）", section):
                for part in parenthetical.split("/"):
                    tokens = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", part)
                    if not tokens:
                        continue
                    full_name = tokens[-1]
                    if _given_name(full_name) is None:
                        continue
                    school = "".join(tokens[:-1])
                    result.append({"year": 2026, "province": province, "subject": subject,
                                   "full_name": full_name, "school": school, "score": score,
                                   "rank_type": "最高分汇总", "source_line": line_number})
        line_number += 1
    return result


def normalize(input_path: Path = DEFAULT_INPUT, newer_path: Path | None = DEFAULT_2026_INPUT) -> tuple[list[dict], dict]:
    raw = input_path.read_bytes()
    text = raw.decode("utf-8-sig")
    newer_raw = b""
    newer_rows = []
    if newer_path and Path(newer_path).exists():
        newer_raw = Path(newer_path).read_bytes()
        newer_rows = _parse_2026_html(newer_raw)
    accepted: list[dict] = []
    rejected = Counter()
    seen: set[tuple] = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        cells = line.split("\t")
        if len(cells) < 5:
            rejected["列数不足"] += 1
            continue
        full_name, province, school, year_text, subject = (x.strip() for x in cells[:5])
        year = _number(year_text)
        if year is None or not 1996 <= year <= 2026:
            rejected["年份或范围"] += 1
            continue
        if not subject:
            rejected["类别为空"] += 1
            continue
        if not province:
            rejected["省份为空"] += 1
            continue
        if not full_name:
            rejected["姓名为空"] += 1
            continue
        given_name = _given_name(full_name)
        if given_name is None:
            rejected["姓名无法拆分"] += 1
            continue
        key = (year, province, subject, full_name, school)
        if key in seen:
            rejected["重复记录"] += 1
            continue
        seen.add(key)
        accepted.append({
            "year": year,
            "province": province,
            "subject": subject,
            "full_name": full_name,
            "given_name": given_name,
            "school": school,
            "score": _number(cells[5]) if len(cells) > 5 else None,
            "rank_type": cells[13].strip() if len(cells) > 13 else "",
            "source_line": line_number,
        })
    for row in newer_rows:
        row = dict(row)
        row["given_name"] = _given_name(row["full_name"])
        key = (row["year"], row["province"], row["subject"], row["full_name"], row["school"])
        if key in seen:
            rejected["重复记录"] += 1
            continue
        seen.add(key)
        accepted.append(row)
    accepted.sort(key=lambda x: (x["year"], x["province"], x["subject"], x["full_name"], x["school"]))
    categories = sorted({x["subject"] for x in accepted})
    combined = hashlib.sha256(raw + b"\0" + newer_raw).hexdigest()
    manifest = {
        "source_url": "https://pastebin.com/raw/z3XiLUfa",
        "source_page": "https://pastebin.com/z3XiLUfa",
        "source_urls": ["https://pastebin.com/raw/z3XiLUfa", "https://www.sohu.com/a/1042818486_100934"],
        "source_sha256": combined,
        "source_hashes": {"pastebin": hashlib.sha256(raw).hexdigest(),
                          "sohu_2026": hashlib.sha256(newer_raw).hexdigest() if newer_raw else None},
        "source_encoding": "utf-8/html",
        "year_start": 1996,
        "year_end": 2026,
        "subjects": categories,
        "source_max_year": max((x["year"] for x in accepted), default=None),
        "years_with_data": sorted({x["year"] for x in accepted}),
        "missing_years": [year for year in range(1996, 2027) if year not in {x["year"] for x in accepted}],
        "newer_rows": len(newer_rows),
        "accepted_rows": len(accepted),
        "unique_given_names": len({x["given_name"] for x in accepted}),
        "provinces": sorted({x["province"] for x in accepted}),
        "rejected": dict(rejected),
    }
    return accepted, manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--newer-input", type=Path, default=DEFAULT_2026_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    rows, manifest = normalize(args.input, args.newer_input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"manifest": manifest, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
