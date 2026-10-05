import unittest
from datetime import datetime, timedelta, timezone

from src.system import BenefitOpsSystem

TZ = timezone(timedelta(hours=8))


class Clock:
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t


def make_system(start="2026-03-01T09:00:00+08:00"):
    clock = Clock(datetime.fromisoformat(start))
    return BenefitOpsSystem(clock=clock), clock


class TermTest(unittest.TestCase):
    def setUp(self):
        self.sys, self.clock = make_system()
        self.sys.register_asset("yard-1", "集体院落", "梁家庄", "梁家庄1号院")
        self.sys.grant_term(
            "term-1",
            "yard-1",
            "山风咖啡",
            "2026-03-01T00:00:00+08:00",
            "2026-06-30T23:59:59+08:00",
        )

    def test_expired_term_blocks_operation(self):
        self.sys.stock_consignment("yard-1", "山风咖啡", "梁家庄蜂农", "蜂蜜", 10)
        self.clock.t = datetime(2026, 7, 2, 9, tzinfo=TZ)
        self.sys.expire_due_terms()
        self.assertEqual(self.sys.state.terms["term-1"]["status"], "expired")
        with self.assertRaisesRegex(ValueError, "已到期"):
            self.sys.stock_consignment("yard-1", "山风咖啡", "梁家庄蜂农", "蜂蜜", 5)

    def test_expired_occupation_blocks_regrant_until_vacated(self):
        """许可到期不能沉淀成永久占用：未腾退前不得授予他人。"""
        self.clock.t = datetime(2026, 7, 2, 9, tzinfo=TZ)
        self.sys.expire_due_terms()
        with self.assertRaisesRegex(ValueError, "不得重复授予"):
            self.sys.grant_term(
                "term-2",
                "yard-1",
                "新运营商",
                "2026-07-03T00:00:00+08:00",
                "2026-12-31T23:59:59+08:00",
            )
        self.sys.vacate_term("term-1")
        self.sys.grant_term(
            "term-2",
            "yard-1",
            "新运营商",
            "2026-07-03T00:00:00+08:00",
            "2026-12-31T23:59:59+08:00",
        )
        self.assertEqual(self.sys.state.terms["term-2"]["operator"], "新运营商")

    def test_vacate_blocked_by_open_commitment_and_stock(self):
        self.sys.stock_consignment("yard-1", "山风咖啡", "梁家庄蜂农", "蜂蜜", 3)
        self.sys.register_commitment("bk-1", "yard-1", "已入住旅客甲", prepaid=200)
        with self.assertRaisesRegex(ValueError, "承诺"):
            self.sys.vacate_term("term-1")
        self.sys.fulfill_commitment("bk-1")
        with self.assertRaisesRegex(ValueError, "库存"):
            self.sys.vacate_term("term-1")
        self.sys.settle_stock("yard-1", "山风咖啡", "梁家庄蜂农", "蜂蜜", 3, "退还原主")
        self.sys.vacate_term("term-1")
        self.assertEqual(self.sys.state.terms["term-1"]["status"], "vacated")

    def test_renew_only_before_expiry(self):
        self.sys.renew_term("term-1", "2026-09-30T23:59:59+08:00")
        self.assertEqual(self.sys.state.terms["term-1"]["end"], "2026-09-30T23:59:59+08:00")
        self.clock.t = datetime(2026, 12, 1, 9, tzinfo=TZ)
        self.sys.expire_due_terms()
        with self.assertRaisesRegex(ValueError, "续期"):
            self.sys.renew_term("term-1", "2027-06-30T23:59:59+08:00")


if __name__ == "__main__":
    unittest.main()
