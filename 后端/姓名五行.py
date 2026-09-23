"""Server-only five-element analysis of one delivered name."""
from functools import lru_cache
import importlib.util
from pathlib import Path

元素 = ("金", "木", "水", "火", "土")
键 = ("jin", "mu", "shui", "huo", "tu")
根 = Path(__file__).resolve().parents[1] / "汉字五行知识库"


@lru_cache(maxsize=1)
def 知识库():
    spec = importlib.util.spec_from_file_location("wuxing_model_overlay", 根 / "model_overlay.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_knowledge(根 / "data/wuxing_knowledge_base.json")


def 分析姓名(姓名):
    data, digest = 知识库()
    totals = {element: 0 for element in 元素}
    missing = []
    sources = []
    supported = 0
    for char in 姓名:
        entry = data.get(char) or {}
        element = entry.get("element")
        sources.append(f"{char}·{element if element in 元素 else '未定'}")
        profile = entry.get("energy_profile") or {}
        scores = profile.get("scores") or {}
        if profile.get("supported") and all(isinstance(scores.get(e), (int, float)) for e in 元素):
            supported += 1
            for e in 元素:
                totals[e] += scores[e]
        elif char not in missing:
            missing.append(char)
    available = supported > 0
    items = []
    for e, key in zip(元素, 键):
        score = min(100, max(0, round(totals[e]))) if available else None
        units = score / 20 if score is not None else 0
        items.append({"key": key, "label": e, "percent": score,
                      "cells": [{"id": i, "fill": round(max(0, min(1, units - i)) * 100)} for i in range(5)],
                      "description": f"{e}，取象强度 {score}%" if available else f"{e}，暂无画像"})
    status = "暂无五维画像" if not available else "部分用字暂无画像" if missing else ""
    summary = " · ".join(f"{x['label']} {x['percent']}%" for x in items) if available else "暂无可计算的五维画像。"
    coverage = f"\n暂无画像：{'、'.join(missing)}；未参与计算。" if missing else ""
    return {"version": "server-v1", "knowledge_version": digest[:16], "analyzed_name": 姓名,
            "available": available, "supported": supported, "total": len(姓名), "items": items, "status": status,
            "explanation": summary + "\n\n字源归类：" + "、".join(sources) +
            "\n\n按逐字五维取象分值分别加总，每项最高计 100；含已输入的姓氏。五格表示该项强度，五项不要求合计为 100。" + coverage +
            "\n\n仅作传统用字参考，不代表八字或五行缺失。"}


def 逐字出处(姓名):
    data, _ = 知识库()
    result = []
    for position, char in enumerate(姓名):
        entry = data.get(char) or {}
        profile = entry.get("energy_profile") or {}
        notes = profile.get("semantic_notes", "").strip() if profile.get("supported") else ""
        citations = []
        seen_citations = set()
        for source in entry.get("sources") or []:
            book = (source.get("book") or "").strip()
            quote = (source.get("quote") or "").strip()
            reference = (source.get("reference") or "").strip()
            item = {"id": len(citations), "book": book, "quote": quote, "reference": reference}
            citation_key = (book, quote, reference)
            if book and (quote or reference) and citation_key not in seen_citations:
                citations.append(item)
                seen_citations.add(citation_key)
        if not citations and not notes:
            continue
        element = entry.get("element")
        index = 元素.index(element) if element in 元素 else -1
        result.append({"id": position, "char": char, "element": element if index >= 0 else "",
                       "tone": 键[index] if index >= 0 else "unknown", "citations": citations,
                       "reason": (entry.get("reason") or "").strip() if index >= 0 else "", "notes": notes})
    return result
