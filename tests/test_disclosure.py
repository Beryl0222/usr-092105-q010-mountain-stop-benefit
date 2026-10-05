import unittest

from tests.test_terms import make_system


class DisclosureTest(unittest.TestCase):
    """年底对账场景：咖啡收益有数、厕所维修有人认领、四栏分列。"""

    def setUp(self):
        self.sys, _ = make_system("2026-10-05T09:00:00+08:00")
        self.sys.register_asset("yard-1", "集体院落", "梁家庄", "梁家庄1号院")
        self.sys.register_asset("wc-1", "公共设施", "梁家庄", "村口公厕")
        self.sys.grant_term(
            "term-1",
            "yard-1",
            "山风咖啡",
            "2026-01-01T00:00:00+08:00",
            "2026-12-31T23:59:59+08:00",
            scope="咖啡角",
            employment_target=2,
        )
        self.sys.stock_consignment("yard-1", "山风咖啡", "梁家庄蜂农", "蜂蜜", 20)
        self.sys.sell_consignment("sale-1", "yard-1", "山风咖啡", "梁家庄蜂农", "蜂蜜", 5, 500)
        self.sys.return_consignment("sale-1", 1, 100, "包装破损")
        self.sys.write_off_bad_debt("sale-1", 50, "游客跑单")
        self.sys.open_work_order("wo-1", "wc-1", "水箱漏水", "村集体")
        self.sys.close_work_order("wo-1", 300, {"共益基金": 200, "山风咖啡": 100})
        self.sys.record_employment("emp-1", "山风咖啡", "村民小王", "咖啡师", evidence=["合同-017"])
        self.sys.record_referral("ref-1", "云舍民宿", "yard-1", amount=80, evidence=["订单O-1001"])
        self.sections = self.sys.publish_disclosure("2026Q4")

    def test_four_sections_present_and_separate(self):
        self.assertEqual(
            set(self.sections), {"公共资产使用", "维修负担", "就业兑现", "可分配收益"}
        )

    def test_maintenance_burden_attributed(self):
        burden = self.sections["维修负担"]["责任方汇总"]
        self.assertEqual(burden, {"共益基金": 200, "山风咖啡": 100})
        self.assertEqual(self.sections["维修负担"]["工单"][0]["责任方"], "村集体")

    def test_employment_fulfillment_tracked(self):
        row = self.sections["就业兑现"][0]
        self.assertEqual((row["运营商"], row["承诺岗位"], row["已兑现"]), ("山风咖啡", 2, 1))

    def test_distributable_income_math(self):
        income = self.sections["可分配收益"]
        self.assertEqual(income["寄售销售额"], 500)
        self.assertEqual(income["退货扣减"], 100)
        self.assertEqual(income["坏账扣减"], 50)
        self.assertEqual(income["寄售净额"], 350)
        self.assertEqual(income["维修基金支出"], 200)
        self.assertEqual(income["可分配总额"], 150)
        # 退货与坏账只归集到实际参与方
        self.assertEqual(income["退货坏账归集"], {"山风咖啡": 75, "梁家庄蜂农": 75})
        # 非货币贡献单列，不混入金额
        self.assertEqual(income["非货币贡献"], {"导流笔数": 1, "志愿工时": 0})

    def test_allocation_capped_by_disclosure(self):
        self.sys.allocate_benefit("2026Q4", "梁家庄集体", 150)
        with self.assertRaisesRegex(ValueError, "超出可分配总额"):
            self.sys.allocate_benefit("2026Q4", "梁家庄集体", 1)

    def test_allocation_requires_disclosure(self):
        with self.assertRaisesRegex(ValueError, "尚未公示"):
            self.sys.allocate_benefit("2026Q3", "梁家庄集体", 10)

    def test_disclosure_not_republished(self):
        with self.assertRaisesRegex(ValueError, "不得重复发布"):
            self.sys.publish_disclosure("2026Q4")


if __name__ == "__main__":
    unittest.main()
