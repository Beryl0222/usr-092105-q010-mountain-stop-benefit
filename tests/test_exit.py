import unittest

from tests.test_terms import make_system


class ExitTest(unittest.TestCase):
    """旺季离场场景：交割清单拦住未清库存、预付款、设备与数据责任。"""

    def setUp(self):
        self.sys, _ = make_system("2026-12-20T09:00:00+08:00")
        self.sys.register_asset("yard-1", "集体院落", "梁家庄", "梁家庄1号院")
        self.sys.grant_term(
            "term-1",
            "yard-1",
            "山风咖啡",
            "2026-01-01T00:00:00+08:00",
            "2026-12-31T23:59:59+08:00",
        )
        self.sys.install_equipment("yard-1", "eq-1", "山风咖啡", "意式咖啡机")
        self.sys.stock_consignment("yard-1", "山风咖啡", "梁家庄蜂农", "蜂蜜", 8)
        self.sys.register_commitment("bk-1", "yard-1", "跨年旅客", prepaid=200)
        self.sys.request_exit("山风咖啡")

    def open_keys(self):
        return {i["key"] for i in self.sys.exit_checklist("山风咖啡") if i["open"]}

    def test_checklist_blocks_silent_exit(self):
        self.assertEqual(
            self.open_keys(), {"库存清结", "预付款清结", "设备移除", "数据交接", "许可腾退"}
        )
        with self.assertRaisesRegex(ValueError, "交割清单未清结"):
            self.sys.confirm_exit("山风咖啡")

    def test_exit_window_freezes_new_business(self):
        with self.assertRaisesRegex(ValueError, "不得新增入库"):
            self.sys.stock_consignment("yard-1", "山风咖啡", "梁家庄蜂农", "蜂蜜", 5)
        with self.assertRaisesRegex(ValueError, "退出交割"):
            self.sys.register_commitment("bk-2", "yard-1", "新旅客")
        with self.assertRaisesRegex(ValueError, "不得新签许可"):
            self.sys.grant_term(
                "term-9",
                "yard-1",
                "山风咖啡",
                "2027-01-01T00:00:00+08:00",
                "2027-12-31T23:59:59+08:00",
            )

    def test_physical_items_cannot_be_cleared_by_attestation(self):
        with self.assertRaisesRegex(ValueError, "业务操作清结"):
            self.sys.clear_exit_item("山风咖啡", "库存清结", "口头说清了")

    def test_full_handover_then_exit(self):
        self.sys.fulfill_commitment("bk-1")  # 预付款随履约结清
        self.sys.settle_stock("yard-1", "山风咖啡", "梁家庄蜂农", "蜂蜜", 8, "退还原主")
        self.sys.remove_equipment("yard-1", "eq-1", "运回山风咖啡仓库")
        self.sys.clear_exit_item("山风咖啡", "数据交接", "数据移交回执-2026-1220")
        self.sys.vacate_term("term-1")
        self.assertEqual(self.open_keys(), set())

        events = self.sys.confirm_exit("山风咖啡")
        self.assertEqual([e["event_type"] for e in events], ["OPERATOR_EXITED"])
        self.assertIn("山风咖啡", self.sys.state.exited_operators)

        # 退出后不得再以原主体经营或处置资产
        with self.assertRaisesRegex(ValueError, "退出"):
            self.sys.grant_term(
                "term-9",
                "yard-1",
                "山风咖啡",
                "2027-01-01T00:00:00+08:00",
                "2027-12-31T23:59:59+08:00",
            )

    def test_equipment_cannot_leave_after_contract(self):
        self.sys.fulfill_commitment("bk-1")
        self.sys.settle_stock("yard-1", "山风咖啡", "梁家庄蜂农", "蜂蜜", 8, "退还原主")
        self.sys.clear_exit_item("山风咖啡", "数据交接", "回执-001")
        # 设备故意不清，退出被拦
        with self.assertRaisesRegex(ValueError, "设备移除"):
            self.sys.confirm_exit("山风咖啡")


if __name__ == "__main__":
    unittest.main()
