"""共益运营事件流的持续审计投影。

把事件日志折叠成可审计状态，并在折叠过程中逐条核对不变量。
所有问题以中文违规项返回（``violations``），任何接入方都可以拿同一事件流
独立复算——这就是“持续可审计”的含义：结论只依赖事件，不依赖某个运营商自报。

关键不变量：
1. 许可到期不得继续使用公共资产；季节许可不超过 180 天，到期重新竞价/轮换。
2. 导流贡献必须有凭证并经入住核销；跨村结算只承认已核销证据。
3. 寄售退货退回实际供货农户；坏账只落到批次实际参与方（销售方或农户自认）。
4. 暴雨/检修/超载只暂停受影响节点、受影响业务；已入住旅客承诺逐一兑现后才解封。
5. 维修工单 72 小时内必须有人认领；财政资产维修同样要落责任、落分摊。
6. 退出先出交割清单；清单生成前设备、款项、货物冻结；全部阻断项清偿后才完成交割。
"""

from datetime import datetime, timedelta
from typing import Any

from src.catalog import RULES
from src.handover import build_handover_checklist


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _quarter(value: datetime) -> str:
    return f"{value.year}Q{(value.month - 1) // 3 + 1}"


def _initial_state() -> dict[str, Any]:
    return {
        "events_by_id": {},          # event_id -> 事件（幂等重放检测）
        "next_version": {},          # aggregate_id -> 下一期望版本
        "assets": {},                # asset_id -> 资产现状
        "terms": {},                 # term_id -> 许可现状
        "permits": [],               # 摊位许可
        "repairs": {},               # repair_order_id -> 工单
        "batches": {},               # consignment batch
        "prepayments": {},           # 预付款
        "referrals": {},            # 导流
        "contributions": [],        # 跨村贡献
        "shifts": {},
        "pledges": [],
        "capacities": {},           # node -> cap
        "overcap_reports": {},      # (node, date) -> load，待超载宣布核销
        "overloads": {},            # node -> {active, declared_date, suspension_seen}
        "suspensions": {},          # aggregate_id -> 暂停
        "notices": [],
        "allocations": {},          # benefit_distribution aggregate
        "handovers_by_term": {},    # term_id -> 已正式生成的交割清单
        "pending_handovers": {},    # term_id -> 退出请求时的系统快照（待 HANDOVER_LIST_GENERATED 确认）
        "handover_alias": {},       # handover aggregate_id -> term_id
        "resolved_blockers": {},    # handover aggregate_id -> set(blocker_id)
        "as_of": None,
        "violations": [],
    }


