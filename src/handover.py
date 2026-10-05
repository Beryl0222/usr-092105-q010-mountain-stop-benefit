"""运营商退出交割清单构建。

退出请求发生时，系统调用 :func:`build_handover_checklist` 快照全部未结合同责任，
生成稳定编号的阻断项（blocker）。审计器据此核验：
- 清单生成时不得遗漏任何未结合同责任；
- 每项阻断必须凭清偿证据解除；
- 交割完成前，设备离场、新收款、新收货一律被阻止。
"""

def _bid(kind: str, ref: str) -> str:
    return f"B-{kind}-{ref}"


def build_handover_checklist(state: dict, term_id: str) -> dict:
    """依据审计投影当前状态，重建某 term 的交割清单。"""
    term = state["terms"].get(term_id)
    blockers: list[dict] = []

    # 1. 未结清寄售库存与货款（库存与坏账只认批次实际参与方）
    open_consignments = []
    for bid, batch in state["batches"].items():
        if batch["term_id"] != term_id:
            continue
        owed = batch["sold_proceeds"] - batch["supplier_borne_bad_debt"]
        open_consignments.append({
            "batch_id": bid,
            "supplier_party_id": batch["supplier"],
            "seller_party_id": batch["seller"],
            "quantity_on_hand": batch["delivered"] - batch["sold"] - batch["returned"],
            "owed_to_supplier_cents": owed,
            "settled": batch["settled"],
        })
        if not batch["settled"]:
            blockers.append({
                "blocker_id": _bid("inv", bid),
                "kind": "unsettled_consignment",
                "ref": bid,
                "detail": "寄售批次未与农户结清或退货，未清库存不得带离合同期",
            })

    # 2. 未兑现、未退款的旅客预付款
    open_prepayments = []
    for pid, prep in state["prepayments"].items():
        if prep["term_id"] != term_id or prep["status"] != "open":
            continue
        open_prepayments.append({
            "prepayment_id": pid,
            "guest_ref": prep["guest_ref"],
            "amount_cents": prep["amount_cents"],
            "due_date": prep["due_date"],
        })
        blockers.append({
            "blocker_id": _bid("pay", pid),
            "kind": "open_prepayment",
            "ref": pid,
            "detail": "旅客预付款未兑现也未退款，不得随运营商离场",
        })

    # 3. 仍在场的设备（区分可搬离的运营商设备与公共/集体资产）
    equipment_to_clear = []
    for aid, asset in state["assets"].items():
        if aid not in term.get("asset_ids", set()) and asset.get("present_at") not in term.get("asset_ids", set()):
            continue
        if asset.get("present") is False:
            continue
        equipment_to_clear.append({
            "asset_id": aid,
            "asset_kind": asset["kind"],
            "owner": asset["owner"],
            "removable": bool(asset.get("removable")),
        })
        blockers.append({
            "blocker_id": _bid("eqp", aid),
            "kind": "equipment_on_site",
            "ref": aid,
            "detail": ("可搬离设备须登记放行；公共/集体资产须交还，"
                       "不得在交割完成前悄悄搬离"),
        })

    # 4. 未关闭维修工单
    open_repairs = []
    for rid, order in state["repairs"].items():
        if order["asset_id"] in term.get("asset_ids", set()) and not order.get("completed"):
            open_repairs.append({"repair_order_id": rid, "fault": order["fault"]})
            blockers.append({
                "blocker_id": _bid("rep", rid),
                "kind": "open_repair",
                "ref": rid,
                "detail": "维修工单未完工或负担未结清",
            })

    # 5. 未核销导流（退出运营商作为来源方的未结案线索，证据未成立不得带进分配）
    operator_id = term["party_id"] if term else None
    unverified_referrals = [
        {"referral_id": rid, "evidence_ref": r["evidence_ref"]}
        for rid, r in state["referrals"].items()
        if r["status"] == "recorded"
        and (r["source_party"] == operator_id or r["target_party"] == operator_id)
    ]
    for item in unverified_referrals:
        blockers.append({
            "blocker_id": _bid("ref", item["referral_id"]),
            "kind": "unverified_referral",
            "ref": item["referral_id"],
            "detail": "导流证据未经入住核销，退出时按驳回处理，不得计入贡献",
        })

    # 6. 就业承诺缺口
    pledge = next((p for p in state["pledges"] if p["term_id"] == term_id), None)
    pledge_status = None
    if pledge:
        gap = max(0, pledge["positions_total"] - pledge["hires_total"]), \
              max(0, pledge["local_min"] - pledge["hires_local"])
        pledge_status = {
            "positions_promised": pledge["positions_total"],
            "positions_delivered": pledge["hires_total"],
            "local_promised": pledge["local_min"],
            "local_delivered": pledge["hires_local"],
            "positions_gap": gap[0],
            "local_gap": gap[1],
        }
        if not pledge.get("reported"):
            blockers.append({
                "blocker_id": _bid("plt", term_id),
                "kind": "employment_unreported",
                "ref": term_id,
                "detail": "退出前未提交季度就业兑现与工资凭证",
            })
        elif gap[0] > 0 or gap[1] > 0:
            blockers.append({
                "blocker_id": _bid("plt", term_id),
                "kind": "employment_shortfall",
                "ref": term_id,
                "detail": "就业承诺岗位或本地用工存在缺口，须在分配中补足或说明",
            })

    # 7. 数据责任（必有项）
    data_responsibilities = [
        "预付款台账与旅客联系方式",
        "寄售批次、农户结算与退货记录",
        "导流凭证与核销记录",
        "公共资产使用与维修记录",
        "会员与营销数据（须按合同删除或移交，不得擅自带走）",
    ]
    blockers.append({
        "blocker_id": _bid("dat", term_id),
        "kind": "data_handover",
        "ref": term_id,
        "detail": "经营数据责任未签署移交/销毁确认",
    })

    return {
        "term_id": term_id,
        "operator_party_id": term["party_id"] if term else None,
        "assets_to_return": sorted(term.get("asset_ids", set())) if term else [],
        "open_consignments": open_consignments,
        "open_prepayments": open_prepayments,
        "equipment_to_clear": equipment_to_clear,
        "open_repairs": open_repairs,
        "unverified_referrals": unverified_referrals,
        "pledge_status": pledge_status,
        "data_responsibilities": data_responsibilities,
        "blockers": blockers,
    }
