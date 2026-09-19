"""Backfill model-produced gender-fit percentages into accepted shared inventory."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from psycopg.types.json import Jsonb

from 后端.数据库 import 连接数据库
from 后端.智能筛选 import 性别评分单批
from 后端.模型接口 import 读取环境配置, 模型已配置, 验证模型地址


def 补全(批量=25):
    配置 = 读取环境配置()
    if not 模型已配置(配置):
        raise RuntimeError("模型未配置，不能补全性别评分")
    验证模型地址(配置.地址)
    with 连接数据库() as c:
        行 = c.execute("""SELECT m.id,m.given_name,m.payload
            FROM app_materials m JOIN app_profiles p ON p.id=m.profile_id
            WHERE p.surname='' AND (NOT m.payload ? '男孩适配分' OR NOT m.payload ? '女孩适配分')
            ORDER BY m.id""").fetchall()
    已更新 = 0
    for 起点 in range(0, len(行), 批量):
        当前 = 行[起点:起点 + 批量]
        候选 = [{"名字": x["given_name"], **dict(x["payload"])} for x in 当前]
        评分 = 性别评分单批(候选, 配置)
        with 连接数据库() as c:
            for 编号, 分数 in 评分.items():
                已更新 += c.execute("UPDATE app_materials SET payload=payload || %s WHERE id=%s",
                    (Jsonb(分数), 当前[编号]["id"])).rowcount
    return {"待补全": len(行), "已更新": 已更新, "未返回": len(行) - 已更新}


if __name__ == "__main__":
    print(json.dumps(补全(), ensure_ascii=False))
