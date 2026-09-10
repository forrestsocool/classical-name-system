from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


根目录 = Path(__file__).resolve().parents[1]
默认输入 = 根目录 / "古籍与东亚年号参考资料" / "古籍全文" / "诗经.txt"
默认输出 = 根目录 / "构建产物" / "诗经篇章结构.json"
默认篇名配置 = 根目录 / "资料配置" / "诗经正式篇名.json"
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


def 读取篇名配置(路径: Path) -> dict:
    if not 路径.exists():
        return {"分区篇名": {}, "来源": []}
    配置 = json.loads(路径.read_text(encoding="utf-8"))
    if not isinstance(配置.get("分区篇名"), dict):
        raise ValueError(f"篇名配置缺少“分区篇名”：{路径}")
    return 配置


def 提取篇章(路径: Path, 篇名配置: dict | None = None) -> dict:
    编码, 行列表 = 读取行(路径)
    篇章: list[dict] = []
    当前: dict | None = None
    分区序号: dict[str, int] = {}
    篇名配置 = 篇名配置 or {"分区篇名": {}, "来源": []}
    分区篇名 = 篇名配置.get("分区篇名", {})
    篇名来源 = ""
    if 篇名配置.get("来源"):
        篇名来源 = 篇名配置["来源"][0].get("名称", "")

    def 收集当前() -> None:
        if 当前 is None:
            return
        内容 = 当前.pop("_内容")
        if not 内容:
            return
        首行号, 首句 = 内容[0]
        分区 = 当前["分区"]
        分区序号[分区] = 分区序号.get(分区, 0) + 1
        正式篇名 = ""
        候选篇名 = 分区篇名.get(分区, [])
        if 分区序号[分区] <= len(候选篇名):
            正式篇名 = str(候选篇名[分区序号[分区] - 1]).strip()
        当前.update(
            {
                "篇号": len(篇章) + 1,
                "首句": 首句,
                "首句篇名候选": 首句候选(首句),
                "正式篇名": 正式篇名,
                "篇名状态": "已按目录核对" if 正式篇名 else "首句候选，待人工核对",
                "篇名来源": 篇名来源 if 正式篇名 else "",
                "分区篇序": 分区序号[分区],
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
    配置篇数 = sum(len(名称列表) for 名称列表 in 分区篇名.values())
    正式篇名数 = sum(bool(项目["正式篇名"]) for 项目 in 篇章)
    if 分区篇名 and 配置篇数 != len(篇章):
        raise ValueError(f"正式篇名配置数量为{配置篇数}，原始篇章数量为{len(篇章)}")
    if 分区篇名 and 正式篇名数 != len(篇章):
        raise ValueError(f"正式篇名覆盖数量为{正式篇名数}，原始篇章数量为{len(篇章)}")
    if 分区篇名 and {键: len(值) for 键, 值 in 分区篇名.items()} != 分区统计:
        raise ValueError("篇名配置与原文的分区数量不一致")
    return {
        "报告版本": "1.1",
        "说明": "正式篇名按配置目录与原始分区顺序关联；首句篇名候选仅作辅助检索字段。",
        "文件": str(路径),
        "编码": 编码,
        "文件哈希": hashlib.sha256(路径.read_bytes()).hexdigest(),
        "篇名配置": "",
        "篇名来源": 篇名配置.get("来源", []),
        "篇数": len(篇章),
        "正式篇名数": 正式篇名数,
        "分区统计": 分区统计,
        "篇章": 篇章,
    }


def 主程序() -> int:
    解析器 = argparse.ArgumentParser(description="生成诗经篇章结构候选清单")
    解析器.add_argument("--输入", type=Path, default=默认输入)
    解析器.add_argument("--输出", type=Path, default=默认输出)
    解析器.add_argument("--篇名配置", type=Path, default=默认篇名配置)
    参数 = 解析器.parse_args()
    if not 参数.输入.exists():
        raise FileNotFoundError(f"文件不存在：{参数.输入}")
    参数.输出.parent.mkdir(parents=True, exist_ok=True)
    报告 = 提取篇章(参数.输入, 读取篇名配置(参数.篇名配置))
    报告["篇名配置"] = str(参数.篇名配置)
    参数.输出.write_text(
        json.dumps(报告, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"已生成：{参数.输出}")
    print(f"篇数：{报告['篇数']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(主程序())
