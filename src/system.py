"""百里画廊山地驿站共益运营系统。

把道路节点、公共设施、村集体院落、季节性摊位、民宿导流、寄售交易、
志愿班次、就业承诺、生态容量、维修工单与分配结果放进同一本
持续可审计的事件账：命令先校验业务规则再追加事件，
状态由事件回放投影，可随时清空重建核对。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from .disclosure import build_disclosure
from .events import aggregate_of, validate_domain_record
from .exit import ATTESTABLE, build_checklist
from .state import LOCAL_TZ, Projection, current_holder, parse_ts, stock_key
from .store import EventStore

SUSPEND_REASONS = ("暴雨", "检修", "超载")
STOCK_SETTLE_WAYS = ("退还原主", "移交接任者")
CAPACITY_METRIC = "同时接待人数"


class BenefitOpsSystem:
    def __init__(self, store: EventStore | None = None, clock=None):
        self.store = store or EventStore()
        self.state = Projection()
        for record in self.store.all():
            self.state.apply(record)
        self._clock = clock

    # ---------- 基础 ----------
    def _now(self) -> datetime:
        return self._clock() if self._clock else datetime.now(LOCAL_TZ)

    @staticmethod
    def _iso(value) -> str:
        return value.isoformat() if isinstance(value, datetime) else str(value)

    def _emit(self, event_type, aggregate_id, summary, payload, at=None, event_id=None) -> dict:
        aggregate_type = aggregate_of(event_type)
        record = {
            "event_id": event_id or f"evt-{uuid.uuid4().hex[:12]}",
            "event_type": event_type,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "occurred_at": self._iso(at) if at else self._now().isoformat(),
            "version": self.state.versions.get((aggregate_type, aggregate_id), 0) + 1,
            "summary": summary,
            "payload": payload,
        }
        errors = validate_domain_record(record)
        if errors:
            raise ValueError("；".join(errors))
        record, created = self.store.append(record)
        if created:
            self.state.apply(record)
        return record

    def _require_asset(self, asset_id) -> dict:
        asset = self.state.assets.get(asset_id)
        if asset is None:
            raise ValueError(f"资产不存在：{asset_id}")
        return asset

    def _require_not_suspended(self, asset_id) -> dict:
        asset = self._require_asset(asset_id)
        if asset["suspended"]:
            reasons = "、".join(asset["suspended"].values())
            raise ValueError(f"{asset['label']}因{reasons}暂停中，受影响业务已精准暂停")
        return asset

    def _require_term(self, term_id) -> dict:
        term = self.state.terms.get(term_id)
        if term is None:
            raise ValueError(f"许可不存在：{term_id}")
        return term

    def _require_active_term(self, asset_id, operator) -> dict:
        """经营许可到期即失效，不能沉淀成永久占用。"""
        for term in self.state.terms.values():
            if (
                term["asset_id"] == asset_id
                and term["operator"] == operator
                and term["status"] in ("active", "expired")
            ):
                if term["status"] == "active" and self._now() < parse_ts(term["end"]):
                    return term
                raise ValueError(
                    f"经营许可 {term['term_id']} 已到期，不得继续经营；到期未腾退将列入季度公示"
                )
        raise ValueError(f"{operator} 在 {asset_id} 没有有效经营许可")

    # ---------- 资产、容量与设备 ----------
    def register_asset(self, asset_id, kind, village, label, attrs=None, at=None) -> dict:
        if asset_id in self.state.assets:
            raise ValueError(f"资产已登记：{asset_id}")
        return self._emit(
            "ASSET_REGISTERED",
            asset_id,
            f"登记{village}{label}",
            {"kind": kind, "village": village, "label": label, "attrs": attrs or {}},
            at=at,
        )

    def declare_capacity(self, asset_id, metric=CAPACITY_METRIC, limit=0, note="", at=None) -> dict:
        asset = self._require_asset(asset_id)
        if limit < 0:
            raise ValueError("生态容量不能为负")
        return self._emit(
            "CAPACITY_DECLARED",
            asset_id,
            f"{asset['label']}生态容量：{metric}上限{limit}",
            {"metric": metric, "limit": limit, "note": note},
            at=at,
        )

    def install_equipment(self, asset_id, equipment_id, owner, label, at=None) -> dict:
        asset = self._require_asset(asset_id)
        if equipment_id in asset["equipment"]:
            raise ValueError(f"设备已登记：{equipment_id}")
        return self._emit(
            "EQUIPMENT_INSTALLED",
            asset_id,
            f"{owner}在{asset['label']}安装{label}",
            {"equipment_id": equipment_id, "owner": owner, "label": label},
            at=at,
        )

    def remove_equipment(self, asset_id, equipment_id, destination, note="", at=None) -> dict:
        asset = self._require_asset(asset_id)
        equipment = asset["equipment"].get(equipment_id)
        if equipment is None:
            raise ValueError(f"{asset['label']}上没有设备 {equipment_id}")
        if equipment["owner"] in self.state.exited_operators:
            raise ValueError("合同期已结束，设备不得再自行离场，请按遗留物登记维修工单处理")
        if not destination:
            raise ValueError("设备离场必须登记去向，不得悄悄带出")
        return self._emit(
            "EQUIPMENT_REMOVED",
            asset_id,
            f"{equipment['owner']}将{equipment['label']}移出{asset['label']}（去向：{destination}）",
            {
                "equipment_id": equipment_id,
                "owner": equipment["owner"],
                "destination": destination,
                "note": note,
            },
            at=at,
        )

    # ---------- 经营许可 ----------
    def grant_term(
        self,
        term_id,
        asset_id,
        operator,
        start,
        end,
        scope="整体",
        employment_target=0,
        note="",
        at=None,
    ) -> dict:
        asset = self._require_not_suspended(asset_id)
        if term_id in self.state.terms:
            raise ValueError(f"许可标识已使用：{term_id}")
        if operator in self.state.exited_operators:
            raise ValueError(f"{operator} 已完成退出，须重新签约主体")
        if operator in self.state.exit_requests:
            raise ValueError(f"{operator} 正在退出交割，不得新签许可")
        if parse_ts(end) <= parse_ts(start):
            raise ValueError("许可截止必须晚于起始")
        for term in self.state.terms.values():
            if (
                term["asset_id"] == asset_id
                and term["scope"] == scope
                and term["status"] in ("active", "expired")
            ):
                raise ValueError(
                    f"{asset['label']}的{scope}尚有许可未腾退（{term['term_id']}），不得重复授予"
                )
        return self._emit(
            "TERM_GRANTED",
            term_id,
            f"授予{operator}经营{asset['label']}{scope}（至{self._iso(end)}）",
            {
                "asset_id": asset_id,
                "operator": operator,
                "scope": scope,
                "start": self._iso(start),
                "end": self._iso(end),
                "employment_target": employment_target,
                "note": note,
            },
            at=at,
        )

    def renew_term(self, term_id, new_end, at=None) -> dict:
        term = self._require_term(term_id)
        if term["status"] != "active":
            raise ValueError("只有有效许可可以续期")
        if self._now() >= parse_ts(term["end"]):
            raise ValueError("许可已到期，不能续期，须重新申请")
        if parse_ts(new_end) <= parse_ts(term["end"]):
            raise ValueError("续期截止必须晚于原截止")
        return self._emit(
            "TERM_RENEWED",
            term_id,
            f"{term['operator']}的许可续期至{self._iso(new_end)}",
            {"new_end": self._iso(new_end)},
            at=at,
        )

    def expire_due_terms(self, at=None) -> list[dict]:
        """把已到期许可显式标记为到期；到期不自动消失，等待腾退并列入公示。"""
        now = parse_ts(at) if at else self._now()
        events = []
        due = [
            t
            for t in self.state.terms.values()
            if t["status"] == "active" and parse_ts(t["end"]) <= now
        ]
        for term in due:
            events.append(
                self._emit(
                    "TERM_EXPIRED",
                    term["term_id"],
                    f"{term['operator']}的许可到期，占用不得沉淀为永久",
                    {},
                    at=now,
                )
            )
        return events

    def vacate_term(self, term_id, at=None) -> dict:
        term = self._require_term(term_id)
        if term["status"] not in ("active", "expired"):
            raise ValueError(f"许可 {term_id} 当前状态不允许腾退")
        asset_id, operator = term["asset_id"], term["operator"]
        open_commitments = [
            c
            for c in self.state.commitments.values()
            if c["asset_id"] == asset_id and c["status"] == "open"
        ]
        if open_commitments:
            raise ValueError("尚有未履约的旅客承诺，不得腾退")
        remaining = {
            k: q
            for k, q in self.state.stock.items()
            if q > 0 and k[0] == asset_id and k[1] == operator
        }
        if remaining:
            raise ValueError("尚有未清寄售库存，不得腾退")
        equipment = [
            eid
            for eid, eq in self.state.assets[asset_id]["equipment"].items()
            if eq["owner"] == operator
        ]
        if equipment:
            raise ValueError("设备尚未移除或移交，不得腾退")
        return self._emit(
            "TERM_VACATED",
            term_id,
            f"{operator}腾退{asset_id}，资产回到村集体可授予池",
            {},
            at=at,
        )

    # ---------- 既有承诺（已入住旅客等） ----------
    def register_commitment(self, commitment_id, asset_id, guest, prepaid=0, until=None, at=None):
        asset = self._require_not_suspended(asset_id)
        if commitment_id in self.state.commitments:
            raise ValueError(f"承诺标识已使用：{commitment_id}")
        holder = current_holder(self.state, asset_id)
        if holder and holder in self.state.exit_requests:
            raise ValueError("经营方正在退出交割，不再接收新预订")
        limit = asset["capacity"].get(CAPACITY_METRIC)
        if limit is not None:
            load = sum(
                1
                for c in self.state.commitments.values()
                if c["asset_id"] == asset_id and c["status"] == "open"
            )
            if load >= limit:
                raise ValueError(f"{asset['label']}已达生态容量上限{limit}，新承诺不予受理")
        return self._emit(
            "SERVICE_RECORDED",
            commitment_id,
            f"登记既有承诺：{guest}（预付款{prepaid}元）",
            {
                "action": "登记",
                "asset_id": asset_id,
                "guest": guest,
                "prepaid": prepaid,
                "until": self._iso(until) if until else None,
            },
            at=at,
        )

    def fulfill_commitment(self, commitment_id, at=None) -> dict:
        """履约既有承诺：暂停期间照常，已入住旅客的承诺必须被照顾。"""
        commitment = self._require_commitment(commitment_id)
        return self._emit(
            "SERVICE_RECORDED",
            commitment_id,
            f"履约承诺：{commitment['guest']}",
            {
                "action": "履约",
                "asset_id": commitment["asset_id"],
                "guest": commitment["guest"],
                "prepaid": commitment["prepaid"],
            },
            at=at,
        )

    def cancel_commitment(self, commitment_id, at=None) -> dict:
        commitment = self._require_commitment(commitment_id)
        return self._emit(
            "SERVICE_RECORDED",
            commitment_id,
            f"取消承诺并退还预付款：{commitment['guest']}",
            {
                "action": "取消",
                "asset_id": commitment["asset_id"],
                "guest": commitment["guest"],
                "prepaid": commitment["prepaid"],
                "refund": commitment["prepaid"],
            },
            at=at,
        )

    def _require_commitment(self, commitment_id) -> dict:
        commitment = self.state.commitments.get(commitment_id)
        if commitment is None:
            raise ValueError(f"承诺不存在：{commitment_id}")
        if commitment["status"] != "open":
            raise ValueError(f"承诺 {commitment_id} 已{commitment['status']}")
        return commitment

    # ---------- 精准暂停 ----------
    def suspend_assets(self, asset_ids, reason, note="", at=None) -> str:
        """暴雨、检修或超载时只暂停受影响资产，并把在营承诺列入保护清单。"""
        if reason not in SUSPEND_REASONS:
            raise ValueError(f"暂停原因须为：{'、'.join(SUSPEND_REASONS)}")
        suspension_id = f"susp-{uuid.uuid4().hex[:8]}"
        for asset_id in asset_ids:
            asset = self._require_asset(asset_id)
            if asset["suspended"]:
                raise ValueError(f"{asset['label']}已在暂停中")
            protected = sorted(
                cid
                for cid, c in self.state.commitments.items()
                if c["asset_id"] == asset_id and c["status"] == "open"
            )
            self._emit(
                "SERVICE_SUSPENDED",
                asset_id,
                f"因{reason}暂停{asset['label']}，保护{len(protected)}项既有承诺",
                {
                    "suspension_id": suspension_id,
                    "reason": reason,
                    "protected_commitments": protected,
                    "note": note,
                },
                at=at,
            )
        return suspension_id

    def resume_assets(self, suspension_id, at=None) -> list[dict]:
        affected = [
            aid
            for aid, asset in self.state.assets.items()
            if suspension_id in asset["suspended"]
        ]
        if not affected:
            raise ValueError(f"暂停记录不存在或已恢复：{suspension_id}")
        return [
            self._emit(
                "SERVICE_RESUMED",
                asset_id,
                f"恢复{self.state.assets[asset_id]['label']}运营",
                {"suspension_id": suspension_id},
                at=at,
            )
            for asset_id in affected
        ]

    # ---------- 社区贡献（导流、志愿班次、就业兑现） ----------
    def record_referral(self, referral_id, contributor, asset_id, amount=0, evidence=None, at=None):
        """民宿导流必须附证据（订单、入住记录或支付凭证），否则不计贡献。"""
        if not evidence:
            raise ValueError("导流贡献必须附证据（订单、入住记录或支付凭证）")
        self._require_not_suspended(asset_id)
        self._require_fresh_contribution(referral_id)
        return self._emit(
            "CONTRIBUTION_RECORDED",
            referral_id,
            f"{contributor}导流至{asset_id}，证据{len(evidence)}份",
            {
                "kind": "导流",
                "contributor": contributor,
                "asset_id": asset_id,
                "amount": amount,
                "evidence": list(evidence),
            },
            at=at,
        )

    def record_volunteer_shift(self, shift_id, person, asset_id, hours, evidence=None, at=None):
        if not evidence:
            raise ValueError("志愿班次必须附签到签退记录")
        self._require_asset(asset_id)
        self._require_fresh_contribution(shift_id)
        if hours <= 0:
            raise ValueError("志愿工时须为正数")
        return self._emit(
            "CONTRIBUTION_RECORDED",
            shift_id,
            f"{person}在{asset_id}志愿服务{hours}小时",
            {
                "kind": "志愿班次",
                "contributor": person,
                "asset_id": asset_id,
                "hours": hours,
                "evidence": list(evidence),
            },
            at=at,
        )

    def record_employment(self, employment_id, operator, person, role, evidence=None, at=None):
        if not evidence:
            raise ValueError("就业兑现必须附用工凭据（合同或社保登记）")
        self._require_fresh_contribution(employment_id)
        return self._emit(
            "CONTRIBUTION_RECORDED",
            employment_id,
            f"{operator}录用{person}为{role}",
            {
                "kind": "就业兑现",
                "contributor": operator,
                "person": person,
                "role": role,
                "evidence": list(evidence),
            },
            at=at,
        )

    def _require_fresh_contribution(self, contribution_id):
        if any(c["contribution_id"] == contribution_id for c in self.state.contributions):
            raise ValueError(f"贡献记录已存在：{contribution_id}")

    # ---------- 寄售交易 ----------
    def stock_consignment(self, asset_id, operator, producer, item, qty, at=None) -> dict:
        if qty <= 0:
            raise ValueError("入库数量须为正数")
        if operator in self.state.exit_requests:
            raise ValueError("退出交割期间不得新增入库")
        self._require_not_suspended(asset_id)
        self._require_active_term(asset_id, operator)
        return self._emit(
            "CONSIGNMENT_STOCKED",
            self._stock_aggregate(asset_id, operator, producer, item),
            f"{producer}的{item}入库{qty}件至{asset_id}",
            {
                "asset_id": asset_id,
                "operator": operator,
                "producer": producer,
                "item": item,
                "qty": qty,
                "way": "入库",
            },
            at=at,
        )

    def settle_stock(self, asset_id, operator, producer, item, qty, way, at=None) -> dict:
        """清结库存：退还原主或移交接任者，退出交割的必经之路。"""
        if way not in STOCK_SETTLE_WAYS:
            raise ValueError(f"清结方式须为：{'、'.join(STOCK_SETTLE_WAYS)}")
        key = stock_key(asset_id, operator, producer, item)
        if qty <= 0 or self.state.stock.get(key, 0) < qty:
            raise ValueError("清结数量超过账面库存")
        return self._emit(
            "CONSIGNMENT_STOCKED",
            self._stock_aggregate(asset_id, operator, producer, item),
            f"{operator}的{item}清结{qty}件（{way}）",
            {
                "asset_id": asset_id,
                "operator": operator,
                "producer": producer,
                "item": item,
                "qty": -qty,
                "way": way,
            },
            at=at,
        )

    def sell_consignment(self, sale_id, asset_id, operator, producer, item, qty, amount, at=None):
        if sale_id in self.state.sales:
            raise ValueError(f"寄售单已存在：{sale_id}")
        if qty <= 0 or amount < 0:
            raise ValueError("数量须为正、金额不得为负")
        self._require_not_suspended(asset_id)
        self._require_active_term(asset_id, operator)
        key = stock_key(asset_id, operator, producer, item)
        if self.state.stock.get(key, 0) < qty:
            raise ValueError(f"{item}库存不足，无法成交")
        participants = sorted({operator, producer})
        return self._emit(
            "CONSIGNMENT_SOLD",
            sale_id,
            f"寄售成交：{producer}的{item}{qty}件，金额{amount}元",
            {
                "asset_id": asset_id,
                "operator": operator,
                "producer": producer,
                "item": item,
                "qty": qty,
                "amount": amount,
                "participants": participants,
            },
            at=at,
        )

    def return_consignment(self, sale_id, qty, amount, reason, at=None) -> dict:
        """退货只归到原成交单的实际参与方，不摊给无关方。"""
        sale = self._require_sale(sale_id)
        if qty <= 0 or amount < 0:
            raise ValueError("退货数量须为正、金额不得为负")
        if sale["returned_qty"] + qty > sale["qty"]:
            raise ValueError("退货数量超过可退数量")
        if round(sale["returned_amount"] + amount, 2) > sale["amount"]:
            raise ValueError("退货金额超过成交金额")
        return self._emit(
            "CONSIGNMENT_RETURNED",
            sale_id,
            f"寄售退货：{sale['item']}{qty}件，退款{amount}元（{reason}）",
            {
                "qty": qty,
                "amount": amount,
                "reason": reason,
                "participants": list(sale["participants"]),
            },
            at=at,
        )

    def write_off_bad_debt(self, sale_id, amount, reason, at=None) -> dict:
        """坏账只记到原成交单的实际参与方。"""
        sale = self._require_sale(sale_id)
        if amount <= 0:
            raise ValueError("坏账金额须为正数")
        recoverable = round(sale["amount"] - sale["returned_amount"] - sale["bad_debt"], 2)
        if amount > recoverable:
            raise ValueError("坏账金额超过未回款部分")
        return self._emit(
            "BAD_DEBT_RECORDED",
            sale_id,
            f"寄售坏账{amount}元（{reason}），归集到实际参与方",
            {"amount": amount, "reason": reason, "participants": list(sale["participants"])},
            at=at,
        )

    def _require_sale(self, sale_id) -> dict:
        sale = self.state.sales.get(sale_id)
        if sale is None:
            raise ValueError(f"寄售单不存在：{sale_id}，退货坏账不得凭空归集")
        return sale

    @staticmethod
    def _stock_aggregate(asset_id, operator, producer, item) -> str:
        return f"stock-{asset_id}-{operator}-{producer}-{item}"

    # ---------- 维修工单 ----------
    def open_work_order(self, work_order_id, asset_id, issue, responsible, at=None) -> dict:
        """维修工单开立即指定责任方，财政修建的设施也不能没人认领。"""
        asset = self._require_asset(asset_id)
        if work_order_id in self.state.work_orders:
            raise ValueError(f"工单已存在：{work_order_id}")
        if not responsible:
            raise ValueError("维修工单必须指定责任方，不能没人认领")
        return self._emit(
            "WORK_ORDER_OPENED",
            asset_id,
            f"{asset['label']}报修：{issue}（责任方：{responsible}）",
            {"work_order_id": work_order_id, "issue": issue, "responsible": responsible},
            at=at,
        )

    def close_work_order(self, work_order_id, cost, shares, at=None) -> dict:
        order = self.state.work_orders.get(work_order_id)
        if order is None:
            raise ValueError(f"工单不存在：{work_order_id}")
        if order["status"] != "open":
            raise ValueError(f"工单 {work_order_id} 已完工")
        if cost < 0 or not shares:
            raise ValueError("完工必须登记费用与分摊")
        if round(sum(shares.values()), 2) != round(cost, 2):
            raise ValueError("分摊合计必须等于维修费用")
        return self._emit(
            "WORK_ORDER_CLOSED",
            order["asset_id"],
            f"工单{work_order_id}完工，费用{cost}元按约分摊",
            {"work_order_id": work_order_id, "cost": cost, "shares": dict(shares)},
            at=at,
        )

    # ---------- 季度公示与分配 ----------
    def publish_disclosure(self, quarter, at=None) -> dict:
        """发布季度公示：公共资产使用、维修负担、就业兑现与可分配收益分列。"""
        if quarter in self.state.disclosures:
            raise ValueError(f"{quarter} 已公示，不得重复发布")
        sections = build_disclosure(self.state, quarter)
        self._emit(
            "DISCLOSURE_PUBLISHED",
            f"disclosure-{quarter}",
            f"发布{quarter}季度公示（四栏分列）",
            {"quarter": quarter, "sections": sections},
            at=at,
        )
        return sections

    def allocate_benefit(self, quarter, party, amount, note="", at=None) -> dict:
        disclosure = self.state.disclosures.get(quarter)
        if disclosure is None:
            raise ValueError(f"{quarter} 尚未公示，不得分配")
        if amount <= 0:
            raise ValueError("分配金额须为正数")
        total = disclosure["sections"]["可分配收益"]["可分配总额"]
        used = sum(a["amount"] for a in self.state.allocations if a["quarter"] == quarter)
        if round(used + amount, 2) > total:
            raise ValueError(f"超出可分配总额：已分{used}元，本次{amount}元，上限{total}元")
        return self._emit(
            "BENEFIT_ALLOCATED",
            f"benefit-{quarter}",
            f"{quarter}向{party}分配{amount}元",
            {"quarter": quarter, "party": party, "amount": amount, "note": note},
            at=at,
        )

    # ---------- 退出交割 ----------
    def request_exit(self, operator, at=None) -> list[dict]:
        """运营商提出退出：生成交割清单，未清结前不得确认退出。"""
        terms = [
            t
            for t in self.state.terms.values()
            if t["operator"] == operator and t["status"] in ("active", "expired")
        ]
        if not terms:
            raise ValueError(f"{operator} 没有待退出的许可")
        if operator in self.state.exit_requests:
            raise ValueError(f"{operator} 已提出退出申请")
        return [
            self._emit(
                "EXIT_REQUESTED",
                term["term_id"],
                f"{operator}提出退出，生成交割清单",
                {"operator": operator},
                at=at,
            )
            for term in terms
        ]

    def exit_checklist(self, operator) -> list[dict]:
        if operator not in self.state.exit_requests:
            raise ValueError(f"{operator} 尚未提出退出申请")
        return build_checklist(self.state, operator)

    def clear_exit_item(self, operator, item_key, evidence, at=None) -> dict:
        """核销凭回执的交割事项（如数据交接）；其余事项必须靠业务操作清结。"""
        if operator not in self.state.exit_requests:
            raise ValueError(f"{operator} 尚未提出退出申请")
        if item_key not in ATTESTABLE:
            raise ValueError(f"{item_key}须通过对应业务操作清结，不可直接核销")
        if not evidence:
            raise ValueError("核销必须附移交回执")
        term = next(
            (t for t in self.state.terms.values() if t["operator"] == operator),
            None,
        )
        if term is None:
            raise ValueError(f"找不到 {operator} 的许可")
        return self._emit(
            "EXIT_ITEM_CLEARED",
            term["term_id"],
            f"{operator}交割事项清结：{item_key}",
            {"operator": operator, "item_key": item_key, "evidence": evidence},
            at=at,
        )

    def confirm_exit(self, operator, at=None) -> list[dict]:
        """确认退出：清单全部清结才放行，否则逐项列明拦下。"""
        if operator not in self.state.exit_requests:
            raise ValueError(f"{operator} 尚未提出退出申请")
        if operator in self.state.exited_operators:
            raise ValueError(f"{operator} 已完成退出")
        open_items = [i["key"] for i in build_checklist(self.state, operator) if i["open"]]
        if open_items:
            raise ValueError("交割清单未清结，不得退出：" + "、".join(open_items))
        return [
            self._emit(
                "OPERATOR_EXITED",
                term["term_id"],
                f"{operator}完成交割，退出{term['asset_id']}",
                {"operator": operator},
                at=at,
            )
            for term in list(self.state.terms.values())
            if term["operator"] == operator and term["status"] != "exited"
        ]
