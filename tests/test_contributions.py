import unittest

from src.system import BenefitOpsSystem
from tests.test_terms import make_system


class ContributionTest(unittest.TestCase):
    def setUp(self):
        self.sys, _ = make_system()
        self.sys.register_asset("yard-1", "集体院落", "梁家庄", "梁家庄1号院")

    def test_referral_requires_evidence(self):
        """导流贡献必须有证据，空口不计。"""
        with self.assertRaisesRegex(ValueError, "证据"):
            self.sys.record_referral("ref-1", "云舍民宿", "yard-1", amount=80)
        self.sys.record_referral(
            "ref-1",
            "云舍民宿",
            "yard-1",
            amount=80,
            evidence=["订单O-1001", "入住记录C-203"],
        )
        record = self.sys.state.contributions[0]
        self.assertEqual(record["kind"], "导流")
        self.assertEqual(len(record["evidence"]), 2)

    def test_volunteer_shift_requires_signin(self):
        with self.assertRaisesRegex(ValueError, "签到"):
            self.sys.record_volunteer_shift("shift-1", "村民小李", "yard-1", 4)
        self.sys.record_volunteer_shift("shift-1", "村民小李", "yard-1", 4, evidence=["签到表-1005"])
        self.assertEqual(self.sys.state.contributions[0]["hours"], 4)

    def test_employment_fulfillment_recorded(self):
        with self.assertRaisesRegex(ValueError, "凭据"):
            self.sys.record_employment("emp-1", "山风咖啡", "村民小王", "咖啡师")
        self.sys.record_employment(
            "emp-1", "山风咖啡", "村民小王", "咖啡师", evidence=["劳动合同-2026-017"]
        )
        self.assertEqual(self.sys.state.contributions[0]["kind"], "就业兑现")

    def test_duplicate_contribution_rejected(self):
        self.sys.record_referral("ref-1", "云舍民宿", "yard-1", evidence=["订单O-1001"])
        with self.assertRaisesRegex(ValueError, "已存在"):
            self.sys.record_referral("ref-1", "云舍民宿", "yard-1", evidence=["订单O-1002"])


if __name__ == "__main__":
    unittest.main()
