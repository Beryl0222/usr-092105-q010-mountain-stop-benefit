"""运营商退出：交割清单生成与清结核对。

清单完全由事件账投影计算，任何一项未清结，退出都无法确认——
未清库存、预付款、设备与数据责任不会被悄悄带出合同期。
"""
from .state import current_holder

# 只能凭回执核销的事项；其余事项必须通过对应业务操作清结，不可直接核销。
ATTESTABLE = {"数据交接"}


def build_checklist(state, operator: str) -> list[dict]:
    """按当前账本计算运营商的交割清单，每项给出待办明细。"""
    items = []

    remaining = {k: q for k, q in state.stock.items() if q > 0 and k[1] == operator}
    items.append(
        {
            "key": "库存清结",
            "open": bool(remaining),
            "detail": [
                f"{asset}·{producer}·{item} 余 {qty}"
                for (asset, _op, producer, item), qty in sorted(remaining.items())
            ],
            "cleared_by": None,
        }
    )

    prepaid = [
        c
        for c in state.commitments.values()
        if c["status"] == "open"
        and c.get("prepaid", 0) > 0
        and current_holder(state, c["asset_id"]) == operator
    ]
    items.append(
        {
            "key": "预付款清结",
            "open": bool(prepaid),
            "detail": [f"{c['guest']} 预付款 {c['prepaid']} 元" for c in prepaid],
            "cleared_by": None,
        }
    )

    equipment = [
        (asset_id, equipment_id)
        for asset_id, asset in state.assets.items()
        for equipment_id, eq in asset["equipment"].items()
        if eq["owner"] == operator
    ]
    items.append(
        {
            "key": "设备移除",
            "open": bool(equipment),
            "detail": [f"{asset_id} 上的 {equipment_id}" for asset_id, equipment_id in equipment],
            "cleared_by": None,
        }
    )

    data_evidence = state.exit_clearances.get((operator, "数据交接"))
    items.append(
        {
            "key": "数据交接",
            "open": data_evidence is None,
            "detail": [] if data_evidence else ["旅客与交易数据尚未移交村集体"],
            "cleared_by": data_evidence,
        }
    )

    orders = [
        w
        for w in state.work_orders.values()
        if w["status"] == "open" and w["responsible"] == operator
    ]
    items.append(
        {
            "key": "维修工单清结",
            "open": bool(orders),
            "detail": [f"{w['work_order_id']}：{w['issue']}" for w in orders],
            "cleared_by": None,
        }
    )

    terms = [
        t
        for t in state.terms.values()
        if t["operator"] == operator and t["status"] in ("active", "expired")
    ]
    items.append(
        {
            "key": "许可腾退",
            "open": bool(terms),
            "detail": [f"{t['term_id']}（{t['asset_id']}）" for t in terms],
            "cleared_by": None,
        }
    )
    return items
