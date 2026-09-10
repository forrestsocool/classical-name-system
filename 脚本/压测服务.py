from __future__ import annotations

import argparse
import json
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

压测会话 = "web-" + uuid.uuid4().hex


@dataclass
class 请求结果:
    状态码: int
    耗时毫秒: float
    任务编号: str = ""
    错误: str = ""


def 请求地址(地址: str, 方法: str = "GET", 数据: dict | None = None) -> 请求结果:
    正文 = None
    请求头 = {"Accept": "application/json", "X-Session-Key": 压测会话}
    if 数据 is not None:
        正文 = json.dumps(数据, ensure_ascii=False).encode("utf-8")
        请求头["Content-Type"] = "application/json"
    开始 = time.perf_counter()
    try:
        with urlopen(
            Request(地址, data=正文, headers=请求头, method=方法), timeout=15
        ) as 响应:
            原文 = 响应.read()
            解析结果 = {}
            if 原文:
                try:
                    解析结果 = json.loads(原文.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    解析结果 = {}
            return 请求结果(
                状态码=响应.status,
                耗时毫秒=(time.perf_counter() - 开始) * 1000,
                任务编号=str(解析结果.get("任务编号", "")),
            )
    except HTTPError as 异常:
        return 请求结果(
            状态码=异常.code,
            耗时毫秒=(time.perf_counter() - 开始) * 1000,
            错误=f"HTTP {异常.code}",
        )
    except (TimeoutError, URLError, OSError) as 异常:
        return 请求结果(
            状态码=0,
            耗时毫秒=(time.perf_counter() - 开始) * 1000,
            错误=异常.__class__.__name__,
        )


def 构造请求(基础地址: str, 模式: str, 序号: int) -> tuple[str, str, dict | None]:
    if 模式 == "健康":
        return f"{基础地址}/api/health", "GET", None
    if 模式 == "就绪":
        return f"{基础地址}/api/ready", "GET", None
    if 模式 == "检索":
        参数 = urlencode({"关键词": "温故", "数量": 5})
        return f"{基础地址}/api/search?{参数}", "GET", None
    return (
        f"{基础地址}/api/name-runs",
        "POST",
        {
            "姓氏": "王",
            "名字长度": 2,
            "方向": ["温润君子"],
            "随机种子": 序号,
        },
    )


def 百分位(数值: list[float], 比例: float) -> float:
    if not 数值:
        return 0.0
    排序 = sorted(数值)
    位置 = min(len(排序) - 1, max(0, round((len(排序) - 1) * 比例)))
    return 排序[位置]


def 主程序() -> int:
    解析器 = argparse.ArgumentParser(description="对起名服务进行可重复的轻量压测")
    解析器.add_argument("--地址", default="http://127.0.0.1:8000")
    解析器.add_argument(
        "--模式", choices=("健康", "就绪", "检索", "起名"), default="检索"
    )
    解析器.add_argument("--请求数", type=int, default=30)
    解析器.add_argument("--并发数", type=int, default=5)
    参数 = 解析器.parse_args()
    if not 1 <= 参数.请求数 <= 1000:
        解析器.error("请求数必须在1到1000之间")
    if not 1 <= 参数.并发数 <= 50:
        解析器.error("并发数必须在1到50之间")

    基础地址 = 参数.地址.rstrip("/")
    结果列表: list[请求结果] = []
    with ThreadPoolExecutor(max_workers=参数.并发数) as 执行器:
        任务 = [
            执行器.submit(
                请求地址,
                *构造请求(基础地址, 参数.模式, 序号),
            )
            for 序号 in range(参数.请求数)
        ]
        for 任务句柄 in as_completed(任务):
            结果列表.append(任务句柄.result())

    成功结果 = [结果 for 结果 in 结果列表 if 200 <= 结果.状态码 < 300]
    任务编号 = [结果.任务编号 for 结果 in 结果列表 if 结果.任务编号]
    清理成功数 = 0
    if 参数.模式 == "起名" and 任务编号:
        for 编号 in 任务编号:
            结果 = 请求地址(f"{基础地址}/api/name-runs/{编号}", "DELETE")
            if 200 <= 结果.状态码 < 300:
                清理成功数 += 1

    耗时 = [结果.耗时毫秒 for 结果 in 结果列表]
    错误类型: dict[str, int] = {}
    for 结果 in 结果列表:
        if not 200 <= 结果.状态码 < 300:
            错误类型[结果.错误 or f"HTTP {结果.状态码}"] = (
                错误类型.get(结果.错误 or f"HTTP {结果.状态码}", 0) + 1
            )
    输出 = {
        "模式": 参数.模式,
        "总请求数": len(结果列表),
        "成功数": len(成功结果),
        "失败数": len(结果列表) - len(成功结果),
        "最小毫秒": round(min(耗时), 2) if 耗时 else 0,
        "平均毫秒": round(statistics.fmean(耗时), 2) if 耗时 else 0,
        "P50毫秒": round(百分位(耗时, 0.50), 2),
        "P95毫秒": round(百分位(耗时, 0.95), 2),
        "最大毫秒": round(max(耗时), 2) if 耗时 else 0,
        "清理任务数": 清理成功数,
        "错误": 错误类型,
    }
    print(json.dumps(输出, ensure_ascii=False, indent=2))
    return 0 if len(成功结果) == len(结果列表) and 清理成功数 == len(任务编号) else 1


if __name__ == "__main__":
    raise SystemExit(主程序())
