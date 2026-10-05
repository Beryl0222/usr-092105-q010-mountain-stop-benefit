"""年底对账演示：把百里画廊共益运营的一年跑一遍。

场景取自真实痛点——咖啡收益要有数、财政修建的厕所维修有人认领、
民宿导流凭证据记账、退货坏账只归实际参与方、暴雨精准暂停但照顾
已入住旅客、许可到期不得沉淀成永久占用、季度公示四栏分列、
运营商退出先过交割清单。

运行：python3 examples/year_end_close.py
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.system import BenefitOpsSystem  # noqa: E402

TZ = timezone(timedelta(hours=8))
current = [datetime(2026, 10, 1, 9, tzinfo=TZ)]
ops = BenefitOpsSystem(clock=lambda: current[0])


def at(day, hour=9):
    """把账本时钟拨到 2026 年 10 月的某一天。"""
    current[0] = datetime(2026, 10, day, hour, tzinfo=TZ)


def show(title, value):
    print(f"\n=== {title} ===")
    print(json.dumps(value, ensure_ascii=False, indent=2))


# --- 资产与许可 ---------------------------------------------------------
ops.register_asset("node-liangjia", "道路节点", "梁家庄", "梁家庄路口")
ops.register_asset("wc-liangjia", "公共设施", "梁家庄", "村口公厕（财政修建）")
ops.register_asset("yard-liangjia-3", "集体院落", "梁家庄", "梁家庄3号院")
ops.register_asset("stall-hongye-05", "季节性摊位", "梁家庄", "红叶季5号摊")
ops.declare_capacity("yard-liangjia-3", limit=12, note="院落同时接待上限")

ops.grant_term(
    "term-coffee",
    "yard-liangjia-3",
    "山风咖啡",
    "2026-01-01T00:00:00+08:00",
    "2026-12-31T23:59:59+08:00",
    scope="咖啡角",
    employment_target=3,
)
ops.grant_term(
    "term-stall",
    "stall-hongye-05",
    "山风咖啡",
    "2026-10-01T00:00:00+08:00",
    "2026-11-15T23:59:59+08:00",
)
ops.install_equipment("yard-liangjia-3", "eq-coffee-machine", "山风咖啡", "意式咖啡机")

# --- 旺季经营 -----------------------------------------------------------
at(2)
ops.register_commitment("bk-1001", "yard-liangjia-3", "已入住旅客·王女士", prepaid=300)
ops.record_referral(
    "ref-1001", "云舍民宿", "yard-liangjia-3", amount=80, evidence=["订单O-1001", "入住记录C-203"]
)
ops.stock_consignment("stall-hongye-05", "山风咖啡", "梁家庄蜂农", "蜂蜜", 30)
ops.sell_consignment("sale-1001", "stall-hongye-05", "山风咖啡", "梁家庄蜂农", "蜂蜜", 10, 1000)
ops.return_consignment("sale-1001", 1, 100, "包装破损")
ops.write_off_bad_debt("sale-1001", 50, "游客跑单未回款")
ops.record_volunteer_shift("shift-1001", "村民小李", "node-liangjia", 4, evidence=["签到表-1002"])
ops.record_employment("emp-1001", "山风咖啡", "村民小王", "咖啡师", evidence=["劳动合同-2026-017"])

# --- 暴雨：精准暂停受影响业务，照顾已入住旅客 ---------------------------
at(5, 6)
suspension = ops.suspend_assets(["stall-hongye-05", "node-liangjia"], "暴雨", note="河道涨水")
try:
    ops.sell_consignment("sale-1002", "stall-hongye-05", "山风咖啡", "梁家庄蜂农", "蜂蜜", 1, 100)
except ValueError as exc:
    print(f"\n[暴雨期间寄售被拦] {exc}")
ops.fulfill_commitment("bk-1001")  # 已入住旅客的既有承诺照常履约
at(7, 18)
ops.resume_assets(suspension)

# --- 财政修建的厕所维修：开单即定责任方 ----------------------------------
at(10)
ops.open_work_order("wo-wc-1", "wc-liangjia", "水箱漏水", "村集体")
ops.close_work_order("wo-wc-1", 300, {"共益基金": 200, "山风咖啡": 100})

# --- 摊位许可到期：不能沉淀成永久占用 ------------------------------------
current[0] = datetime(2026, 11, 20, 9, tzinfo=TZ)
ops.expire_due_terms()
try:
    ops.sell_consignment("sale-1003", "stall-hongye-05", "山风咖啡", "梁家庄蜂农", "蜂蜜", 1, 100)
except ValueError as exc:
    print(f"\n[许可到期经营被拦] {exc}")
ops.settle_stock("stall-hongye-05", "山风咖啡", "梁家庄蜂农", "蜂蜜", 21, "退还原主")
ops.vacate_term("term-stall")

# --- 季度公示：四栏分列 ---------------------------------------------------
current[0] = datetime(2026, 12, 31, 10, tzinfo=TZ)
sections = ops.publish_disclosure("2026Q4")
show("2026Q4 季度公示", sections)
ops.allocate_benefit("2026Q4", "梁家庄集体", sections["可分配收益"]["可分配总额"], note="集体留存")

# --- 运营商退出：交割清单未清不得离场 -------------------------------------
current[0] = datetime(2027, 1, 5, 9, tzinfo=TZ)
ops.request_exit("山风咖啡")
show("交割清单（申请退出时）", ops.exit_checklist("山风咖啡"))
try:
    ops.confirm_exit("山风咖啡")
except ValueError as exc:
    print(f"\n[退出被拦] {exc}")

ops.remove_equipment("yard-liangjia-3", "eq-coffee-machine", "运回山风咖啡仓库")
ops.clear_exit_item("山风咖啡", "数据交接", "数据移交回执-2027-0105")
ops.vacate_term("term-coffee")
ops.confirm_exit("山风咖啡")
print("\n[退出完成] 山风咖啡交割完毕，设备、库存、预付款、数据责任均已清结")

ops.store.dump_jsonl("/tmp/baili-gallery-events.jsonl")
print(f"\n事件账共 {len(ops.store.all())} 条，已导出 /tmp/baili-gallery-events.jsonl")