class _Audit:
    def __init__(self) -> None:
        self.s = _initial_state()

    def fail(self, code: str, message: str, event_id: str) -> None:
        self.s["violations"].append({"code": code, "message": message, "event_id": event_id})

    # —— 通用查询 ——
    def _active_suspensions(self, at: datetime) -> list[dict]:
        out = []
        for sus in self.s["suspensions"].values():
            ended = sus.get("ended_at")
            if sus["starts_at"] <= at and (ended is None or at < ended):
                out.append(sus)
        return out

    def _assert_not_suspended(self, at: datetime, asset_ids, services: set[str],
                              event_id: str, what: str) -> None:
        for sus in self._active_suspensions(at):
            if sus["scope_assets"] & set(asset_ids) and sus["service_kinds"] & services:
                self.fail(
                    "SUSPENSION_VIOLATION",
                    f"{what} 撞上暂停 {sus['reason']}（{sorted(sus['scope_assets'] & set(asset_ids))}）"
                    f"：该业务在暂停范围内，不得发生；已入住旅客承诺不受影响",
                    event_id,
                )

    # —— 主入口 ——
    def fold(self, events: list[dict]) -> dict:
        for event in events:
            self._apply(event)
        self._end_of_log_checks()
        return self.s

    def _apply(self, event: dict) -> None:
        eid = event["event_id"]
        if eid in self.s["events_by_id"]:
            if self.s["events_by_id"][eid] != event:
                self.fail("EVENT_CONFLICT",
                          f"事件标识 {eid} 重放但内容不一致，重试必须沿用原事件与原内容", eid)
            return  # 幂等重放：不再产生副作用

        agg_id = event["aggregate_id"]
        expected = self.s["next_version"].get(agg_id, 1)
        if event["version"] != expected:
            self.fail("VERSION_GAP",
                      f"{agg_id} 版本应为 {expected}，实际收到 {event['version']}：事件流断档或乱序",
                      eid)
        self.s["next_version"][agg_id] = event["version"] + 1
        self.s["events_by_id"][eid] = event
        self.s["as_of"] = _dt(event["occurred_at"])

        handler = getattr(self, f"_on_{event['event_type'].lower()}", None)
        if handler:
            handler(event)

    # ================= 公共资产 =================
    def _on_asset_registered(self, e: dict) -> None:
        p = e["payload"]
        aid = e["aggregate_id"]
        if aid in self.s["assets"]:
            self.fail("ASSET_DUPLICATE", f"公共资产 {aid} 重复登记", e["event_id"])
            return
        self.s["assets"][aid] = {
            "kind": p["asset_kind"], "village": p["village"], "owner": p["owner"],
            "funded_by": p["funded_by"], "location": p["location_name"],
            "maintenance_responsible_party": p["maintenance_responsible_party"],
            "present": True, "present_at": p.get("present_at_asset_id", aid),
            "removable": p.get("removable", False),
        }

    def _on_asset_usage_recorded(self, e: dict) -> None:
        p, aid = e["payload"], e["aggregate_id"]
        asset = self.s["assets"].get(p["asset_id"])
        term = self.s["terms"].get(p["term_id"])
        if asset is None:
            self.fail("UNKNOWN_ASSET", f"使用记录指向未登记资产 {p['asset_id']}", e["event_id"])
        if term is None:
            self.fail("UNKNOWN_TERM", f"使用记录指向不存在的许可 {p['term_id']}", e["event_id"])
            return
        if p["asset_id"] not in term["asset_ids"]:
            self.fail("ASSET_NOT_IN_TERM",
                      f"资产 {p['asset_id']} 不在许可 {p['term_id']} 范围内：不得借许可占用院外公共资产",
                      e["event_id"])
        start, end = _dt(p["used_from"]), _dt(p["used_to"])
        if end <= start:
            self.fail("BAD_TIME", "使用记录 used_to 必须晚于 used_from", e["event_id"])
        outside = start < term["starts_at"] or end > term["ends_at"]
        if outside:
            self.fail("USAGE_OUTSIDE_TERM",
                      f"{p['party_id']} 对 {p['asset_id']} 的使用（{p['used_from']}~{p['used_to']}）"
                      f"超出许可期限 {p['term_id']}：到期不能沉淀成永久占用",
                      e["event_id"])
        elif term["status"] != "active":
            # 时间窗在期限内、但许可已被提前撤销
            self.fail("USAGE_AFTER_TERM_END",
                      f"许可 {p['term_id']} 已 {term['status']}，其后不得再记录公共资产使用",
                      e["event_id"])

    def _asset_exit_gate(self, e: dict, asset_id: str) -> str | None:
        """设备离场/交还的退出冻结检查，返回受影响 term_id。"""
        asset = self.s["assets"].get(asset_id, {})
        for term_id, term in self.s["terms"].items():
            if term.get("exit_requested_at") is None:
                continue
            in_term = (asset_id in term["asset_ids"]
                       or asset.get("present_at") in term["asset_ids"])
            if not in_term:
                continue
            ho = self.s["handovers_by_term"].get(term_id)
            if ho is None:
                self.fail("EXIT_FREEZE",
                          f"{term_id} 已提出退出但交割清单尚未正式生成，{asset_id} 一律冻结，"
                          "不得搬离或交还", e["event_id"])
                return term_id
            listed = {x["asset_id"] for x in ho["checklist"]["equipment_to_clear"]}
            if asset_id not in listed:
                self.fail("EQUIPMENT_NOT_LISTED",
                          f"{asset_id} 不在交割清单内，不得离场；清单之外的设备流出都属于私带",
                          e["event_id"])
            return term_id
        return None

    def _on_asset_returned(self, e: dict) -> None:
        p = e["payload"]
        asset = self.s["assets"].get(p["asset_id"])
        if asset is None:
            self.fail("UNKNOWN_ASSET", f"交还未登记资产 {p['asset_id']}", e["event_id"])
            return
        self._asset_exit_gate(e, p["asset_id"])
        asset["present"] = False

    def _on_asset_removed(self, e: dict) -> None:
        p = e["payload"]
        asset = self.s["assets"].get(e["aggregate_id"])
        if asset is None:
            self.fail("UNKNOWN_ASSET", f"搬离未登记资产 {e['aggregate_id']}", e["event_id"])
            return
        self._asset_exit_gate(e, e["aggregate_id"])
        asset["present"] = False

    # ================= 经营许可 =================
    def _on_term_granted(self, e: dict) -> None:
        p, tid = e["payload"], e["aggregate_id"]
        if tid in self.s["terms"]:
            self.fail("TERM_DUPLICATE", f"许可 {tid} 重复授予", e["event_id"])
            return
        starts, ends = _dt(p["starts_at"]), _dt(p["ends_at"])
        for aid in p["asset_ids"]:
            if aid not in self.s["assets"]:
                self.fail("UNKNOWN_ASSET", f"许可 {tid} 指向未登记资产 {aid}", e["event_id"])
            for other_id, other in self.s["terms"].items():
                if other["status"] != "active" or aid not in other["asset_ids"]:
                    continue
                if starts < other["ends_at"] and other["starts_at"] < ends:
                    self.fail("TERM_OVERLAP",
                              f"资产 {aid} 在 {other_id} 许可期内又被授给 {tid}："
                              "同一公共资产不得同时挂两本许可", e["event_id"])
        self.s["terms"][tid] = {
            "party_id": p["party_id"], "village": p["village"], "scope": p["scope"],
            "asset_ids": list(p["asset_ids"]), "starts_at": starts, "ends_at": ends,
            "seasonal": p["seasonal"], "grant_basis": p["grant_basis"],
            "status": "active", "exit_requested_at": None,
        }

    def _close_term(self, e: dict, status: str) -> None:
        term = self.s["terms"].get(e["aggregate_id"])
        if term is None:
            self.fail("UNKNOWN_TERM", f"{e['event_type']} 指向不存在的许可", e["event_id"])
            return
        if term["status"] != "active":
            self.fail("TERM_NOT_ACTIVE",
                      f"许可 {e['aggregate_id']} 当前状态 {term['status']}，不能再 {status}",
                      e["event_id"])
            return
        term["status"] = status

    def _on_term_expired(self, e: dict) -> None:
        self._close_term(e, "expired")

    def _on_term_revoked(self, e: dict) -> None:
        self._close_term(e, "revoked")

    def _on_operator_exited(self, e: dict) -> None:
        tid = e["aggregate_id"]
        term = self.s["terms"].get(tid)
        if term is None:
            self.fail("UNKNOWN_TERM", "退出请求指向不存在的许可", e["event_id"])
            return
        if term.get("exit_requested_at") is not None:
            self.fail("EXIT_DUPLICATE", f"{tid} 已在退出流程中", e["event_id"])
            return
        term["exit_requested_at"] = _dt(e["payload"]["requested_at"])
        # 退出请求发生时系统即时快照全部未结合同责任；在 HANDOVER_LIST_GENERATED
        # 正式确认前，设备、款项、货物一律冻结。
        checklist = build_handover_checklist(self.s, tid)
        self.s["pending_handovers"][tid] = {
            "handover_id": None, "term_id": tid,
            "generated_event_id": e["event_id"], "checklist": checklist,
        }

    def _published_handover(self, term_id: str) -> dict | None:
        return self.s["handovers_by_term"].get(term_id) or \
            self.s["pending_handovers"].get(term_id)

    # ================= 预付款 =================
    def _on_prepayment_received(self, e: dict) -> None:
        p = e["payload"]
        term = self.s["terms"].get(p["term_id"])
        if term is None:
            self.fail("UNKNOWN_TERM", f"预付款挂在不存在的许可 {p['term_id']}", e["event_id"])
            return
        if term.get("exit_requested_at"):
            self.fail("EXIT_FREEZE",
                      f"{p['term_id']} 已进入退出流程，不得再收取旅客预付款 {p['prepayment_id']}",
                      e["event_id"])
        if p["service_kind"] == "stay":
            self._assert_not_suspended(
                _dt(e["occurred_at"]), term["asset_ids"], {"new_booking"},
                e["event_id"], f"新增住宿预订 {p['prepayment_id']}")
        self.s["prepayments"][p["prepayment_id"]] = {
            "term_id": p["term_id"], "guest_ref": p["guest_ref"],
            "amount_cents": p["amount_cents"], "service_kind": p["service_kind"],
            "due_date": p["due_date"], "status": "open",
        }

    def _prepayment_transition(self, e: dict, status: str) -> None:
        pid = e["payload"]["prepayment_id"]
        prep = self.s["prepayments"].get(pid)
        if prep is None:
            self.fail("UNKNOWN_PREPAYMENT", f"预付款 {pid} 不存在", e["event_id"])
            return
        if prep["status"] != "open":
            self.fail("PREPAYMENT_STATE",
                      f"预付款 {pid} 已 {prep['status']}，不能重复处理", e["event_id"])
            return
        prep["status"] = status

    def _on_prepayment_fulfilled(self, e: dict) -> None:
        self._prepayment_transition(e, "fulfilled")

    def _on_prepayment_refunded(self, e: dict) -> None:
        self._prepayment_transition(e, "refunded")

    # ================= 摊位 =================
    def _on_stall_permit_issued(self, e: dict) -> None:
        p = e["payload"]
        site = self.s["assets"].get(p["site_asset_id"])
        if site is None or site["kind"] != "stall_site":
            self.fail("BAD_STALL_SITE",
                      f"摊位许可 {e['aggregate_id']} 必须落在已登记的 stall_site 点位上",
                      e["event_id"])
        starts, ends = _dt(p["starts_at"]), _dt(p["ends_at"]),
        if ends <= starts:
            self.fail("BAD_TIME", "摊位许可结束时间必须晚于开始时间", e["event_id"])
        elif (ends - starts).days > RULES["max_seasonal_term_days"]:
            self.fail("SEASON_TOO_LONG",
                      f"摊位许可最长 {RULES['max_seasonal_term_days']} 天，"
                      "季节一过点位必须让出，不得跨年占用", e["event_id"])
        for old in self.s["permits"]:
            if old["site_asset_id"] != p["site_asset_id"] or old.get("closed_at"):
                continue
            if starts < old["ends_at"] and old["starts_at"] < ends:
                self.fail("STALL_OVERLAP",
                          f"点位 {p['site_asset_id']} 上一季节许可未撤场核验，不能发新许可",
                          e["event_id"])
        self.s["permits"].append({
            "permit_id": e["aggregate_id"], **{k: p[k] for k in
            ("site_asset_id", "party_id", "village")},
            "starts_at": starts, "ends_at": ends, "closed_at": None,
        })

    def _on_stall_closed(self, e: dict) -> None:
        p = e["payload"]
        for permit in reversed(self.s["permits"]):
            if permit["site_asset_id"] == p["site_asset_id"] and permit.get("closed_at") is None:
                permit["closed_at"] = _dt(p["closed_at"])
                return
        self.fail("NO_OPEN_STALL", f"点位 {p['site_asset_id']} 没有在营摊位可关闭",
                  e["event_id"])

    # ================= 寄售 =================
    def _on_consignment_delivered(self, e: dict) -> None:
        p, bid = e["payload"], e["aggregate_id"]
        term = self.s["terms"].get(p["term_id"])
        if term is None:
            self.fail("UNKNOWN_TERM", f"寄售批次挂在不存在的许可 {p['term_id']}", e["event_id"])
            return
        at = _dt(p["delivered_at"])
        if term["status"] != "active":
            self.fail("CONSIGNMENT_TO_CLOSED_TERM",
                      f"许可 {p['term_id']} 已 {term['status']}，不得再收寄售货物",
                      e["event_id"])
        if term.get("exit_requested_at"):
            self.fail("EXIT_FREEZE",
                      "退出流程中不得再收新寄售批次，避免库存被带进合同期外", e["event_id"])
        if at < term["starts_at"] or at > term["ends_at"]:
            self.fail("USAGE_OUTSIDE_TERM",
                      f"寄售批次 {bid} 交付时间超出许可期限", e["event_id"])
        self.s["batches"][bid] = {
            "term_id": p["term_id"], "supplier": p["supplier_party_id"],
            "seller": p["seller_party_id"], "village": p["village"],
            "delivered": p["quantity"], "sold": 0, "returned": 0,
            "sold_proceeds": 0, "commission_total": 0, "bad_debt_total": 0,
            "supplier_borne_bad_debt": 0, "seller_borne_bad_debt": 0,
            "unsold_policy": p["unsold_policy"], "settled": False,
        }

    def _batch(self, e: dict) -> dict | None:
        bid = e["aggregate_id"]
        batch = self.s["batches"].get(bid)
        if batch is None:
            self.fail("UNKNOWN_BATCH", f"寄售批次 {bid} 不存在", e["event_id"])
        elif batch["settled"]:
            self.fail("BATCH_SETTLED", f"批次 {bid} 已结清，之后不得再发生变动", e["event_id"])
        return batch

    def _on_consignment_sold(self, e: dict) -> None:
        p = e["payload"]
        batch = self._batch(e)
        if batch is None:
            return
        if batch["sold"] + batch["returned"] + p["quantity"] > batch["delivered"]:
            self.fail("CONSIGNMENT_OVERSELL",
                      f"批次 {e['aggregate_id']} 售出/退货数量超过交付数量，库存对不上",
                      e["event_id"])
        if p["commission_cents"] > p["gross_cents"]:
            self.fail("BAD_COMMISSION", "单笔记售佣金不得超过销售总额", e["event_id"])
        pos = p.get("point_of_sale_asset_id")
        services = {"consignment_sale"}
        if pos and self.s["assets"].get(pos, {}).get("kind") == "stall_site":
            services.add("stall_sale")
        if pos:
            self._assert_not_suspended(_dt(p["sold_at"]), [pos], services,
                                       e["event_id"], f"寄售销售 {p['order_ref']}")
        batch["sold"] += p["quantity"]
        batch["sold_proceeds"] += p["gross_cents"]
        batch["commission_total"] += p["commission_cents"]

    def _on_consignment_returned(self, e: dict) -> None:
        p = e["payload"]
        bid = e["aggregate_id"]
        batch = self._batch(e)
        if batch is None:
            return
        if batch["sold"] + batch["returned"] + p["quantity"] > batch["delivered"]:
            self.fail("CONSIGNMENT_OVERRETURN",
                      f"批次 {bid} 退货数量超过未售库存", e["event_id"])
        batch["returned"] += p["quantity"]

    def _on_consignment_bad_debt(self, e: dict) -> None:
        p = e["payload"]
        bid = e["aggregate_id"]
        batch = self._batch(e)
        if batch is None:
            return
        responsible = p["responsible_party_id"]
        if p["basis"] == "supplier_agreed_risk":
            if responsible != batch["supplier"]:
                self.fail("BAD_DEBT_WRONG_PARTY",
                          f"批次 {e['aggregate_id']} 的 supplier_agreed_risk 坏账只能由实际供货农户"
                          f"{batch['supplier']} 自认，不能摊给 {responsible}", e["event_id"])
                return
            batch["supplier_borne_bad_debt"] += p["amount_cents"]
        else:
            if responsible != batch["seller"]:
                self.fail("BAD_DEBT_WRONG_PARTY",
                          f"批次 {e['aggregate_id']} 的 {p['basis']} 坏账由销售风险产生，"
                          f"只能归实际销售方 {batch['seller']}，不能从农户货款里扣",
                          e["event_id"])
                return
            batch["seller_borne_bad_debt"] += p["amount_cents"]
        if batch["bad_debt_total"] + p["amount_cents"] > batch["sold_proceeds"]:
            self.fail("BAD_DEBT_OVERSIZE",
                      f"批次 {e['aggregate_id']} 坏账累计超过实际销售额", e["event_id"])
        batch["bad_debt_total"] += p["amount_cents"]

    def _on_consignment_settled(self, e: dict) -> None:
        p = e["payload"]
        batch = self.s["batches"].get(e["aggregate_id"])
        if batch is None:
            self.fail("UNKNOWN_BATCH", f"批次 {e['aggregate_id']} 不存在", e["event_id"])
            return
        supplier_due = (batch["sold_proceeds"] - batch["commission_total"]
                        - batch["supplier_borne_bad_debt"])
        if p["paid_cents"] != supplier_due:
            self.fail("SETTLE_AMOUNT_MISMATCH",
                      f"批次 {e['aggregate_id']} 应付农户 {supplier_due} 分"
                      f"（销售额−佣金−农户自认坏账），实记 {p['paid_cents']} 分："
                      "销售方坏账不得从农户货款中扣", e["event_id"])
        batch["settled"] = True

    # ================= 导流 =================
    def _on_referral_recorded(self, e: dict) -> None:
        p, rid = e["payload"], e["aggregate_id"]
        node = self.s["assets"].get(p["node_asset_id"])
        if node is None:
            self.fail("UNKNOWN_ASSET", f"导流 {rid} 指向未登记道路节点", e["event_id"])
        if p["source_party_id"] == p["target_party_id"]:
            self.fail("SELF_REFERRAL", "导流来源与承接方不能是同一经营者", e["event_id"])
        self._assert_not_suspended(
            _dt(p["recorded_at"]), [p["node_asset_id"]], {"new_referral"},
            e["event_id"], f"新增导流 {rid}")
        self.s["referrals"][rid] = {
            "source_party": p["source_party_id"], "source_village": p["source_village"],
            "target_party": p["target_party_id"], "target_village": p["target_village"],
            "node": p["node_asset_id"], "guest_ref": p["guest_ref"],
            "evidence_ref": p["evidence_ref"], "status": "recorded",
        }

    def _on_referral_verified(self, e: dict) -> None:
        p = e["payload"]
        ref = self.s["referrals"].get(p["referral_id"])
        if ref is None:
            self.fail("UNKNOWN_REFERRAL", f"导流 {p['referral_id']} 不存在", e["event_id"])
            return
        if ref["status"] != "recorded":
            self.fail("REFERRAL_STATE",
                      f"导流 {p['referral_id']} 已 {ref['status']}，不能重复核销", e["event_id"])
            return
        ref["status"] = "verified"
        ref["booking_id"] = p["booking_id"]
        ref["payout_cents"] = p["payout_cents"]

    def _on_referral_rejected(self, e: dict) -> None:
        p = e["payload"]
        ref = self.s["referrals"].get(p["referral_id"])
        if ref is None:
            self.fail("UNKNOWN_REFERRAL", f"导流 {p['referral_id']} 不存在", e["event_id"])
            return
        if ref["status"] != "recorded":
            self.fail("REFERRAL_STATE",
                      f"导流 {p['referral_id']} 已结案，不能再驳回", e["event_id"])
            return
        ref["status"] = "rejected"

    # ================= 跨村贡献边界 =================
    def _on_service_recorded(self, e: dict) -> None:
        p = e["payload"]
        if not p.get("evidence_refs"):
            self.fail("CONTRIBUTION_NO_EVIDENCE",
                      "跨村贡献交换必须附证据，没有凭证的贡献不得进入村际结算", e["event_id"])
        if p["contribution_kind"] == "cross_village_referral":
            for ref in p["evidence_refs"]:
                rec = self.s["referrals"].get(ref)
                if rec is None or rec["status"] != "verified":
                    self.fail("CONTRIBUTION_UNVERIFIED_REFERRAL",
                              f"跨村导流贡献证据 {ref} 未经入住核销（或不存在），"
                              "运营商不能把别人的营业混作自己的导流贡献", e["event_id"])
        self.s["contributions"].append({"payload": p, "event_id": e["event_id"]})

    # ================= 志愿班次 =================
    def _on_shift_scheduled(self, e: dict) -> None:
        p = e["payload"]
        if p["node_asset_id"] not in self.s["assets"]:
            self.fail("UNKNOWN_ASSET", f"班次挂在未登记节点 {p['node_asset_id']}", e["event_id"])
        self.s["shifts"][p["shift_id"]] = {"status": "scheduled", **p}

    def _on_shift_fulfilled(self, e: dict) -> None:
        p = e["payload"]
        shift = self.s["shifts"].get(p["shift_id"])
        if shift is None:
            self.fail("UNKNOWN_SHIFT", f"班次 {p['shift_id']} 不存在", e["event_id"])
            return
        if shift["status"] != "scheduled":
            self.fail("SHIFT_STATE", f"班次 {p['shift_id']} 已 {shift['status']}", e["event_id"])
        shift["status"] = "fulfilled"
        shift["evidence_ref"] = p["evidence_ref"]

    def _on_shift_cancelled(self, e: dict) -> None:
        p = e["payload"]
        shift = self.s["shifts"].get(p["shift_id"])
        if shift is None:
            self.fail("UNKNOWN_SHIFT", f"班次 {p['shift_id']} 不存在", e["event_id"])
            return
        shift["status"] = "cancelled"

    # ================= 就业承诺 =================
    def _pledge(self, term_id: str) -> dict | None:
        return next((p for p in self.s["pledges"] if p["term_id"] == term_id), None)

    def _on_pledge_made(self, e: dict) -> None:
        p = e["payload"]
        if p["local_positions_min"] > p["positions_total"]:
            self.fail("BAD_PLEDGE", "本地用工下限不能高于承诺总岗位", e["event_id"])
        if self._pledge(p["term_id"]) is not None:
            self.fail("PLEDGE_DUPLICATE", f"{p['term_id']} 已有就业承诺", e["event_id"])
            return
        self.s["pledges"].append({
            "term_id": p["term_id"], "operator": p["operator_party_id"],
            "positions_total": p["positions_total"], "local_min": p["local_positions_min"],
            "wage_min_cents": p["wage_min_cents"],
            "hires_total": 0, "hires_local": 0, "reported": False,
        })

    def _on_pledge_fulfilled(self, e: dict) -> None:
        p = e["payload"]
        pledge = self._pledge(p["term_id"])
        if pledge is None:
            self.fail("UNKNOWN_PLEDGE", f"{p['term_id']} 没有就业承诺可兑现", e["event_id"])
            return
        if p["hires_local"] > p["hires_total"]:
            self.fail("BAD_PLEDGE", "本地用工数不能大于总用工数", e["event_id"])
        pledge["hires_total"] = p["hires_total"]
        pledge["hires_local"] = p["hires_local"]
        pledge["reported"] = True
        if p["hires_total"] < pledge["positions_total"]:
            self.fail("PLEDGE_GAP",
                      f"{p['term_id']} 就业岗位兑现不足：承诺 {pledge['positions_total']}，"
                      f"实际 {p['hires_total']}", e["event_id"])
        if p["hires_local"] < pledge["local_min"]:
            self.fail("PLEDGE_LOCAL_GAP",
                      f"{p['term_id']} 本地用工兑现不足：承诺 {pledge['local_min']}，"
                      f"实际 {p['hires_local']}", e["event_id"])

    def _on_pledge_shortfall(self, e: dict) -> None:
        p = e["payload"]
        pledge = self._pledge(p["term_id"])
        if pledge is None:
            self.fail("UNKNOWN_PLEDGE", "缺口申报对应不到就业承诺", e["event_id"])
            return
        pledge["shortfall_note"] = p["note"]

    # ================= 生态容量与超载 =================
    def _on_capacity_defined(self, e: dict) -> None:
        p = e["payload"]
        if p["node_asset_id"] not in self.s["assets"]:
            self.fail("UNKNOWN_ASSET", f"容量指标挂在未登记节点 {p['node_asset_id']}",
                      e["event_id"])
        self.s["capacities"][p["node_asset_id"]] = {
            "metric": p["metric"], "daily_cap": p["daily_cap"]}

    def _on_load_reported(self, e: dict) -> None:
        p = e["payload"]
        cap = self.s["capacities"].get(p["node_asset_id"])
        if cap is None:
            self.fail("NO_CAPACITY",
                      f"节点 {p['node_asset_id']} 未定义生态容量即上报承载量", e["event_id"])
            return
        if p["load"] > cap["daily_cap"]:
            # 上报瞬间不判定；当日若最终没有宣布超载并处置，由收尾检查兜底。
            self.s["overcap_reports"][(p["node_asset_id"], p["date"])] = p["load"]

    def _on_overload_declared(self, e: dict) -> None:
        p = e["payload"]
        cap = self.s["capacities"].get(p["node_asset_id"])
        if cap and p["load"] <= cap["daily_cap"]:
            self.fail("OVERLOAD_FALSE",
                      f"承载 {p['load']} 未超容量 {cap['daily_cap']}，不应宣布超载",
                      e["event_id"])
        rec = self.s["overloads"].setdefault(
            p["node_asset_id"], {"active": False, "declared_date": None})
        if rec["active"]:
            self.fail("OVERLOAD_DUPLICATE", f"{p['node_asset_id']} 已处于超载状态",
                      e["event_id"])
            return
        rec.update(active=True, declared_date=p["date"], suspension_seen=False)
        self.s["overcap_reports"].pop((p["node_asset_id"], p["date"]), None)

    def _on_overload_cleared(self, e: dict) -> None:
        p = e["payload"]
        rec = self.s["overloads"].get(p["node_asset_id"])
        if not rec or not rec["active"]:
            self.fail("OVERLOAD_INACTIVE",
                      f"{p['node_asset_id']} 未处于超载状态，无需解除", e["event_id"])
            return
        if not rec["suspension_seen"]:
            self.fail("OVERLOAD_WITHOUT_SUSPENSION",
                      f"{p['node_asset_id']} 超载期间从未发出精准暂停，受影响业务没有被保护",
                      e["event_id"])
        rec["active"] = False

    # ================= 暂停与旅客承诺 =================
    def _on_suspension_issued(self, e: dict) -> None:
        p, sid = e["payload"], e["aggregate_id"]
        assets = set(p["scope_asset_ids"])
        for aid in assets:
            if aid not in self.s["assets"]:
                self.fail("UNKNOWN_ASSET", f"暂停范围含未登记资产 {aid}", e["event_id"])
        starts = _dt(p["starts_at"])
        if p["reason"] == "overload":
            if not any(self.s["overloads"].get(a, {}).get("active") for a in assets):
                self.fail("SUSPENSION_BAD_REASON",
                          "reason=overload 的暂停必须对应一个已宣布的超载节点", e["event_id"])
            for aid in assets:
                rec = self.s["overloads"].get(aid)
                if rec and rec["active"]:
                    rec["suspension_seen"] = True
        protected = {}
        for c in p.get("protected_commitments", []):
            cid = c["commitment_id"]
            prep_id = c.get("prepayment_id")
            if prep_id and prep_id not in self.s["prepayments"]:
                self.fail("UNKNOWN_COMMITMENT",
                          f"受保护承诺 {cid} 引用的预付款 {prep_id} 不存在", e["event_id"])
            protected[cid] = {"guest_ref": c.get("guest_ref"), "prepayment_id": prep_id,
                              "honored": False}
        self.s["suspensions"][sid] = {
            "reason": p["reason"], "scope_assets": assets,
            "service_kinds": set(p["service_kinds"]), "starts_at": starts,
            "expected_end": _dt(p["expected_end"]) if p.get("expected_end") else None,
            "ended_at": None, "protected": protected,
        }

    def _on_suspension_lifted(self, e: dict) -> None:
        sid = e["aggregate_id"]
        sus = self.s["suspensions"].get(sid)
        if sus is None:
            self.fail("UNKNOWN_SUSPENSION", f"暂停 {sid} 不存在", e["event_id"])
            return
        if sus["ended_at"] is not None:
            self.fail("SUSPENSION_STATE", f"暂停 {sid} 已解除", e["event_id"])
            return
        ended = _dt(e["payload"]["ended_at"])
        unhonored = [cid for cid, c in sus["protected"].items() if not c["honored"]]
        if unhonored:
            self.fail("COMMITMENT_NOT_HONORED",
                      f"暂停 {sid} 解除时仍有已入住/已付款旅客承诺未兑现：{unhonored}；"
                      "暂停只针对新业务，既有承诺必须照护到底", e["event_id"])
        sus["ended_at"] = ended

    def _on_commitment_honored(self, e: dict) -> None:
        p = e["payload"]
        sus = self.s["suspensions"].get(p["suspension_id"])
        if sus is None:
            self.fail("UNKNOWN_SUSPENSION",
                      f"承诺兑现记录指向不存在的暂停 {p['suspension_id']}", e["event_id"])
            return
        commitment = sus["protected"].get(p["commitment_id"])
        if commitment is None:
            self.fail("UNKNOWN_COMMITMENT",
                      f"承诺 {p['commitment_id']} 不在暂停 {p['suspension_id']} 的保护清单内",
                      e["event_id"])
            return
        if commitment["honored"]:
            self.fail("COMMITMENT_DUP", f"承诺 {p['commitment_id']} 已兑现", e["event_id"])
            return
        prep_id = commitment.get("prepayment_id")
        if prep_id and self.s["prepayments"][prep_id]["status"] == "open":
            self.fail("COMMITMENT_NOT_BACKED",
                      f"承诺 {p['commitment_id']} 标记兑现，但对应预付款 {prep_id} "
                      "仍未履约或退款，证据不成立", e["event_id"])
        commitment["honored"] = True

    # ================= 维修工单 =================
    def _on_repair_opened(self, e: dict) -> None:
        p, rid = e["payload"], e["aggregate_id"]
        asset = self.s["assets"].get(p["asset_id"])
        if asset is None:
            self.fail("UNKNOWN_ASSET", f"工单挂在未登记资产 {p['asset_id']}", e["event_id"])
        opened = _dt(p["opened_at"])
        self.s["repairs"][rid] = {
            "asset_id": p["asset_id"], "fault": p["fault"], "reported_by": p["reported_by"],
            "opened_at": opened, "claim_deadline": opened
            + timedelta(hours=RULES["repair_claim_hours"]),
            "claimed_by": None, "completed": False, "cost_cents": 0, "borne_by": [],
            "village": asset["village"] if asset else None,
        }

    def _on_repair_claimed(self, e: dict) -> None:
        p = e["payload"]
        order = self.s["repairs"].get(p["repair_order_id"])
        if order is None:
            self.fail("UNKNOWN_REPAIR", f"工单 {p['repair_order_id']} 不存在", e["event_id"])
            return
        if order["claimed_by"]:
            self.fail("REPAIR_RECLAIMED",
                      f"工单 {p['repair_order_id']} 已由 {order['claimed_by']} 认领",
                      e["event_id"])
            return
        order["claimed_by"] = p["claimed_by"]
        order["claim_basis"] = p["basis"]

    def _on_repair_completed(self, e: dict) -> None:
        p = e["payload"]
        rid = e["aggregate_id"]
        order = self.s["repairs"].get(rid)
        if order is None:
            self.fail("UNKNOWN_REPAIR", f"工单 {rid} 不存在", e["event_id"])
            return
        if not order["claimed_by"]:
            self.fail("REPAIR_UNCLAIMED",
                      f"财政/公共资产工单 {rid}（{order['fault']}）在无人认领责任的情况下完工："
                      "维修负担必须先认领、再分摊，不能年底对账时悬空", e["event_id"])
        shares = p["borne_by"]
        total = sum(s.get("share_cents", 0) for s in shares)
        if total != p["cost_cents"]:
            self.fail("REPAIR_SHARE_MISMATCH",
                      f"工单 {rid} 维修费 {p['cost_cents']} 分，但分摊合计 {total} 分",
                      e["event_id"])
        order.update(completed=True, cost_cents=p["cost_cents"],
                     borne_by=shares, completed_at=_dt(p["completed_at"]),
                     evidence_ref=p["evidence_ref"])

    # ================= 季度公示 =================
    def _on_notice_published(self, e: dict) -> None:
        p = e["payload"]
        sections = p["sections"]
        required = ("asset_usage", "repair_burden", "employment", "distributable_benefit")
        for key in required:
            if key not in sections:
                self.fail("NOTICE_SECTION_MISSING",
                          f"季度公示必须把 {required} 四板块分开呈现，缺 {key}", e["event_id"])
        for src in p["source_event_ids"]:
            if src not in self.s["events_by_id"]:
                self.fail("NOTICE_BAD_SOURCE",
                          f"公示引用了事件流中不存在的事件 {src}：公示必须可逐笔回溯",
                          e["event_id"])

        village, quarter = p["scope_village"], p["quarter"]
        # 维修负担：本村季内开单或仍未关闭的工单必须全部公示
        shown_repairs = {r.get("repair_order_id") for r in sections.get("repair_burden", [])}
        for rid, order in self.s["repairs"].items():
            if order["village"] != village:
                continue
            if _quarter(order["opened_at"]) == quarter or not order["completed"]:
                if rid not in shown_repairs:
                    self.fail("NOTICE_REPAIR_OMITTED",
                              f"公示遗漏工单 {rid}：{order['fault']}（认领方："
                              f"{order['claimed_by'] or '无人认领'}）", e["event_id"])
        # 就业兑现：本村所有承诺逐条公示且数字与凭证投影一致
        shown_terms = {x.get("term_id"): x for x in
                       sections.get("employment", {}).get("pledges", [])}
        for pledge in self.s["pledges"]:
            term = self.s["terms"].get(pledge["term_id"])
            if not term or term["village"] != village:
                continue
            shown = shown_terms.get(pledge["term_id"])
            if shown is None:
                self.fail("NOTICE_PLEDGE_OMITTED",
                          f"公示遗漏许可 {pledge['term_id']} 的就业承诺兑现情况",
                          e["event_id"])
                continue
            for key_proj, key_show in (("positions_total", "positions_total"),
                                       ("local_min", "local_positions_min"),
                                       ("hires_total", "hires_total"),
                                       ("hires_local", "hires_local")):
                if key_show in shown and shown[key_show] != pledge[key_proj]:
                    self.fail("NOTICE_PLEDGE_MISMATCH",
                              f"公示中 {pledge['term_id']} 的 {key_show} 与工资凭证投影不符",
                              e["event_id"])
        # 可分配收益：分配结果逐行可回溯
        for item in sections.get("distributable_benefit", {}).get("allocations", []):
            agg = self.s["allocations"].get(item.get("aggregate_id"))
            if agg is None:
                self.fail("NOTICE_ALLOCATION_UNKNOWN",
                          f"公示中的分配结果 {item.get('aggregate_id')} 事件流中不存在",
                          e["event_id"])
                continue
            if "total_cents" in item and item["total_cents"] != agg["total_cents"]:
                self.fail("NOTICE_ALLOCATION_MISMATCH",
                          f"公示分配总额与 {item['aggregate_id']} 事件记录不一致",
                          e["event_id"])
            if item.get("settled") != agg["settled"]:
                self.fail("NOTICE_ALLOCATION_MISMATCH",
                          f"公示兑付状态与 {item['aggregate_id']} 不一致", e["event_id"])
        # 公共资产使用：本村许可必须逐条出现
        shown_usage_terms = {x.get("term_id") for x in sections.get("asset_usage", [])}
        for tid, term in self.s["terms"].items():
            if term["village"] == village and tid not in shown_usage_terms:
                self.fail("NOTICE_USAGE_OMITTED",
                          f"公示遗漏许可 {tid} 对公共资产的使用情况", e["event_id"])
        self.s["notices"].append(p)

    # ================= 分配边界 =================
    def _on_benefit_allocated(self, e: dict) -> None:
        p, agg = e["payload"], e["aggregate_id"]
        if agg in self.s["allocations"]:
            self.fail("ALLOCATION_DUPLICATE", f"分配结果 {agg} 重复记录", e["event_id"])
            return
        total = 0
        for line in p["lines"]:
            total += line.get("amount_cents", 0)
            basis = line.get("basis")
            for ref in line.get("evidence_refs", []):
                if basis == "referral_commission":
                    rec = self.s["referrals"].get(ref)
                    if rec is None or rec["status"] != "verified":
                        self.fail("ALLOCATION_UNVERIFIED_REFERRAL",
                                  f"分配行 {line.get('party_id')} 的导流依据 {ref} "
                                  "未核销，导流贡献必须有证据才能分钱", e["event_id"])
                elif basis in ("consignment_proceeds", "consignment_commission"):
                    batch = self.s["batches"].get(ref)
                    if batch is None:
                        self.fail("ALLOCATION_UNKNOWN_BATCH",
                                  f"分配行引用不存在的寄售批次 {ref}", e["event_id"])
        self.s["allocations"][agg] = {"period": p["period"], "total_cents": total,
                                      "settled": False, "lines": p["lines"]}

    def _on_benefit_settled(self, e: dict) -> None:
        agg = e["payload"]["allocation_aggregate_id"]
        rec = self.s["allocations"].get(agg)
        if rec is None:
            self.fail("UNKNOWN_ALLOCATION", f"分配结果 {agg} 不存在", e["event_id"])
            return
        if rec["settled"]:
            self.fail("ALLOCATION_DOUBLE_SETTLE", f"分配结果 {agg} 重复兑付", e["event_id"])
            return
        rec["settled"] = True

    # ================= 退出交割 =================
    def _frozen_handover(self, handover_id: str) -> tuple[str, dict] | None:
        term_id = self.s["handover_alias"].get(
            handover_id, handover_id.removeprefix("handover-"))
        ho = self.s["handovers_by_term"].get(term_id)
        if ho is None or ho["handover_id"] != handover_id:
            return None
        return term_id, ho

    def _on_handover_list_generated(self, e: dict) -> None:
        p, hid = e["payload"], e["aggregate_id"]
        ho = self.s["pending_handovers"].get(p["term_id"])
        if ho is None:
            existing = self.s["handovers_by_term"].get(p["term_id"])
            if existing is not None:
                self.fail("HANDOVER_DUPLICATE",
                          f"{p['term_id']} 的交割清单 {existing['handover_id']} 已生成，"
                          "不得另立清单", e["event_id"])
            else:
                self.fail("HANDOVER_NO_EXIT",
                          f"交割清单 {hid} 必须由退出请求触发生成，不能凭空制作", e["event_id"])
            return
        expected_ids = {b["blocker_id"] for b in ho["checklist"]["blockers"]}
        actual_ids = {b.get("blocker_id") for b in p["checklist"].get("blockers", [])}
        if actual_ids != expected_ids:
            missing = expected_ids - actual_ids
            extra = actual_ids - expected_ids
            self.fail("HANDOVER_LIST_TAMPERED",
                      f"交割清单与系统快照不一致（遗漏 {sorted(missing)}，私加 {sorted(extra)}）："
                      "未清库存、预付款、设备或数据责任不得被悄悄带出合同期", e["event_id"])
        ho["handover_id"] = hid
        self.s["handover_alias"][hid] = p["term_id"]
        # 清单经与系统快照核对一致后正式生效；其后离场只认清单内项目。
        self.s["handovers_by_term"][p["term_id"]] = ho
        self.s["pending_handovers"].pop(p["term_id"], None)

    def _on_handover_blocker_resolved(self, e: dict) -> None:
        p = e["payload"]
        found = self._frozen_handover(p["handover_id"])
        if found is None:
            self.fail("UNKNOWN_HANDOVER",
                      f"阻断项解除指向不存在的交割单 {p['handover_id']}", e["event_id"])
            return
        term_id, ho = found
        blocker = next((b for b in ho["checklist"]["blockers"]
                        if b["blocker_id"] == p["blocker_id"]), None)
        if blocker is None:
            self.fail("UNKNOWN_BLOCKER",
                      f"交割单 {p['handover_id']} 上没有阻断项 {p['blocker_id']}", e["event_id"])
            return
        if not self._blocker_actually_cleared(blocker, term_id, p["resolution_evidence"]):
            self.fail("BLOCKER_NOT_CLEARED",
                      f"阻断项 {p['blocker_id']} 标为解除，但对应责任在事件流中并未清偿，"
                      "解除必须凭证据且与事实一致", e["event_id"])
            return
        self.s["resolved_blockers"].setdefault(ho["handover_id"], set()).add(p["blocker_id"])

    def _blocker_actually_cleared(self, blocker: dict, term_id: str, evidence: str) -> bool:
        if not evidence:
            return False
        kind, ref = blocker["kind"], blocker["ref"]
        if kind == "unsettled_consignment":
            return self.s["batches"][ref]["settled"]
        if kind == "open_prepayment":
            return self.s["prepayments"][ref]["status"] != "open"
        if kind == "equipment_on_site":
            return self.s["assets"][ref]["present"] is False
        if kind == "open_repair":
            return self.s["repairs"][ref]["completed"]
        if kind == "unverified_referral":
            return self.s["referrals"][ref]["status"] in ("verified", "rejected")
        if kind in ("employment_unreported", "employment_shortfall"):
            pledge = self._pledge(term_id)
            if not pledge or not pledge["reported"]:
                return False
            return (pledge["hires_total"] >= pledge["positions_total"]
                    and pledge["hires_local"] >= pledge["local_min"])
        if kind == "data_handover":
            return False  # 只能随 HANDOVER_COMPLETED 的数据确认解除
        return False

    def _on_handover_completed(self, e: dict) -> None:
        p = e["payload"]
        found = self._frozen_handover(p["handover_id"])
        if found is None:
            self.fail("UNKNOWN_HANDOVER", f"交割完成指向不存在的交割单 {p['handover_id']}",
                      e["event_id"])
            return
        term_id, ho = found
        checklist = ho["checklist"]
        resolved = self.s["resolved_blockers"].setdefault(ho["handover_id"], set())
        if "B-dat-" + term_id not in resolved:
            if not p.get("data_acknowledgement_ref"):
                self.fail("DATA_NOT_HANDED_OVER",
                          "交割完成缺少数据移交/销毁确认：经营数据责任不得被擅自带走",
                          e["event_id"])
            else:
                resolved.add("B-dat-" + term_id)
        outstanding = {b["blocker_id"] for b in checklist["blockers"]} - resolved
        if outstanding:
            self.fail("HANDOVER_BLOCKED",
                      f"交割单仍有 {len(outstanding)} 项未清偿（{sorted(outstanding)[:5]}...），"
                      "不得完成交割、不得离场", e["event_id"])
        for item in checklist["equipment_to_clear"]:
            if self.s["assets"][item["asset_id"]]["present"]:
                self.fail("EQUIPMENT_LEFT_ON_SITE",
                          f"设备 {item['asset_id']} 未清场即完成交割", e["event_id"])
        term = self.s["terms"].get(term_id)
        if term:
            term["status"] = "handover_completed"

    # ================= 日志收尾检查 =================
    def _end_of_log_checks(self) -> None:
        as_of = self.s["as_of"]
        if as_of is None:
            return
        for rid, order in self.s["repairs"].items():
            if not order["claimed_by"] and as_of > order["claim_deadline"]:
                asset = self.s["assets"].get(order["asset_id"], {})
                self.s["violations"].append({
                    "code": "REPAIR_NEVER_CLAIMED",
                    "message": f"工单 {rid}（{asset.get('location', order['asset_id'])}："
                               f"{order['fault']}，资金来源：{asset.get('funded_by')}）"
                               f"开出超过 {RULES['repair_claim_hours']} 小时仍无人认领——"
                               "财政修建的厕所也必须有维修责任方",
                    "event_id": rid,
                })
        for (node, date), load in list(self.s["overcap_reports"].items()):
            cap = self.s["capacities"].get(node, {})
            self.s["violations"].append({
                "code": "LOAD_OVER_CAP_WITHOUT_DECLARATION",
                "message": f"节点 {node} {date} 承载 {load} 已超容量上限 "
                           f"{cap.get('daily_cap')}，但始终没有宣布超载并精准暂停，"
                           "不能装作没看见",
                "event_id": node,
            })
        for node, rec in self.s["overloads"].items():
            if rec["active"] and not rec["suspension_seen"]:
                self.s["violations"].append({
                    "code": "OVERLOAD_UNRESOLVED",
                    "message": f"节点 {node} 仍处于超载状态且未发出精准暂停",
                    "event_id": node,
                })


def audit(events: list[dict]) -> dict:
    """折叠事件流，返回投影状态与中文违规列表。"""
    return _Audit().fold(events)
