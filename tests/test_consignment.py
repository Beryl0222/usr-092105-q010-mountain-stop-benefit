import unittest

from tests.test_terms import make_system


class ConsignmentTest(unittest.TestCase):
    def setUp(self):
        self.sys, _ = make_system()
        self.sys.register_asset("stall-5", "季节性摊位", "梁家庄", "红叶季5号摊")
        self.sys.grant_term(
            "term-1",
            "stall-5",
            "山风咖啡",
            "2026-03-01T00:00:00+08:00",
            "2026-11-15T23:59:59+08:00",
        )
        self.sys.stock_consignment("stall-5", "山风咖啡", "梁家庄蜂农", "蜂蜜", 20)

    def test_sale_requires_active_term(self):
        with self.assertRaisesRegex(ValueError, "有效经营许可"):
            self.sys.sell_consignment(
                "sale-x", "stall-5", "无证商贩", "梁家庄蜂农", "蜂蜜", 1, 100
            )

    def test_sale_consumes_stock(self):
        self.sys.sell_consignment("sale-1", "stall-5", "山风咖啡", "梁家庄蜂农", "蜂蜜", 5, 500)
        key = ("stall-5", "山风咖啡", "梁家庄蜂农", "蜂蜜")
        self.assertEqual(self.sys.state.stock[key], 15)
        with self.assertRaisesRegex(ValueError, "库存不足"):
            self.sys.sell_consignment("sale-2", "stall-5", "山风咖啡", "梁家庄蜂农", "蜂蜜", 99, 1)

    def test_return_attributed_to_actual_participants(self):
        """退货只归到实际参与方，不摊给无关方。"""
        self.sys.sell_consignment("sale-1", "stall-5", "山风咖啡", "梁家庄蜂农", "蜂蜜", 5, 500)
        event = self.sys.return_consignment("sale-1", 2, 200, "包装破损")
        self.assertEqual(event["payload"]["participants"], ["山风咖啡", "梁家庄蜂农"])
        sale = self.sys.state.sales["sale-1"]
        self.assertEqual((sale["returned_qty"], sale["returned_amount"]), (2, 200))
        with self.assertRaisesRegex(ValueError, "超过可退数量"):
            self.sys.return_consignment("sale-1", 4, 10, "超量退货")

    def test_return_unknown_sale_rejected(self):
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.sys.return_consignment("sale-404", 1, 10, "凭空退货")

    def test_bad_debt_scoped_and_capped(self):
        self.sys.sell_consignment("sale-1", "stall-5", "山风咖啡", "梁家庄蜂农", "蜂蜜", 5, 500)
        self.sys.return_consignment("sale-1", 1, 100, "退货")
        self.sys.write_off_bad_debt("sale-1", 300, "游客跑单")
        self.assertEqual(self.sys.state.sales["sale-1"]["bad_debt"], 300)
        with self.assertRaisesRegex(ValueError, "超过未回款"):
            self.sys.write_off_bad_debt("sale-1", 200, "超额计提")


if __name__ == "__main__":
    unittest.main()
