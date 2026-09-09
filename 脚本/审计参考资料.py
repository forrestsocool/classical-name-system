from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path


默认根目录 = Path(__file__).resolve().parents[1]
默认资料目录 = 默认根目录 / "古籍与东亚年号参考资料"
默认输出文件 = 默认根目录 / "构建产物" / "参考资料审计报告.json"


def 读取文本(路径: Path) -> tuple[str, str, list[str]]:
    """读取文本，返回正文、编码和按行拆分结果。"""
    原始字节 = 路径.read_bytes()
    编码 = "utf-8"
    if 原始字节.startswith(b"\xff\xfe") or 原始字节.startswith(b"\xfe\xff"):
        编码 = "utf-16"
    try:
        正文 = 原始字节.decode(编码)
    except UnicodeDecodeError:
        编码 = "gb18030"
        正文 = 原始字节.decode(编码, errors="replace")
    return 正文, 编码, 正文.splitlines()


def 统计古籍(路径: Path) -> dict:
    正文, 编码, 行列表 = 读取文本(路径)
    标题正则 = re.compile(r"^【[^】]+】$")
    标题 = [(行号, 行) for 行号, 行 in enumerate(行列表, 1) if 标题正则.match(行.strip())]
    替换字符数 = 正文.count("�")
    控制字符数 = sum(
        1
        for 字符 in 正文
        if ord(字符) < 32 and 字符 not in {"\n", "\r", "\t"}
    )
    统计 = Counter(正文)
    可疑字 = {字: 统计[字] for 字 in ("乾", "干", "坤", "繁", "體") if 统计[字]}
    重复标题 = []
    for (前行号, 前标题), (后行号, 后标题) in zip(标题, 标题[1:]):
        if 前标题 == 后标题:
            重复标题.append({"前行": 前行号, "后行": 后行号, "标题": 前标题})
    风险 = []
    if 替换字符数:
        风险.append("存在替换字符")
    if 控制字符数:
        风险.append("存在非换行控制字符")
    if 重复标题 and 路径.stem != "诗经":
        风险.append("存在重复篇章标题，需要人工确认篇名结构")
    if 路径.stem == "周易" and 统计["干"]:
        风险.append("包含“干”，需要逐处核对是否应为“乾”")
    return {
        "文件": str(路径),
        "编码": 编码,
        "字节数": 路径.stat().st_size,
        "文件哈希": hashlib.sha256(路径.read_bytes()).hexdigest(),
        "字符数": len(正文),
        "行数": len(行列表),
        "标题数": len(标题),
        "标题示例": [{"行": 行号, "标题": 内容} for 行号, 内容 in 标题[:12]],
        "连续重复标题数": len(重复标题),
        "连续重复标题示例": 重复标题[:12],
        "替换字符数": 替换字符数,
        "控制字符数": 控制字符数,
        "可疑字统计": 可疑字,
        "风险": 风险,
    }


def 统计年号(路径: Path) -> dict:
    正文, 编码, 行列表 = 读取文本(路径)
    区域标题 = []
    三字段 = []
    两字段 = []
    存疑记录 = []
    非三字段记录 = []
    当前分类 = None
    for 行号, 原行 in enumerate(行列表, 1):
        行 = 原行.strip()
        if not 行:
            continue
        if "｜" not in 行:
            if not re.search(r"年|朝鲜|越南|日本|中国", 行):
                区域标题.append({"行": 行号, "标题": 行})
            当前分类 = 行
            continue
        字段 = [字段.strip() for 字段 in 行.split("｜")]
        记录 = {"行": 行号, "分类": 当前分类, "原文": 行, "字段数": len(字段)}
        if len(字段) == 3:
            三字段.append(记录)
        elif len(字段) == 2:
            两字段.append(记录)
        else:
            非三字段记录.append(记录)
        if any("？" in 字段 or "?" in 字段 or "□" in 字段 for 字段 in 字段):
            存疑记录.append(记录)
    return {
        "文件": str(路径),
        "编码": 编码,
        "字节数": 路径.stat().st_size,
        "文件哈希": hashlib.sha256(路径.read_bytes()).hexdigest(),
        "字符数": len(正文),
        "行数": len(行列表),
        "分类或区域标题数": len(区域标题),
        "分类或区域标题示例": 区域标题[:20],
        "三字段记录数": len(三字段),
        "两字段现行记录数": len(两字段),
        "两字段现行记录示例": 两字段[:20],
        "存疑记录数": len(存疑记录),
        "存疑记录示例": 存疑记录[:20],
        "非三字段记录数": len(非三字段记录),
        "非三字段记录示例": 非三字段记录[:20],
        "风险": (["存在无法解析的年号字段"] if 非三字段记录 else [])
        + (["包含待核验字符的年号记录"] if 存疑记录 else []),
    }


def 生成报告(资料目录: Path) -> dict:
    古籍目录 = 资料目录 / "古籍全文"
    古籍报告 = []
    for 路径 in sorted(古籍目录.glob("*.txt")):
        古籍报告.append(统计古籍(路径))

    年号路径 = 资料目录 / "儒家文化圈历史年号汇总.txt"
    年号报告 = 统计年号(年号路径) if 年号路径.exists() else None
    总风险 = sum(len(项目["风险"]) for 项目 in 古籍报告)
    if 年号报告:
        总风险 += len(年号报告["风险"])
    return {
        "报告版本": "1.0",
        "说明": "本报告只读审计原始资料，不代表资料已经完成校勘。",
        "资料目录": str(资料目录),
        "古籍": 古籍报告,
        "年号": 年号报告,
        "风险项目数": 总风险,
    }


def 主程序() -> int:
    解析器 = argparse.ArgumentParser(description="审计古籍和年号原始资料")
    解析器.add_argument("--资料目录", type=Path, default=默认资料目录)
    解析器.add_argument("--输出", type=Path, default=默认输出文件)
    参数 = 解析器.parse_args()
    if not 参数.资料目录.exists():
        print(f"资料目录不存在：{参数.资料目录}", file=sys.stderr)
        return 2
    报告 = 生成报告(参数.资料目录)
    参数.输出.parent.mkdir(parents=True, exist_ok=True)
    参数.输出.write_text(
        json.dumps(报告, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已生成：{参数.输出}")
    print(f"古籍文件：{len(报告['古籍'])} 个")
    print(f"风险项目：{报告['风险项目数']} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(主程序())
