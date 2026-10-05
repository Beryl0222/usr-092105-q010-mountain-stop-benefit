"""由事件回放得到的运营状态投影。

投影不保存任何事件里没有的事实，随时可以清空重建，
因此年底对账、季度公示与退出交割看到的是同一本账。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

LOCAL_TZ = timezone(timedelta(hours=8))


def parse_ts(value) -> datetime:
    """把 ISO 字符串或 datetime 归一化为带本地时区的时间。"""
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=LOCAL_TZ)


def stock_key(asset_id: str, operator: str, producer: str, item: str) -> tuple:
    """寄售库存按（资产、运营商、供货方、品类）归集，退货坏账才能只归到实际参与方。"""
    return (asset_id, operator, producer, item)


def current_holder(state: "Projection", asset_id: str):
    """资产当前经营方（含到期未腾退的占用者），无则返回 None。"""
    holders = [
        t
        for t in state.terms.values()
        if t["asset_id"] == asset_id and t["status"] in ("active", "expired")
    ]
    if not holders:
        return None
    return sorted(holders, key=lambda t: t["start"])[-1]["operator"]


class Projection:
    def __init__(self):
        self.assets = {}  # asset_id -> 资产（容量、设备、暂停状态）
        self.terms = {}  # term_id -> 经营许可
        self.commitments = {}  # commitment_id -> 既有承诺（已入住旅客等）
        self.contributions = []  # 导流/志愿班次/就业兑现记录
        self.stock = {}  # (asset, operator, producer, item) -> 库存数量
        self.sales = {}  # sale_id -> 寄售成交
        self.returns = []  # 退货流水（含参与方）
        self.bad_debts = []  # 坏账流水（含参与方）
        self.work_orders = {}  # work_order_id -> 维修工单
        self.suspensions = {}  # suspension_id -> 暂停记录
        self.disclosures = {}  # quarter -> 公示内容
        self.allocations = []  # 分配流水
        self.exit_requests = {}  # operator -> 申请退出时间
        self.exit_clearances = {}  # (operator, 事项) -> 回执证据
        self.exited_operators = set()
        self.versions = {}  # (aggregate_type, aggregate_id) -> 当前版本

    def apply(self, record: dict) -> None:
        self.versions[(record["aggregate_type"], record["aggregate_id"])] = record["version"]
        handler = getattr(self, "_on_" + record["event_type"].lower(), None)
        if handler:
            handler(record)

    # ----- shared_asset -----
    def _on_asset_registered(self, record):
        p = record["payload"]
        self.assets[record["aggregate_id"]] = {
            "asset_id": record["aggregate_id"],
            "kind": p["kind"],
            "village": p["village"],
            "label": p["label"],
            "attrs": p.get("attrs", {}),
            "capacity": {},
            "equipment": {},
            "suspended": {},
        }

    def _on_capacity_declared(self, record):
        p = record["payload"]
        self.assets[record["aggregate_id"]]["capacity"][p["metric"]] = p["limit"]

    def _on_equipment_installed(self, record):
        p = record["payload"]
        self.assets[record["aggregate_id"]]["equipment"][p["equipment_id"]] = {
            "owner": p["owner"],
            "label": p["label"],
        }

    def _on_equipment_removed(self, record):
        p = record["payload"]
        self.assets[record["aggregate_id"]]["equipment"].pop(p["equipment_id"], None)

    def _on_work_order_opened(self, record):
        p = record["payload"]
        self.work_orders[p["work_order_id"]] = {
            "work_order_id": p["work_order_id"],
            "asset_id": record["aggregate_id"],
            "issue": p["issue"],
            "responsible": p["responsible"],
            "status": "open",
            "opened_at": record["occurred_at"],
            "cost": 0,
            "shares": {},
            "closed_at": None,
        }

    def _on_work_order_closed(self, record):
        p = record["payload"]
        self.work_orders[p["work_order_id"]].update(
            status="closed",
            cost=p["cost"],
            shares=dict(p["shares"]),
            closed_at=record["occurred_at"],
        )

    def _on_service_suspended(self, record):
        p = record["payload"]
        self.assets[record["aggregate_id"]]["suspended"][p["suspension_id"]] = p["reason"]
        entry = self.suspensions.setdefault(
            p["suspension_id"],
            {
                "suspension_id": p["suspension_id"],
                "reason": p["reason"],
                "assets": [],
                "occurred_at": record["occurred_at"],
                "note": p.get("note", ""),
            },
        )
        entry["assets"].append(record["aggregate_id"])

    def _on_service_resumed(self, record):
        p = record["payload"]
        asset = self.assets.get(record["aggregate_id"])
        if asset:
            asset["suspended"].pop(p["suspension_id"], None)

    # ----- operating_term -----
    def _on_term_granted(self, record):
        p = record["payload"]
        self.terms[record["aggregate_id"]] = {
            "term_id": record["aggregate_id"],
            "asset_id": p["asset_id"],
            "operator": p["operator"],
            "scope": p["scope"],
            "start": p["start"],
            "end": p["end"],
            "employment_target": p.get("employment_target", 0),
            "status": "active",
            "exit_requested": False,
            "note": p.get("note", ""),
        }

    def _on_term_renewed(self, record):
        self.terms[record["aggregate_id"]]["end"] = record["payload"]["new_end"]

    def _on_term_expired(self, record):
        self.terms[record["aggregate_id"]]["status"] = "expired"

    def _on_term_vacated(self, record):
        self.terms[record["aggregate_id"]]["status"] = "vacated"

    def _on_exit_requested(self, record):
        self.terms[record["aggregate_id"]]["exit_requested"] = True
        self.exit_requests[record["payload"]["operator"]] = record["occurred_at"]

    def _on_exit_item_cleared(self, record):
        p = record["payload"]
        self.exit_clearances[(p["operator"], p["item_key"])] = p["evidence"]

    def _on_operator_exited(self, record):
        self.terms[record["aggregate_id"]]["status"] = "exited"
        self.exited_operators.add(record["payload"]["operator"])

    # ----- community_contribution -----
    def _on_service_recorded(self, record):
        p = record["payload"]
        commitment_id = record["aggregate_id"]
        if p["action"] == "登记":
            self.commitments[commitment_id] = {
                "commitment_id": commitment_id,
                "asset_id": p["asset_id"],
                "guest": p["guest"],
                "prepaid": p.get("prepaid", 0),
                "until": p.get("until"),
                "status": "open",
                "registered_at": record["occurred_at"],
            }
        elif p["action"] == "履约":
            self.commitments[commitment_id]["status"] = "fulfilled"
        elif p["action"] == "取消":
            self.commitments[commitment_id]["status"] = "cancelled"

    def _on_contribution_recorded(self, record):
        self.contributions.append(
            {
                "contribution_id": record["aggregate_id"],
                "occurred_at": record["occurred_at"],
                **record["payload"],
            }
        )

    def _on_consignment_stocked(self, record):
        p = record["payload"]
        key = stock_key(p["asset_id"], p["operator"], p["producer"], p["item"])
        self.stock[key] = self.stock.get(key, 0) + p["qty"]

    def _on_consignment_sold(self, record):
        p = record["payload"]
        self.sales[record["aggregate_id"]] = {
            "sale_id": record["aggregate_id"],
            "occurred_at": record["occurred_at"],
            "asset_id": p["asset_id"],
            "operator": p["operator"],
            "producer": p["producer"],
            "item": p["item"],
            "qty": p["qty"],
            "amount": p["amount"],
            "participants": list(p["participants"]),
            "returned_qty": 0,
            "returned_amount": 0,
            "bad_debt": 0,
        }
        key = stock_key(p["asset_id"], p["operator"], p["producer"], p["item"])
        self.stock[key] = self.stock.get(key, 0) - p["qty"]

    def _on_consignment_returned(self, record):
        p = record["payload"]
        sale = self.sales[record["aggregate_id"]]
        sale["returned_qty"] += p["qty"]
        sale["returned_amount"] = round(sale["returned_amount"] + p["amount"], 2)
        key = stock_key(sale["asset_id"], sale["operator"], sale["producer"], sale["item"])
        self.stock[key] = self.stock.get(key, 0) + p["qty"]
        self.returns.append(
            {
                "sale_id": record["aggregate_id"],
                "occurred_at": record["occurred_at"],
                "qty": p["qty"],
                "amount": p["amount"],
                "reason": p["reason"],
                "participants": list(p["participants"]),
            }
        )

    def _on_bad_debt_recorded(self, record):
        p = record["payload"]
        sale = self.sales[record["aggregate_id"]]
        sale["bad_debt"] = round(sale["bad_debt"] + p["amount"], 2)
        self.bad_debts.append(
            {
                "sale_id": record["aggregate_id"],
                "occurred_at": record["occurred_at"],
                "amount": p["amount"],
                "reason": p["reason"],
                "participants": list(p["participants"]),
            }
        )

    # ----- benefit_distribution -----
    def _on_disclosure_published(self, record):
        p = record["payload"]
        self.disclosures[p["quarter"]] = {
            "sections": p["sections"],
            "published_at": record["occurred_at"],
        }

    def _on_benefit_allocated(self, record):
        p = record["payload"]
        self.allocations.append(
            {
                "quarter": p["quarter"],
                "party": p["party"],
                "amount": p["amount"],
                "occurred_at": record["occurred_at"],
            }
        )
