from pathlib import Path
from collections import Counter

text = Path(Path(__file__).parent.parent / "raw_data" / "pastebin-z3XiLUfa.txt").read_text(encoding="utf-8")
rows = []
for line in text.splitlines():
    cells = line.split("\t")
    if len(cells) >= 5 and cells[3].isdigit() and 1900 <= int(cells[3]) <= 2025:
        rows.append(cells)
years = Counter(int(row[3]) for row in rows)
provinces = Counter(row[1] for row in rows)
categories = Counter(row[4] for row in rows)
target = [row for row in rows if 1996 <= int(row[3]) <= 2026]
print({"rows": len(rows), "target_rows": len(target), "province_count": len(provinces),
       "years": [min(years), max(years)], "categories": categories,
       "provinces": provinces})
