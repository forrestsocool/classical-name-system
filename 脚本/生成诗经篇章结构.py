from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


根目录 = Path(__file__).resolve().parents[1]
默认输入 = 根目录 / "古籍与东亚年号参考资料" / "古籍全文" / "诗经.txt"
默认输出 = 根目录 / "构建产物" / "诗经篇章结构.json"
标题正则 = re.compile(r"^【([^】]+)】$")
标点正则 = re.compile(r"[，。！？；：、,.!?;:\"“”‘’（）()《》〈〉\s]")


def 读取行(路径: Path) -> tuple[str, list[str]]:
    字节 = 路径.read_bytes()
    编码 = "utf-8"
    if 字节.startswith((b"\xff\xfe", b"\xfe\xff")):
        编码 = "utf-16"
    try:
        正文 = 字节.decode(编码)
    except UnicodeDecodeError:
        编码 = "gb18030"
        正文 = 字节.decode(编码, errors="replace")
    return 编码, 正文.splitlines()


def 首句候选(正文: str) -> str:
    清理后 = 标点正则.sub("", 正文).strip()
    return 清理后[:4] if 清理后 else ""


def 提取篇章(路径: Path) -> dict:
    编码, 行列表 = 读取行(路径)
    篇章: list[dict] = []
    当前: dict | None = None

    def 收集当前() -> None:
        if 当前 is None:
            return
        内容 = 当前.pop("_内容")
        if not 内容:
            return
        首行号, 首句 = 内容[0]
        当前.update(
            {
                "篇号": len(篇章) + 1,
                "首句": 首句,
                "首句篇名候选": 首句候选(首句),
                "篇名状态": "首句候选，待人工核对",
                "原始起始行": 首行号,
                "原始结束行": 内容[-1][0],
                "正文行数": len(内容),
            }
        )
        篇章.append(当前)

    for 行号, 原行 in enumerate(行列表, 1):
        行 = 原行.replace("\ufeff", "").strip()
        if not 行:
            continue
        标题匹配 = 标题正则.fullmatch(行)
        if 标题匹配:
            收集当前()
            当前 = {
                "分区": 标题匹配.group(1).strip(),
                "原始标题": 行,
                "标题行": 行号,
                "_内容": [],
            }
            continue
        if 当前 is not None:
            当前["_内容"].append((行号, 行))
    收集当前()

    分区统计: dict[str, int] = {}
    for 项目 in 篇章:
        分区统计[项目["分区"]] = 分区统计.get(项目["分区"], 0) + 1
    return {
        "报告版本": "1.0",
        "说明": "首句篇名仅为结构候选，人工核对前不得视为正式篇名。",
        "文件": str(路径),
        "编码": 编码,
        "文件哈希": hashlib.sha256(路径.read_bytes()).hexdigest(),
        "篇数": len(篇章),
        "分区统计": 分区统计,
        "篇章": 篇章,
    }


def 主程序() -> int:
    解析器 = argparse.ArgumentParser(description="生成诗经篇章结构候选清单")
    解析器.add_argument("--输入", type=Path, default=默认输入)
    解析器.add_argument("--输出", type=Path, default=默认输出)
    参数 = 解析器.parse_args()
    if not 参数.输入.exists():
        raise FileNotFoundError(f"文件不存在：{参数.输入}")
    参数.输出.parent.mkdir(parents=True, exist_ok=True)
    报告 = 提取篇章(参数.输入)
    参数.输出.write_text(
        json.dumps(报告, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"已生成：{参数.输出}")
    print(f"篇数：{报告['篇数']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(主程序())
