import unittest

from tests.test_terms import make_system


class SuspensionTest(unittest.TestCase):
    def setUp(self):
        self.sys, _ = make_system()
        self.sys.register_asset("yard-1", "集体院落", "梁家庄", "梁家庄1号院")
        self.sys.register_asset("stall-5", "季节性摊位", "梁家庄", "红叶季5号摊")
        self.sys.grant_term(
            "term-1",
            "stall-5",
            "山风咖啡",
            "2026-03-01T00:00:00+08:00",
            "2026-11-15T23:59:59+08:00",
        )
        self.sys.stock_consignment("stall-5", "山风咖啡", "梁家庄蜂农", "蜂蜜", 10)

    def test_suspension_protects_checked_in_guests(self):
        """暴雨暂停受影响业务，已入住旅客的既有承诺照常履约。"""
        self.sys.register_commitment("bk-1", "stall-5", "已入住旅客甲", prepaid=300)
        suspension_id = self.sys.suspend_assets(["stall-5"], "暴雨", note="河道涨水")

        event = self.sys.store.for_aggregate("shared_asset", "stall-5")[-1]
        self.assertEqual(event["payload"]["protected_commitments"], ["bk-1"])

        with self.assertRaisesRegex(ValueError, "暂停"):
            self.sys.register_commitment("bk-2", "stall-5", "新旅客乙")
        with self.assertRaisesRegex(ValueError, "暂停"):
            self.sys.sell_consignment("sale-1", "stall-5", "山风咖啡", "梁家庄蜂农", "蜂蜜", 1, 100)

        self.sys.fulfill_commitment("bk-1")  # 既有承诺照常
        self.assertEqual(self.sys.state.commitments["bk-1"]["status"], "fulfilled")

        self.sys.resume_assets(suspension_id)
        self.sys.register_commitment("bk-2", "stall-5", "新旅客乙")
        self.assertEqual(self.sys.state.commitments["bk-2"]["status"], "open")

    def test_suspension_is_precise_not_blanket(self):
        """只暂停受影响资产，未受影响的院落照常营业。"""
        self.sys.suspend_assets(["stall-5"], "检修")
        self.sys.register_commitment("bk-1", "yard-1", "院落旅客")
        self.assertEqual(self.sys.state.commitments["bk-1"]["status"], "open")

    def test_capacity_blocks_overload(self):
        """生态容量满员即拒新承诺，防止超载。"""
        self.sys.declare_capacity("yard-1", limit=1)
        self.sys.register_commitment("bk-1", "yard-1", "旅客甲")
        with self.assertRaisesRegex(ValueError, "生态容量"):
            self.sys.register_commitment("bk-2", "yard-1", "旅客乙")

    def test_invalid_suspend_reason_rejected(self):
        with self.assertRaisesRegex(ValueError, "暂停原因"):
            self.sys.suspend_assets(["stall-5"], "心情不好")


if __name__ == "__main__":
    unittest.main()
