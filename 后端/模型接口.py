from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


出处类型 = Literal["原文连取", "同句取字", "跨句组合", "意境延展"]
中文名正则 = re.compile(r"^[\u3400-\u9fff]{1,2}$")


class 模型候选(BaseModel):
    名字: str = Field(min_length=1, max_length=2)
    语料编号: int
    取字方式: 出处类型
    现代释义: str = Field(min_length=1, max_length=160)
    风格标签: list[str] = Field(default_factory=list, max_length=5)
    风险提示: list[str] = Field(default_factory=list, max_length=10)


class 模型输出(BaseModel):
    候选: list[模型候选] = Field(default_factory=list, max_length=30)


class 模型配置(BaseModel):
    地址: str = "https://api.openai.com/v1/chat/completions"
    密钥: str = ""
    模型: str = ""
    超时秒数: float = Field(default=30, ge=1, le=120)


结构化模式 = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "候选": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "名字": {"type": "string"},
                    "语料编号": {"type": "integer"},
                    "取字方式": {
                        "type": "string",
                        "enum": ["原文连取", "同句取字", "跨句组合", "意境延展"],
                    },
                    "现代释义": {"type": "string"},
                    "风格标签": {"type": "array", "items": {"type": "string"}},
                    "风险提示": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "名字",
                    "语料编号",
                    "取字方式",
                    "现代释义",
                    "风格标签",
                    "风险提示",
                ],
            },
        }
    },
    "required": ["候选"],
}


def 读取环境配置() -> 模型配置:
    return 模型配置(
        地址=os.getenv("起名模型地址", "https://api.openai.com/v1/chat/completions"),
        密钥=os.getenv("起名模型密钥", ""),
        模型=os.getenv("起名模型名称", ""),
    )


def 模型已配置(配置: 模型配置 | None = None) -> bool:
    配置 = 配置 or 读取环境配置()
    return bool(配置.密钥 and 配置.模型)


def 调用兼容模型(
    请求摘要: dict[str, Any],
    证据: list[语料证据],
    配置: 模型配置 | None = None,
) -> list[dict[str, Any]]:
    配置 = 配置 or 读取环境配置()
    if not 模型已配置(配置):
        raise RuntimeError("起名模型尚未配置密钥和模型名称")
    提示词 = 构建提示词(请求摘要, 证据)
    请求体 = json.dumps(
        {
            "model": 配置.模型,
            "messages": [
                {"role": "system", "content": 提示词["系统提示"]},
                {"role": "user", "content": 提示词["用户提示"]},
            ],
            "temperature": 0.7,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "name_candidates",
                    "strict": True,
                    "schema": 结构化模式,
                },
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    请求 = urllib.request.Request(
        配置.地址,
        data=请求体,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {配置.密钥}",
        },
        method="POST",
    )
    for 尝试次数 in range(2):
        try:
            with urllib.request.urlopen(请求, timeout=配置.超时秒数) as 响应:
                数据 = json.loads(响应.read().decode("utf-8"))
            内容 = 数据["choices"][0]["message"]["content"]
            if isinstance(内容, list):
                内容 = "".join(
                    项目.get("text", "")
                    for 项目 in 内容
                    if isinstance(项目, dict)
                )
            return 校验模型输出(内容, 证据, int(请求摘要.get("名字长度", 2)))
        except urllib.error.HTTPError as 异常:
            raise RuntimeError(f"起名模型调用失败：{异常.__class__.__name__}") from 异常
        except (urllib.error.URLError, TimeoutError) as 异常:
            if 尝试次数 == 1:
                raise RuntimeError(f"起名模型调用失败：{异常.__class__.__name__}") from 异常
        except (KeyError, IndexError, TypeError, ValueError) as 异常:
            if 尝试次数 == 1:
                raise RuntimeError("起名模型返回内容无法校验") from 异常
    raise RuntimeError("起名模型调用失败")


@dataclass(frozen=True)
class 语料证据:
    编号: int
    正文: str
    书名: str
    篇章: str


def 构建提示词(
    请求摘要: dict[str, Any],
    证据: list[语料证据],
) -> dict[str, str]:
    证据文本 = [
        {
            "语料编号": 项目.编号,
            "书名": 项目.书名,
            "篇章": 项目.篇章,
            "原文": 项目.正文,
        }
        for 项目 in 证据
    ]
    系统提示 = (
        "你是中文起名助手。只能使用用户提供的语料编号，不得编造古籍原文、书名或篇章。"
        "只输出符合指定结构的数据。现代释义必须和原文含义分开，不得把现代愿望冒充古文原意。"
    )
    用户提示 = json.dumps(
        {
            "起名要求": 请求摘要,
            "可用语料": 证据文本,
            "出处类型说明": {
                "原文连取": "名字两个字在同一条原文中连续出现",
                "同句取字": "名字两个字在同一句中出现但不连续",
                "跨句组合": "两个字来自不同句子，必须保留同一语料编号",
                "意境延展": "不是原文固定词组，必须明确标注",
            },
        },
        ensure_ascii=False,
    )
    return {"系统提示": 系统提示, "用户提示": 用户提示}


def 校验模型输出(
    原始输出: dict[str, Any] | str,
    证据: list[语料证据],
    名字长度: int,
) -> list[dict[str, Any]]:
    if isinstance(原始输出, str):
        try:
            原始输出 = json.loads(原始输出)
        except json.JSONDecodeError as 异常:
            raise ValueError(f"模型输出不是合法 JSON：{异常}") from 异常
    try:
        输出 = 模型输出.model_validate(原始输出)
    except (ValidationError, json.JSONDecodeError) as 异常:
        raise ValueError(f"模型输出格式不合格：{异常}") from 异常
    证据表 = {项目.编号: 项目 for 项目 in 证据}
    结果 = []
    已有名字 = set()
    for 候选 in 输出.候选:
        if len(候选.名字) != 名字长度 or not 中文名正则.fullmatch(候选.名字):
            continue
        if 候选.语料编号 not in 证据表:
            continue
        if 候选.名字 in 已有名字:
            continue
        当前证据 = 证据表[候选.语料编号]
        if 候选.取字方式 == "原文连取" and 当前证据.正文.find(候选.名字) < 0:
            continue
        if 候选.取字方式 in {"同句取字", "跨句组合"}:
            if not all(字 in 当前证据.正文 for 字 in 候选.名字):
                continue
        if 候选.取字方式 == "意境延展" and "意境延展" not in 候选.风险提示:
            候选.风险提示.append("意境延展，不是原文固定词组")
        已有名字.add(候选.名字)
        结果.append(
            {
                "名字": 候选.名字,
                "语料编号": 候选.语料编号,
                "取字方式": 候选.取字方式,
                "现代释义": 候选.现代释义,
                "风格标签": 候选.风格标签,
                "风险提示": 候选.风险提示,
                "原文位置": 当前证据.正文.find(候选.名字),
            }
        )
    return 结果
