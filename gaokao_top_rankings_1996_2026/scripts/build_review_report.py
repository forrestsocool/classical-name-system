"""Build a deterministic, reviewer-friendly report for the gaokao dataset."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "gaokao_champions_1996_2026.json"
OUTPUT = ROOT / "data" / "review_report.md"


def subject_family(subject: str) -> str:
    """Provide a filterable family while retaining the original subject value."""
    if "物理" in subject:
        return "物理类"
    if "历史" in subject:
        return "历史类"
    if "文" in subject:
        return "文科"
    if "理" in subject:
        return "理科"
    return "综合/其他"


def md_escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def table(headers: list[str] | list[list[object]], rows: list[list[object]] | None = None) -> list[str]:
    if rows is None:
        headers, rows = headers[0], headers[1:]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(md_escape(cell) for cell in row) + " |" for row in rows)
    return lines


def build() -> str:
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    manifest = payload["manifest"]
    rows = payload["rows"]
    year_counts = Counter(row["year"] for row in rows)
    province_counts = Counter(row["province"] for row in rows)
    raw_subject_counts = Counter(row["subject"] for row in rows)
    family_counts = Counter(subject_family(row["subject"]) for row in rows)
    group_counts: dict[tuple[int, str, str], int] = defaultdict(int)
    for row in rows:
        group_counts[(row["year"], row["province"], row["subject"])] += 1
    parallel_groups = [count for count in group_counts.values() if count > 1]
    rows_2026 = [row for row in rows if row["year"] == 2026]

    lines = [
        "# 高考状元姓名来源数据审阅报告",
        "",
        "> 这份报告由 `scripts/build_review_report.py` 从同目录 JSON 重新统计生成，供其他 AI 或人工复核。报告不代表数据已经入库或上线。",
        "",
        "## 1. 审阅结论",
        "",
        "- 当前数据采用“公开汇总的各省高考状元/最高分姓名”口径，不声称覆盖每省每年高考前 100 名。",
        "- 原始 `subject` 完整保留；另外提供便于筛选的归类：文科、理科、物理类、历史类、综合/其他。新高考类别没有被强行转换成旧文理科。",
        "- 1996—2023 有汇总记录，2026 有 21 条明确姓名记录；当前公开快照缺少可复用结构化记录的 2024、2025，不能把空档解释成“该年没有状元”。",
        "- 来源目前是网络二次汇总，适合作为候选姓名来源；上线前应按省份、年份用教育考试院或主流媒体一手页面逐条复核。",
        "",
        "## 2. 数据集概况",
        "",
    ]
    lines.extend(table(
        ["指标", "值"],
        [
            ["数据文件", "data/gaokao_champions_1996_2026.json"],
            ["时间范围", f"{manifest['year_start']}—{manifest['year_end']}"],
            ["已接受记录", manifest["accepted_rows"]],
            ["去重后的名（应用给名粒度）", manifest["unique_given_names"]],
            ["省级地区数", len(manifest["provinces"])],
            ["有记录年份数", len(manifest["years_with_data"])],
            ["缺少记录年份", "、".join(map(str, manifest["missing_years"])) or "无"],
            ["补充的 2026 明确姓名记录", manifest["newer_rows"]],
            ["组合来源 SHA-256", manifest["source_sha256"]],
        ],
    ))
    lines += ["", "## 3. 按年份覆盖", ""]
    lines.extend(table(
        ["年份", "记录数", "状态"],
        [[year, year_counts.get(year, 0), "有记录" if year_counts.get(year) else "缺口"] for year in range(1996, 2027)],
    ))
    lines += ["", "## 4. 类别统计", "", "### 便于筛选的归类", ""]
    lines.extend(table([["归类", "记录数"], *[[key, family_counts[key]] for key in sorted(family_counts)]]))
    lines += ["", "### 原始类别（未改写）", ""]
    lines.extend(table([["原始 subject", "记录数"], *[[key, raw_subject_counts[key]] for key in sorted(raw_subject_counts)]]))
    lines += ["", "## 5. 省份覆盖", ""]
    lines.extend(table([["省级地区", "记录数"], *[[key, province_counts[key]] for key in sorted(province_counts)]]))
    lines += ["", "## 6. 并列与拆分规则", ""]
    lines.extend([
        f"- 同一年、同省、同原始类别下有多条记录的分组数：{len(parallel_groups)}；这些记录保留，不按姓名去重。",
        f"- 最大并列组记录数：{max(parallel_groups, default=1)}。",
        "- 二字姓名取第 2 字为给名，三字姓名取第 2—3 字为给名；仅对已知复姓的四字姓名拆分，无法安全拆分的记录进入 rejected。",
        "- 每条记录保留 year、province、subject、full_name、given_name、school、score、rank_type、source_line，方便回到原始文本定位。",
        "",
        "## 7. 2026 明确姓名记录",
        "",
    ])
    lines.extend(table(
        ["省份", "原始类别", "姓名", "学校", "分数"],
        [[row["province"], row["subject"], row["full_name"], row.get("school") or "—", row.get("score") or "—"] for row in rows_2026],
    ))
    lines += ["", "## 8. 清洗拒绝项", ""]
    lines.extend(table([["原因", "数量"], *[[key, value] for key, value in manifest["rejected"].items()]]))
    lines += ["", "## 9. 原始来源与复现", ""]
    lines.extend([
        f"- [Pastebin 汇总页]({manifest['source_page']})",
        f"- [Pastebin 原文]({manifest['source_url']})",
        f"- [2026 年补充页面](https://www.sohu.com/a/1042818486_100934)",
        f"- 原始文件哈希：`{manifest['source_hashes']['pastebin']}`",
        f"- 2026 补充文件哈希：`{manifest['source_hashes']['sohu_2026']}`",
        "",
        "重新清洗：",
        "",
        "```powershell",
        "python scripts/crawler.py --download",
        "python scripts/crawler.py --normalize",
        "python scripts/build_review_report.py",
        "```",
        "",
        "## 10. 复核建议",
        "",
        "1. 先按 `year + province + subject + full_name` 抽样核对原文；并列状元不要合并。",
        "2. 补齐 2024、2025 后再重新运行 normalize 和本报告脚本；缺口字段会自动更新。",
        "3. 若要扩展成“前 100 名”，应另建带名次、分数、科类和原始出处字段的数据表，不能把本数据集的状元记录复制成前 100 名。",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    OUTPUT.write_text(build(), encoding="utf-8")
    print(OUTPUT)
