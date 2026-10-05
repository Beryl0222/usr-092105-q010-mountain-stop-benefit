"""季度公示：公共资产使用、维修负担、就业兑现与可分配收益分列呈现。

四个栏目各自独立计算、互不挤占：维修负担不冲抵就业兑现，
非货币贡献（导流、志愿工时）只作分配参考，不混入可分配金额。
"""
from __future__ import annotations

from datetime import datetime

from .state import LOCAL_TZ, current_holder, parse_ts

SECTION_KEYS = ("公共资产使用", "维修负担", "就业兑现", "可分配收益")


def quarter_range(quarter: str):
    """'2026Q3' -> (季度起, 季度止)，季度止为开区间。"""
    if len(quarter) != 6 or quarter[4] != "Q" or quarter[5] not in "1234":
        raise ValueError(f"季度格式应为 2026Q3，实际为：{quarter}")
    year, q = int(quarter[:4]), int(quarter[5])
    start = datetime(year, 3 * (q - 1) + 1, 1, tzinfo=LOCAL_TZ)
    end = datetime(year + (q == 4), 1 if q == 4 else 3 * q + 1, 1, tzinfo=LOCAL_TZ)
    return start, end


def build_disclosure(state, quarter: str) -> dict:
    """从事件投影计算季度公示四栏内容。"""
    start, end = quarter_range(quarter)

    def in_quarter(iso) -> bool:
        return start <= parse_ts(iso) < end

    # 一、公共资产使用：谁在用什么、是否到期未腾退、容量与负荷。
    asset_usage = []
    for asset in state.assets.values():
        terms = [t for t in state.terms.values() if t["asset_id"] == asset["asset_id"]]
        holder = current_holder(state, asset["asset_id"])
        current = next(
            (t for t in sorted(terms, key=lambda t: t["start"]) if t["operator"] == holder),
            None,
        )
        suspensions = [
            s
            for s in state.suspensions.values()
            if asset["asset_id"] in s["assets"] and in_quarter(s["occurred_at"])
        ]
        load = sum(
            1
            for c in state.commitments.values()
            if c["asset_id"] == asset["asset_id"] and c["status"] == "open"
        )
        if asset["suspended"]:
            status = "暂停中"
        elif any(t["status"] == "active" for t in terms):
            status = "在营"
        elif any(t["status"] == "expired" for t in terms):
            status = "到期未腾退"
        else:
            status = "闲置"
        asset_usage.append(
            {
                "资产": asset["label"],
                "类型": asset["kind"],
                "所在村": asset["village"],
                "状态": status,
                "当前许可": (
                    f"{current['operator']}（{current['start']} ~ {current['end']}）"
                    if current
                    else "无"
                ),
                "本期暂停": [f"{s['reason']}（{s['suspension_id']}）" for s in suspensions],
                "生态容量": dict(asset["capacity"]),
                "当前负荷": load,
            }
        )

    # 二、维修负担：每张工单必须有责任方，费用按分摊归集。
    orders = []
    burden = {}
    for w in state.work_orders.values():
        if in_quarter(w["opened_at"]) or (w["closed_at"] and in_quarter(w["closed_at"])):
            orders.append(
                {
                    "工单": w["work_order_id"],
                    "资产": state.assets[w["asset_id"]]["label"],
                    "问题": w["issue"],
                    "责任方": w["responsible"],
                    "状态": "已完工" if w["status"] == "closed" else "待处理",
                    "费用": w["cost"],
                    "分摊": dict(w["shares"]),
                }
            )
        if w["closed_at"] and in_quarter(w["closed_at"]):
            for party, amount in w["shares"].items():
                burden[party] = round(burden.get(party, 0) + amount, 2)

    # 三、就业兑现：许可里的承诺岗位对照实际录用记录。
    employment = []
    operators = sorted(
        {t["operator"] for t in state.terms.values()}
        | {c["contributor"] for c in state.contributions if c["kind"] == "就业兑现"}
    )
    for operator in operators:
        target = sum(
            t["employment_target"]
            for t in state.terms.values()
            if t["operator"] == operator and parse_ts(t["start"]) < end
        )
        fulfilled = sum(
            1
            for c in state.contributions
            if c["kind"] == "就业兑现"
            and c["contributor"] == operator
            and parse_ts(c["occurred_at"]) < end
        )
        employment.append(
            {
                "运营商": operator,
                "承诺岗位": target,
                "已兑现": fulfilled,
                "兑现率": f"{round(fulfilled / target * 100, 1)}%" if target else "无承诺",
            }
        )

    # 四、可分配收益：寄售净额减去共益基金承担的维修，
    # 退货与坏账只归集到实际参与方；导流与志愿工时单列，不混入金额。
    gross = round(sum(s["amount"] for s in state.sales.values() if in_quarter(s["occurred_at"])), 2)
    returns = [r for r in state.returns if in_quarter(r["occurred_at"])]
    debts = [d for d in state.bad_debts if in_quarter(d["occurred_at"])]
    returned = round(sum(r["amount"] for r in returns), 2)
    bad_debt = round(sum(d["amount"] for d in debts), 2)
    net = round(gross - returned - bad_debt, 2)
    fund_maintenance = burden.get("共益基金", 0)
    distributable = max(0.0, round(net - fund_maintenance, 2))

    attributed = {}
    for flow in returns + debts:
        share = round(flow["amount"] / len(flow["participants"]), 2)
        for party in flow["participants"]:
            attributed[party] = round(attributed.get(party, 0) + share, 2)

    referrals = [
        c for c in state.contributions if c["kind"] == "导流" and in_quarter(c["occurred_at"])
    ]
    volunteer_hours = sum(
        c.get("hours", 0)
        for c in state.contributions
        if c["kind"] == "志愿班次" and in_quarter(c["occurred_at"])
    )
    allocated = {}
    for a in state.allocations:
        if a["quarter"] == quarter:
            allocated[a["party"]] = round(allocated.get(a["party"], 0) + a["amount"], 2)

    income = {
        "寄售销售额": gross,
        "退货扣减": returned,
        "坏账扣减": bad_debt,
        "寄售净额": net,
        "维修基金支出": fund_maintenance,
        "可分配总额": distributable,
        "退货坏账归集": attributed,
        "非货币贡献": {"导流笔数": len(referrals), "志愿工时": volunteer_hours},
        "已分配": allocated,
        "剩余可分配": round(distributable - sum(allocated.values()), 2),
    }

    return {
        "公共资产使用": asset_usage,
        "维修负担": {"工单": orders, "责任方汇总": burden},
        "就业兑现": employment,
        "可分配收益": income,
    }
