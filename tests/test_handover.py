"""退出交割清单的内容与阻断语义测试。"""

import copy
import unittest

from src import scenarios as S
from src.audit import audit
from src.validator import validate_event


class HandoverChecklistTest(unittest.TestCase):
    def _exit_with_open_duties(self):
        """运营商旺季末退出时：1 批寄售未结、1 笔预付款未兑现、设备在场。"""
        log = S.EventLog()
        S._minimal_asset(log, S.YARD_STATION)
        log.events[0]["payload"]["asset_kind"] = "collective_yard"
        S._minimal_asset(log, S.COFFEE_EQP)
        log.events[1]["payload"]["asset_kind"] = "equipment"
        log.events[1]["payload"]["owner"] = "operator"
        log.events[1]["payload"]["removable"] = True
        log.add("TERM_GRANTED", "term-open", "2026-05-01T00:00:00+08:00",
                "许可", party_id=S.OP_YUNSHU, village="画廊村",
                scope="station_cafe",
                asset_ids=[S.YARD_STATION, S.COFFEE_EQP],
                starts_at="2026-05-01T00:00:00+08:00",
                ends_at="2026-10-25T23:59:59+08:00", seasonal=True,
                grant_basis="open_bid")
        log.add("CONSIGNMENT_DELIVERED", "batch-open", "2026-07-01T00:00:00+08:00",
                "寄售交付未结清", term_id="term-open",
                supplier_party_id=S.FARMER_MA, seller_party_id=S.OP_YUNSHU,
                village="画廊村", items_summary="蜂蜜", quantity=10, unit="瓶",
                unit_price_cents=3000, unsold_policy="return",
                delivered_at="2026-07-01T00:00:00+08:00")
        log.add("PREPAYMENT_RECEIVED", "term-open", "2026-10-01T00:00:00+08:00",
                "在住客人预付款未兑现", term_id="term-open",
                prepayment_id="prep-open", guest_ref="g-open",
                amount_cents=50000, service_kind="stay", due_date="2026-10-20")
        log.add("OPERATOR_EXITED", "term-open", "2026-10-18T00:00:00+08:00",
                "运营商提出退出", requested_at="2026-10-18T00:00:00+08:00",
                reason="旺季结束")
        state = audit(log.events)
        return log, state

    def test_checklist_lists_inventory_prepayment_equipment_data(self) -> None:
        _log, state = self._exit_with_open_duties()
        checklist = state["pending_handovers"]["term-open"]["checklist"]
        kinds = {b["kind"] for b in checklist["blockers"]}
        self.assertIn("unsettled_consignment", kinds)
        self.assertIn("open_prepayment", kinds)
        self.assertIn("equipment_on_site", kinds)
        self.assertIn("data_handover", kinds)

        consignment = next(b for b in checklist["open_consignments"]
                           if b["batch_id"] == "batch-open")
        self.assertEqual(consignment["quantity_on_hand"], 10)
        prep = checklist["open_prepayments"][0]
        self.assertEqual(prep["prepayment_id"], "prep-open")

    def test_publishing_a_tampered_list_is_rejected(self) -> None:
        log, state = self._exit_with_open_duties()
        checklist = copy.deepcopy(
            state["pending_handovers"]["term-open"]["checklist"])
        # 私自从清单中删掉未结寄售阻断项，试图把库存悄悄带出合同期
        checklist["blockers"] = [b for b in checklist["blockers"]
                                 if b["kind"] != "unsettled_consignment"]
        log.add("HANDOVER_LIST_GENERATED", "ho-open",
                "2026-10-18T00:00:05+08:00", "被删改过的交割清单",
                term_id="term-open", operator_party_id=S.OP_YUNSHU,
                generated_at="2026-10-18T00:00:05+08:00",
                checklist=checklist)
        codes = {v["code"] for v in audit(log.events)["violations"]}
        self.assertIn("HANDOVER_LIST_TAMPERED", codes)

    def test_list_cannot_be_generated_without_exit_request(self) -> None:
        log = S.EventLog()
        S._minimal_asset(log, S.YARD_STATION)
        log.events[0]["payload"]["asset_kind"] = "collective_yard"
        log.add("TERM_GRANTED", "term-ne", "2026-05-01T00:00:00+08:00",
                "许可", party_id=S.OP_YUNSHU, village="画廊村",
                scope="station_cafe", asset_ids=[S.YARD_STATION],
                starts_at="2026-05-01T00:00:00+08:00",
                ends_at="2026-10-25T23:59:59+08:00", seasonal=True,
                grant_basis="open_bid")
        state = audit(log.events)
        empty = state["pending_handovers"].get("term-ne", {"checklist": {"blockers": []}})
        log.add("HANDOVER_LIST_GENERATED", "ho-ne", "2026-07-01T00:00:00+08:00",
                "未退出却凭空制作交割清单", term_id="term-ne",
                operator_party_id=S.OP_YUNSHU,
                generated_at="2026-07-01T00:00:00+08:00", checklist=empty["checklist"])
        codes = {v["code"] for v in audit(log.events)["violations"]}
        self.assertIn("HANDOVER_NO_EXIT", codes)

    def test_new_prepayment_blocked_after_exit_request(self) -> None:
        events = S.compliant_season()
        # 在合规日志的退出请求之后再插一笔新收款（版本与时间均在其后）
        exit_idx = next(i for i, e in enumerate(events)
                        if e["event_type"] == "OPERATOR_EXITED")
        injected = {
            "event_id": "evt-injected-0001",
            "event_type": "PREPAYMENT_RECEIVED",
            "aggregate_type": "operating_term",
            "aggregate_id": S.TERM_YUNSHU,
            "occurred_at": "2026-10-18T12:00:00+08:00",
            "version": events[exit_idx]["version"] + 1,
            "summary": "退出流程中违规收取预付款",
            "payload": {"term_id": S.TERM_YUNSHU, "prepayment_id": "prep-late",
                        "guest_ref": "g-late", "amount_cents": 10000,
                        "service_kind": "catering", "due_date": "2026-10-25"},
        }
        self.assertEqual(validate_event(injected), [])
        tampered = events[:exit_idx + 1] + [injected] + events[exit_idx + 1:]
        codes = {v["code"] for v in audit(tampered)["violations"]}
        self.assertIn("EXIT_FREEZE", codes)


if __name__ == "__main__":
    unittest.main()
