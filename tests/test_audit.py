"""持续审计不变量测试。

每条规则都有一个“合规样例不违规”的正向保证，和一个
“最小违规片段精确命中对应违规码”的反向保证。
"""

import unittest

from src import scenarios as S
from src.audit import audit
from src.validator import validate_event


def _codes(events):
    return sorted({v["code"] for v in audit(events)["violations"]})


class CompliantSeasonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.events = S.compliant_season()
        cls.state = audit(cls.events)

    def test_no_violations(self) -> None:
        self.assertEqual(self.state["violations"], [])

    def test_all_events_envelope_valid(self) -> None:
        for event in self.events:
            self.assertEqual(validate_event(event), [], event["event_id"])

    def test_repairs_all_claimed_and_shared(self) -> None:
        for rid, order in self.state["repairs"].items():
            self.assertTrue(order["claimed_by"], rid)
            self.assertTrue(order["completed"], rid)
            self.assertEqual(
                sum(s["share_cents"] for s in order["borne_by"]),
                order["cost_cents"])

    def test_consignment_accounting(self) -> None:
        batch = self.state["batches"][S.BATCH_HONEY]
        # 200 = 售 150 + 退 50
        self.assertEqual(batch["delivered"], 200)
        self.assertEqual(batch["sold"] + batch["returned"], 200)
        # 应付农户 = 销售额 4500 − 佣金 450；销售方坏账 600 不扣农户
        self.assertEqual(batch["sold_proceeds"] - batch["commission_total"], 405000)
        self.assertEqual(batch["seller_borne_bad_debt"], 60000)
        self.assertEqual(batch["supplier_borne_bad_debt"], 0)
        self.assertTrue(batch["settled"])

    def test_referral_requires_checkin_evidence(self) -> None:
        ref = self.state["referrals"][S.REFERRAL]
        self.assertEqual(ref["status"], "verified")
        self.assertEqual(ref["payout_cents"], 5000)

    def test_suspension_scope_is_precise(self) -> None:
        storm = self.state["suspensions"][S.SUSP_STORM]
        # 暴雨只暂停 0 公里三个点位，云栖节点不在范围
        self.assertNotIn(S.NODE_YUNQI, storm["scope_assets"])
        self.assertIn("new_booking", storm["service_kinds"])
        # 所有受保护承诺均兑现后才解封
        self.assertTrue(all(c["honored"] for c in storm["protected"].values()))

    def test_handover_has_no_open_blockers(self) -> None:
        ho = self.state["handovers_by_term"][S.TERM_YUNSHU]
        resolved = self.state["resolved_blockers"][ho["handover_id"]]
        outstanding = {b["blocker_id"] for b in ho["checklist"]["blockers"]} - resolved
        self.assertEqual(outstanding, set())

    def test_handover_listed_every_open_duty(self) -> None:
        checklist = self.state["handovers_by_term"][S.TERM_YUNSHU]["checklist"]
        kinds = {b["kind"] for b in checklist["blockers"]}
        # 退出时库存已结清、预付款已兑现，故这两类不应残留；
        # 设备放行与数据责任必须曾在清单上
        self.assertIn("equipment_on_site", kinds)
        self.assertIn("data_handover", kinds)
        self.assertNotIn("unsettled_consignment", kinds)
        self.assertNotIn("open_prepayment", kinds)

    def test_notice_four_sections_present(self) -> None:
        notice = self.state["notices"][0]
        self.assertEqual(set(notice["sections"]),
                         {"asset_usage", "repair_burden",
                          "employment", "distributable_benefit"})


class InvariantViolationTest(unittest.TestCase):
    def assert_only_code(self, events, code):
        for event in events:
            self.assertEqual(validate_event(event), [], event["event_id"])
        self.assertEqual(_codes(events), [code])

    def test_term_cannot_become_permanent_occupancy(self) -> None:
        self.assert_only_code(S.violation_usage_after_expiry(), "USAGE_OUTSIDE_TERM")

    def test_seasonal_term_length_rejected_at_envelope(self) -> None:
        errs = validate_event(S.violation_season_too_long()["event"])
        self.assertTrue(any("180" in m for m in errs))

    def test_referral_contribution_needs_verified_evidence(self) -> None:
        self.assert_only_code(S.violation_unverified_referral_claim(),
                              "CONTRIBUTION_UNVERIFIED_REFERRAL")

    def test_bad_debt_only_borne_by_actual_party(self) -> None:
        self.assert_only_code(S.violation_bad_debt_to_farmer(),
                              "BAD_DEBT_WRONG_PARTY")

    def test_storm_suspension_blocks_affected_business(self) -> None:
        self.assert_only_code(S.violation_business_during_storm(),
                              "SUSPENSION_VIOLATION")

    def test_suspension_cannot_lift_before_guest_commitments_kept(self) -> None:
        self.assert_only_code(S.violation_lift_with_honoring_guest(),
                              "COMMITMENT_NOT_HONORED")

    def test_fiscal_toilet_repair_must_be_claimed(self) -> None:
        self.assert_only_code(S.violation_repair_never_claimed(),
                              "REPAIR_NEVER_CLAIMED")

    def test_overload_without_targeted_response_is_violation(self) -> None:
        self.assert_only_code(S.violation_overload_no_response(),
                              "LOAD_OVER_CAP_WITHOUT_DECLARATION")

    def test_assets_frozen_between_exit_request_and_list(self) -> None:
        self.assert_only_code(S.violation_exit_smuggle(), "EXIT_FREEZE")

    def test_handover_blocked_until_all_duties_cleared(self) -> None:
        self.assert_only_code(S.violation_handover_incomplete(),
                              "HANDOVER_BLOCKED")

    def test_quarterly_notice_cannot_hide_repair_burden(self) -> None:
        self.assert_only_code(S.violation_notice_missing_repair(),
                              "NOTICE_REPAIR_OMITTED")

    def test_settlement_must_match_consignment_formula(self) -> None:
        self.assert_only_code(S.violation_settle_amount(),
                              "SETTLE_AMOUNT_MISMATCH")


class EventStreamIntegrityTest(unittest.TestCase):
    def test_replayed_event_is_idempotent(self) -> None:
        events = S.compliant_season()
        once = audit(events)["violations"]
        twice = audit(events + events)["violations"]
        self.assertEqual(once, [])
        self.assertEqual(twice, [])

    def test_version_gap_detected(self) -> None:
        events = S.compliant_season()
        events[10]["version"] = 99
        self.assertIn("VERSION_GAP",
                      {v["code"] for v in audit(events)["violations"]})

    def test_conflicting_replay_detected(self) -> None:
        events = S.compliant_season()
        clone = [dict(e) for e in events]
        clone[0]["summary"] = clone[0]["summary"] + "（被篡改）"
        codes = {v["code"] for v in audit(events + clone)["violations"]}
        self.assertIn("EVENT_CONFLICT", codes)


if __name__ == "__main__":
    unittest.main()
