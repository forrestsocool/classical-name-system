from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


脚本目录 = Path(__file__).resolve().parent
if str(脚本目录) not in sys.path:
    sys.path.insert(0, str(脚本目录))

from 压测服务 import 构造请求, 请求地址, 百分位  # noqa: E402


def 执行场景(基础地址: str, 模式: str, 请求数: int, 并发数: int) -> dict:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import statistics

    结果列表 = []
    with ThreadPoolExecutor(max_workers=并发数) as 执行器:
        任务列表 = [
            执行器.submit(请求地址, *构造请求(基础地址, 模式, 序号))
            for 序号 in range(请求数)
        ]
        for 任务 in as_completed(任务列表):
            结果列表.append(任务.result())
    成功 = [项目 for 项目 in 结果列表 if 200 <= 项目.状态码 < 300]
    耗时 = [项目.耗时毫秒 for 项目 in 结果列表]
    任务编号 = [项目.任务编号 for 项目 in 结果列表 if 项目.任务编号]
    清理成功数 = 0
    if 模式 == "起名":
        for 编号 in 任务编号:
            删除结果 = 请求地址(f"{基础地址}/api/name-runs/{编号}", "DELETE")
            if 200 <= 删除结果.状态码 < 300:
                清理成功数 += 1
    return {
        "模式": 模式,
        "总请求数": len(结果列表),
        "成功数": len(成功),
        "失败数": len(结果列表) - len(成功),
        "平均毫秒": round(statistics.fmean(耗时), 2) if 耗时 else 0,
        "P50毫秒": round(百分位(耗时, 0.50), 2),
        "P95毫秒": round(百分位(耗时, 0.95), 2),
        "最大毫秒": round(max(耗时), 2) if 耗时 else 0,
        "清理任务数": 清理成功数,
        "清理目标数": len(任务编号),
    }


def 主程序() -> int:
    解析器 = argparse.ArgumentParser(description="按生产配置验证起名服务的接口和延迟阈值")
    解析器.add_argument("--地址", default="http://127.0.0.1:8000")
    解析器.add_argument("--请求数", type=int, default=30)
    解析器.add_argument("--并发数", type=int, default=5)
    解析器.add_argument("--检索P95上限", type=float, default=1000)
    解析器.add_argument("--起名P95上限", type=float, default=1500)
    参数 = 解析器.parse_args()
    if not 1 <= 参数.请求数 <= 1000:
        解析器.error("请求数必须在1到1000之间")
    if not 1 <= 参数.并发数 <= 50:
        解析器.error("并发数必须在1到50之间")

    基础地址 = 参数.地址.rstrip("/")
    场景 = [
        执行场景(基础地址, "健康", 参数.请求数, 参数.并发数),
        执行场景(基础地址, "就绪", 参数.请求数, 参数.并发数),
        执行场景(基础地址, "检索", 参数.请求数, 参数.并发数),
        执行场景(基础地址, "起名", 参数.请求数, 参数.并发数),
    ]
    阈值 = {"检索": 参数.检索P95上限, "起名": 参数.起名P95上限}
    失败原因 = []
    for 项目 in 场景:
        if 项目["成功数"] != 项目["总请求数"]:
            失败原因.append(f"{项目['模式']}存在失败请求")
        if 项目["模式"] == "起名" and 项目["清理任务数"] != 项目["清理目标数"]:
            失败原因.append("起名任务清理不完整")
        if 项目["模式"] in 阈值 and 项目["P95毫秒"] > 阈值[项目["模式"]]:
            失败原因.append(
                f"{项目['模式']}P95超过阈值{阈值[项目['模式']]}毫秒"
            )
    输出 = {
        "地址": 基础地址,
        "请求数": 参数.请求数,
        "并发数": 参数.并发数,
        "场景": 场景,
        "阈值": 阈值,
        "状态": "通过" if not 失败原因 else "失败",
        "失败原因": 失败原因,
    }
    print(json.dumps(输出, ensure_ascii=False, indent=2))
    return 0 if not 失败原因 else 1


if __name__ == "__main__":
    raise SystemExit(主程序())
