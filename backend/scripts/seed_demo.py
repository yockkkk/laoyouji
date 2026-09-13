"""灌入演示数据（等价 POST /api/seed）。

    python scripts/seed_demo.py --list                          # 先看四个剧本长什么样
    python scripts/seed_demo.py                                 # 只有默认家庭
    python scripts/seed_demo.py --scenario hypertension_spike   # 再加 30 天指标档案
    python scripts/seed_demo.py --level 紧急                    # 按档位切（中文要在 UTF-8 终端里敲）

``--scenario`` 是**可选**的：不加就是原来那份干净的默认家庭（也是所有测试的基线）。
加了才给张桂芳补上康乐左翼要看的那 30 天指标/慢病/用药 —— 答辩现场切档靠它。

四档一句话切换：``stable``（保健）/ ``observation``（观察）/ ``hypertension_spike``
（建议就医，默认）/ ``emergency``（紧急）。日期一律相对"今天"生成，所以
**演示当天早上跑一次**拿到的就是当天的时间线，不会翻出几个月前的死日期。

灌完不靠脚本自己念结论：把数从库里**读回来**，再喂给 ``health_rules`` 算一遍档位。
演示者当场看到的是"库里这些数 → 这个档位"，而不是脚本背下来的一句话。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bootstrap import build_context  # noqa: E402
from app.db.seed import (KANGLE_PERSONA, SCENARIOS, resolve_scenario,  # noqa: E402
                         seed_demo, seed_kangle_persona)
from app.safety import health_rules as hr  # noqa: E402
from app.tools.health_tools import (_active_conditions, _grouped_history,  # noqa: E402
                                    triage_overview)

# 今天那几条读数标在清晨（最早的 06:41）。比这个时刻还早跑，屏幕上会出现"未来时间" ——
# REFOCUS §6.4 明确不许。不做"夹到当前时刻"的钳制：那会把墙钟引进种子，同一份档案
# 两次跑出来就不一样了。宁可打一句警告。
_MORNING_READINGS_END = dtime(7, 40)


def _print_scenarios() -> None:
    print("可选剧本（--scenario 用 key，--level 用档位）：")
    for name, sc in SCENARIOS.items():
        s, d = sc["bp_tail"][0]
        print(f"  {name:<20} {sc['level']:<5} 今天 {s}/{d} mmHg   {sc['story']}")
    print(f"\n人物：张桂芳（{KANGLE_PERSONA['sex']}，{KANGLE_PERSONA['age']} 岁，"
          f"{KANGLE_PERSONA['city']}，{KANGLE_PERSONA['living']}，{KANGLE_PERSONA['children']}）"
          f"—— 慢病 {'、'.join(c['name'] for c in KANGLE_PERSONA['conditions'])}。")
    print("健康指标为**合成演示数据**，只用于演示分诊链路，不是真人病历。")


async def _report_back(ctx, elder: dict, info: dict) -> None:
    """把刚灌进去的数读回来，用真规则再判一次档 —— 这才是"数据驱动档位"的证据。"""
    elder_id = elder["id"]
    grouped = await _grouped_history(ctx.repos, elder_id)
    conditions = await _active_conditions(ctx.repos, elder_id)
    overview = triage_overview(grouped, conditions)

    print(f"已灌入指标档案：{info['scenario']}，{info['readings']} 条读数、"
          f"{info['conditions']} 条慢病、{info['medications']} 种药，"
          f"覆盖最近 {info['days']} 天（{info['today']} 收尾）")
    print(f"读回库里的数再分诊 → 实际档位：{overview['level']}（剧本声明：{info['declared_level']}）")
    print(f"  {overview['headline']}")
    for r in overview["readings"]:
        trend = "" if r["trend"] == "平稳" else f"（最近{r['trend']}）"
        reason = f" — {r['reason']}" if r["reason"] else ""
        print(f"  · {r['label']} {r['display']}{trend}{reason}")
    if info["missed_days"]:
        print(f"  整天漏测（老人不是机器，答辩被问到就照实说）：{'、'.join(info['missed_days'])}")
    if overview["level"] != info["declared_level"]:
        print(f"  ！！档位与剧本声明不符：库里这些数跑出来是「{overview['level']}」而不是"
              f"「{info['declared_level']}」—— 别照着剧本讲，照屏幕上的讲。")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="灌入康乐演示数据（健康指标为合成演示数据）")
    switch = parser.add_mutually_exclusive_group()
    switch.add_argument("--scenario", default=None, choices=list(SCENARIOS),
                        help="额外灌入哪一份指标档案（ASCII 安全写法，如 --scenario emergency）")
    switch.add_argument("--level", default=None, choices=list(hr.LEVELS),
                        help="同上，按中文档位切（Windows 控制台中文参数易乱码，优先用 --scenario）")
    parser.add_argument("--days", type=int, default=30, help="档案天数，默认 30")
    parser.add_argument("--list", action="store_true", help="只列出四个剧本，不灌数据")
    args = parser.parse_args()

    if args.list:
        _print_scenarios()
        return

    scenario = resolve_scenario(args.scenario or args.level) if (args.scenario or args.level) else None
    if datetime.now().time() < _MORNING_READINGS_END:
        print("提醒：现在是清晨，今天那几条读数标在 06:41–07:41，比当前时刻晚，"
              "界面上会显示成未来时间。建议上午晚些或下午再跑一次。")

    ctx = build_context()
    result = await seed_demo(ctx.repos)
    print(f"演示数据已复位：{result['elder']['name']}（{result['elder']['id']}）— "
          f"{result['child']['name']}（{result['child']['id']}）")

    if scenario:
        info = await seed_kangle_persona(ctx.repos, result["elder"],
                                        scenario=scenario, days=args.days)
        await _report_back(ctx, result["elder"], info)


if __name__ == "__main__":
    asyncio.run(main())
