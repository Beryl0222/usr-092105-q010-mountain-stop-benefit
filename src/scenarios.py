"""联调与测试用场景数据。

- :func:`compliant_season` 构造一条完整合规的 2026 旺季事件流：
  资产登记 → 季节许可与就业承诺 → 寄售/导流/志愿 → 暴雨与超载精准暂停 →
  维修认领分摊 → 季度公示 → 季末退出交割。
- ``violation_*`` 各自是一条只触发单一违规码的最小事件流，供测试逐条锁定口径。

运行 ``python3 -m src.scenarios`` 会把合规全季日志写入
``data/sample_season.json`` 供外部系统联调。
"""

import json
from collections import defaultdict
from pathlib import Path

from src.audit import audit
from src.catalog import event_aggregate
from src.validator import validate_event

# 村集体与经营者
COL_HUALANG = "collective-hualang"   # 画廊村股份经济合作社
COL_YUNQI = "collective-yunqi"       # 云栖村股份经济合作社
OP_YUNSHU = "op-yunshu-travel"       # 云舒文旅（驿站咖啡运营商）
OP_SHANJU = "op-shanju-stay"         # 山居民宿
FARMER_MA = "farmer-ma-guifeng"      # 柳湾村农户马桂凤
VENDOR_WANG = "vendor-wang-jie"      # 画廊村摊主王姐
VOLUNTEER_ZHOU = "volunteer-zhou"

# 资产
NODE_KM0 = "node-gallery-km0"
TOILET_KM0 = "toilet-gallery-km0"
YARD_STATION = "yard-hualang-station"
STALL_KM0 = "site-stall-km0"
COFFEE_EQP = "eqp-coffee-bar"
YARD_YUNQI = "yard-yunqi-08"
NODE_YUNQI = "node-yunqi-gate"

TERM_YUNSHU = "term-yunshu-2026"
TERM_SHANJU = "term-shanju-2026"
BATCH_HONEY = "batch-honey-2026"
REFERRAL = "referral-2201"
REPAIR = "repair-toilet-0710"
SUSP_STORM = "susp-storm-0812"
SUSP_OVERLOAD = "susp-overload-1002"
PLEDGE = "pledge-yunshu-2026"
NOTICE = "notice-2026q3-hualang"
ALLOC = "alloc-2026q3"
HANDOVER = "ho-yunshu-2026"


class EventLog:
    """按聚合自动维护 version、按顺序生成 event_id 的简易构造器。"""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self._versions: dict[str, int] = defaultdict(int)
        self._seq = 0

    def add(self, event_type: str, aggregate_id: str, occurred_at: str,
            summary: str, **payload) -> dict:
        self._seq += 1
        self._versions[aggregate_id] += 1
        event = {
            "event_id": f"evt-blh-{self._seq:04d}",
            "event_type": event_type,
            "aggregate_type": event_aggregate(event_type),
            "aggregate_id": aggregate_id,
            "occurred_at": occurred_at,
            "version": self._versions[aggregate_id],
            "summary": summary,
            "payload": payload,
        }
        self.events.append(event)
        return event

    @property
    def ids(self) -> set[str]:
        return {e["event_id"] for e in self.events}


def compliant_season() -> list[dict]:
    log = EventLog()

    # —— 4 月：道路节点、财政厕所、院落、摊位点、设备登记 ——
    log.add("ASSET_REGISTERED", NODE_KM0, "2026-04-20T09:00:00+08:00",
            "登记百里画廊0公里观景道路节点", asset_kind="road_node",
            village="画廊村", owner="collective", funded_by="fiscal",
            location_name="百里画廊0公里观景点",
            maintenance_responsible_party=COL_HUALANG)
    log.add("ASSET_REGISTERED", TOILET_KM0, "2026-04-20T09:05:00+08:00",
            "登记财政资金修建的0公里节点旅游厕所", asset_kind="public_toilet",
            village="画廊村", owner="government", funded_by="fiscal",
            location_name="0公里节点旅游厕所", road_node_asset_id=NODE_KM0,
            present_at_asset_id=NODE_KM0,
            maintenance_responsible_party=COL_HUALANG)
    log.add("ASSET_REGISTERED", YARD_STATION, "2026-04-20T09:10:00+08:00",
            "登记村集体院落（驿站咖啡用房）", asset_kind="collective_yard",
            village="画廊村", owner="collective", funded_by="collective",
            location_name="画廊村老村委院落",
            maintenance_responsible_party=COL_HUALANG)
    log.add("ASSET_REGISTERED", STALL_KM0, "2026-04-20T09:15:00+08:00",
            "登记0公里节点季节性摊位点位", asset_kind="stall_site",
            village="画廊村", owner="collective", funded_by="collective",
            location_name="0公里节点摊区A位", road_node_asset_id=NODE_KM0,
            present_at_asset_id=NODE_KM0,
            maintenance_responsible_party=COL_HUALANG)
    log.add("ASSET_REGISTERED", COFFEE_EQP, "2026-04-20T09:20:00+08:00",
            "登记运营商自带可搬离咖啡吧台设备", asset_kind="equipment",
            village="画廊村", owner="operator", funded_by="operator",
            location_name="驿站咖啡吧台", present_at_asset_id=YARD_STATION,
            removable=True, maintenance_responsible_party=OP_YUNSHU)
    log.add("ASSET_REGISTERED", YARD_YUNQI, "2026-04-20T09:25:00+08:00",
            "登记云栖村8号民宿院落", asset_kind="collective_yard",
            village="云栖村", owner="collective", funded_by="collective",
            location_name="云栖村8号院",
            maintenance_responsible_party=COL_YUNQI)
    log.add("ASSET_REGISTERED", NODE_YUNQI, "2026-04-20T09:30:00+08:00",
            "登记云栖入口道路节点", asset_kind="road_node",
            village="云栖村", owner="collective", funded_by="fiscal",
            location_name="云栖入口",
            maintenance_responsible_party=COL_YUNQI)

    # —— 生态容量 ——
    log.add("CAPACITY_DEFINED", "cap-yunqi-gate", "2026-04-25T10:00:00+08:00",
            "云栖入口日生态容量核定为800人次", node_asset_id=NODE_YUNQI,
            metric="persons", daily_cap=800)

    # —— 4 月底：有期限经营许可（到期重新竞价，不沉淀）——
    log.add("TERM_GRANTED", TERM_YUNSHU, "2026-04-28T14:00:00+08:00",
            "公开竞价授予云舒文旅2026旺季驿站咖啡许可（5月1日至10月25日）",
            party_id=OP_YUNSHU, village="画廊村", scope="station_cafe",
            asset_ids=[YARD_STATION], starts_at="2026-05-01T00:00:00+08:00",
            ends_at="2026-10-25T23:59:59+08:00", seasonal=True,
            grant_basis="open_bid",
            conditions={"厕所首问维护": True, "就业岗位": 6, "本地用工下限": 4})
    log.add("TERM_GRANTED", TERM_SHANJU, "2026-04-28T14:30:00+08:00",
            "授予山居民宿2026旺季经营许可", party_id=OP_SHANJU,
            village="云栖村", scope="homestay", asset_ids=[YARD_YUNQI],
            starts_at="2026-05-01T00:00:00+08:00",
            ends_at="2026-10-25T23:59:59+08:00", seasonal=True,
            grant_basis="rotation")

    # —— 就业承诺随许可一并作出 ——
    log.add("PLEDGE_MADE", PLEDGE, "2026-04-28T15:00:00+08:00",
            "云舒文旅承诺旺季提供6个岗位、本地用工不少于4人、月工资不低于2200元",
            term_id=TERM_YUNSHU, operator_party_id=OP_YUNSHU,
            positions_total=6, local_positions_min=4,
            wage_min_cents=220000, season="2026旺季")

    # —— 季节性摊位许可：季节一过必须撤场核验 ——
    log.add("STALL_PERMIT_ISSUED", "stall-wang-2026", "2026-06-28T10:00:00+08:00",
            "王姐取得0公里摊区A位夏秋季节许可", site_asset_id=STALL_KM0,
            party_id=VENDOR_WANG, village="画廊村", season="2026夏秋",
            starts_at="2026-07-01T00:00:00+08:00",
            ends_at="2026-09-30T23:59:59+08:00")

    # —— 7 月：财政厕所损坏，72 小时内认领、完工并分摊 ——
    log.add("REPAIR_OPENED", REPAIR, "2026-07-10T09:00:00+08:00",
            "0公里财政厕所供水管破裂开单", asset_id=TOILET_KM0,
            fault="供水管破裂停水", reported_by=VOLUNTEER_ZHOU,
            opened_at="2026-07-10T09:00:00+08:00")
    log.add("REPAIR_CLAIMED", REPAIR, "2026-07-10T11:00:00+08:00",
            "驿站运营商按许可条件首问认领维修", repair_order_id=REPAIR,
            claimed_by=OP_YUNSHU,
            basis="许可条件：驿站运营商承担节点财政厕所日常维修首问责任")
    log.add("REPAIR_COMPLETED", REPAIR, "2026-07-11T16:00:00+08:00",
            "厕所维修完工，费用1800元由运营商承担800、村集体承担1000",
            cost_cents=180000,
            borne_by=[{"party_id": OP_YUNSHU, "share_cents": 80000},
                      {"party_id": COL_HUALANG, "share_cents": 100000}],
            evidence_ref="ev-repair-invoice-0711",
            completed_at="2026-07-11T16:00:00+08:00")

    # —— 寄售：马桂凤200瓶土蜂蜜，未售退回 ——
    log.add("CONSIGNMENT_DELIVERED", BATCH_HONEY, "2026-07-05T08:30:00+08:00",
            "柳湾村马桂凤交付200瓶土蜂蜜寄售，单价30元，未售退回",
            term_id=TERM_YUNSHU, supplier_party_id=FARMER_MA,
            seller_party_id=OP_YUNSHU, village="画廊村",
            items_summary="土蜂蜜500g装", quantity=200, unit="瓶",
            unit_price_cents=3000, unsold_policy="return",
            delivered_at="2026-07-05T08:30:00+08:00")
    log.add("CONSIGNMENT_SOLD", BATCH_HONEY, "2026-07-20T15:00:00+08:00",
            "寄售蜂蜜售出60瓶，佣金一成", quantity=60,
            gross_cents=180000, commission_cents=18000,
            order_ref="ord-0720-11", sold_at="2026-07-20T15:00:00+08:00",
            point_of_sale_asset_id=YARD_STATION)
    log.add("CONSIGNMENT_SOLD", BATCH_HONEY, "2026-08-02T11:00:00+08:00",
            "寄售蜂蜜售出50瓶", quantity=50, gross_cents=150000,
            commission_cents=15000, order_ref="ord-0802-07",
            sold_at="2026-08-02T11:00:00+08:00",
            point_of_sale_asset_id=YARD_STATION)

    # —— 导流：二维码凭证 + 入住核销，跨村贡献才成立 ——
    log.add("REFERRAL_RECORDED", REFERRAL, "2026-07-15T13:20:00+08:00",
            "驿站咖啡向云栖山居民宿导流1位客人，留存二维码凭证",
            source_party_id=OP_YUNSHU, source_village="画廊村",
            target_party_id=OP_SHANJU, target_village="云栖村",
            node_asset_id=NODE_KM0, channel="驿站台卡二维码",
            guest_ref="g-2201", evidence_kind="qr_code",
            evidence_ref="ev-qr-2201", recorded_at="2026-07-15T13:20:00+08:00")
    log.add("REFERRAL_VERIFIED", REFERRAL, "2026-07-16T18:00:00+08:00",
            "客人实际入住bk-7716，导流证据核销，导流费50元",
            referral_id=REFERRAL, booking_id="bk-7716",
            checked_in_at="2026-07-16T17:30:00+08:00", payout_cents=5000)
    log.add("SERVICE_RECORDED", "cc-referral-2026q3", "2026-07-17T09:00:00+08:00",
            "登记2026Q3画廊村向云栖村的跨村导流贡献1人次（附已核销凭证）",
            contribution_kind="cross_village_referral",
            from_party=OP_YUNSHU, from_village="画廊村", to_village="云栖村",
            quantity=1, unit="人次", evidence_refs=[REFERRAL],
            period="2026Q3")

    # —— 志愿班次 ——
    log.add("SHIFT_SCHEDULED", "shift-zhou-0718", "2026-07-17T18:00:00+08:00",
            "排定志愿者老周7月18日节点秩序与咨询班次",
            shift_id="shift-zhou-0718", volunteer_party_id=VOLUNTEER_ZHOU,
            node_asset_id=NODE_KM0, starts_at="2026-07-18T08:00:00+08:00",
            ends_at="2026-07-18T12:00:00+08:00", duty="节点秩序与游客咨询")
    log.add("SHIFT_FULFILLED", "shift-zhou-0718", "2026-07-18T12:05:00+08:00",
            "志愿班次完成并签到", shift_id="shift-zhou-0718",
            evidence_ref="ev-shift-signin-0718", served_minutes=240)

    # —— 承载量日常观测 ——
    log.add("LOAD_REPORTED", NODE_YUNQI, "2026-07-20T17:00:00+08:00",
            "云栖入口当日承载760人次，低于容量上限",
            node_asset_id=NODE_YUNQI, date="2026-07-20", load=760)

    # —— 8 月 5 日：团餐预付款（暴雨后需要照护的既有承诺）——
    log.add("PREPAYMENT_RECEIVED", TERM_YUNSHU, "2026-08-05T10:00:00+08:00",
            "收取g-3301团餐定金200元，约定8月13日就餐",
            term_id=TERM_YUNSHU, prepayment_id="prep-3001",
            guest_ref="g-3301", amount_cents=20000, service_kind="catering",
            due_date="2026-08-13")

    # —— 8 月 12 日暴雨：只暂停受影响节点的受影响业务 ——
    log.add("SUSPENSION_ISSUED", SUSP_STORM, "2026-08-12T06:00:00+08:00",
            "暴雨红色预警：0公里节点交通进入、摊位与寄售销售、新预订暂停；"
            "已付款团餐g-3301列入受保护承诺",
            reason="storm",
            scope_asset_ids=[NODE_KM0, STALL_KM0, YARD_STATION],
            service_kinds=["traffic_entry", "stall_sale",
                           "consignment_sale", "new_booking"],
            starts_at="2026-08-12T06:00:00+08:00",
            expected_end="2026-08-13T20:00:00+08:00",
            protected_commitments=[{
                "commitment_id": "c-storm-3001", "guest_ref": "g-3301",
                "prepayment_id": "prep-3001",
                "arrangement": "团餐改期至8月15日，定金继续有效"}],
            note="已入住旅客不受影响，沿线其他节点正常经营")
    log.add("PREPAYMENT_FULFILLED", TERM_YUNSHU, "2026-08-15T13:00:00+08:00",
            "改期团餐就餐完成，定金兑现", prepayment_id="prep-3001")
    log.add("COMMITMENT_HONORED", SUSP_STORM, "2026-08-15T13:30:00+08:00",
            "暴雨暂停期间对g-3301的改期承诺已兑现",
            suspension_id=SUSP_STORM, commitment_id="c-storm-3001",
            note="团餐改期8月15日完成，双方确认",
            honored_at="2026-08-15T13:30:00+08:00")
    log.add("SUSPENSION_LIFTED", SUSP_STORM, "2026-08-15T18:00:00+08:00",
            "暴雨预警解除，0公里节点各项业务恢复",
            ended_at="2026-08-15T18:00:00+08:00")

    # 恢复后的寄售销售（在暂停窗口之外）
    log.add("CONSIGNMENT_SOLD", BATCH_HONEY, "2026-08-25T10:00:00+08:00",
            "寄售蜂蜜在摊位售出40瓶（含一笔20瓶赊销600元）",
            quantity=40, gross_cents=120000, commission_cents=12000,
            order_ref="ord-0825-03", sold_at="2026-08-25T10:00:00+08:00",
            point_of_sale_asset_id=STALL_KM0)
    # 赊销坏账：销售方信用风险，只归销售方，不能扣农户货款
    log.add("CONSIGNMENT_BAD_DEBT", BATCH_HONEY, "2026-09-10T10:00:00+08:00",
            "团建公司赊销600元确认无法收回，按销售方信用风险由运营商承担", amount_cents=60000,
            responsible_party_id=OP_YUNSHU, basis="seller_credit",
            evidence_ref="ev-debt-collection-0910")

    # —— 9 月 28 日：国庆民宿预付款（超载时需要照护的在住客人）——
    log.add("PREPAYMENT_RECEIVED", TERM_SHANJU, "2026-09-28T20:00:00+08:00",
            "收取g-1001国庆住宿预付款600元",
            term_id=TERM_SHANJU, prepayment_id="prep-7001",
            guest_ref="g-1001", amount_cents=60000, service_kind="stay",
            due_date="2026-10-04")

    # —— 就业兑现：季度工资凭证 ——
    log.add("PLEDGE_FULFILLED", PLEDGE, "2026-10-01T10:00:00+08:00",
            "三季度用工6人、本地5人，附7-9月工资表",
            term_id=TERM_YUNSHU, hires_total=6, hires_local=5,
            payroll_evidence_refs=["ev-payroll-202607", "ev-payroll-202608",
                                   "ev-payroll-202609"],
            period="2026Q3")

    # —— 10 月 2 日超载：精准暂停新预订/新导流，在住客人继续照护 ——
    log.add("LOAD_REPORTED", NODE_YUNQI, "2026-10-02T15:00:00+08:00",
            "云栖入口当日承载950人次，超过800上限",
            node_asset_id=NODE_YUNQI, date="2026-10-02", load=950)
    log.add("OVERLOAD_DECLARED", NODE_YUNQI, "2026-10-02T15:20:00+08:00",
            "宣布云栖入口超载", node_asset_id=NODE_YUNQI,
            date="2026-10-02", load=950)
    log.add("SUSPENSION_ISSUED", SUSP_OVERLOAD, "2026-10-02T15:30:00+08:00",
            "超载处置：暂停云栖入口新预订与新导流，在住客人g-1001照常接待",
            reason="overload", scope_asset_ids=[NODE_YUNQI, YARD_YUNQI],
            service_kinds=["new_booking", "new_referral", "traffic_entry"],
            starts_at="2026-10-02T15:30:00+08:00",
            expected_end="2026-10-05T12:00:00+08:00",
            protected_commitments=[{
                "commitment_id": "c-overload-7001", "guest_ref": "g-1001",
                "prepayment_id": "prep-7001",
                "arrangement": "已入住客人住宿与早餐不受影响"}],
            note="仅拦截新业务，不驱赶在住旅客")
    log.add("PREPAYMENT_FULFILLED", TERM_SHANJU, "2026-10-04T11:00:00+08:00",
            "g-1001正常退房离店，住宿服务兑现", prepayment_id="prep-7001")
    log.add("COMMITMENT_HONORED", SUSP_OVERLOAD, "2026-10-04T11:30:00+08:00",
            "超载暂停期间在住旅客g-1001承诺已兑现",
            suspension_id=SUSP_OVERLOAD, commitment_id="c-overload-7001",
            note="在住期间服务正常，客人确认",
            honored_at="2026-10-04T11:30:00+08:00")
    log.add("SUSPENSION_LIFTED", SUSP_OVERLOAD, "2026-10-05T12:00:00+08:00",
            "云栖入口承载回落，暂停解除",
            ended_at="2026-10-05T12:00:00+08:00")
    log.add("OVERLOAD_CLEARED", NODE_YUNQI, "2026-10-05T12:10:00+08:00",
            "云栖入口超载解除", node_asset_id=NODE_YUNQI, date="2026-10-05")

    # —— 季末：未售50瓶退回农户，寄售按期结清 ——
    log.add("CONSIGNMENT_RETURNED", BATCH_HONEY, "2026-10-08T09:00:00+08:00",
            "季末未售50瓶按约定退回供货农户马桂凤", quantity=50, reason="季末未售，按 unsold_policy 退回",
            returned_at="2026-10-08T09:00:00+08:00")
    log.add("CONSIGNMENT_SETTLED", BATCH_HONEY, "2026-10-16T10:00:00+08:00",
            "寄售结清：销售4500元−佣金450元，应付农户4050元（销售方坏账600元不扣农户）", paid_cents=405000,
            settled_at="2026-10-16T10:00:00+08:00")

    # —— 摊位季末撤场核验 ——
    log.add("STALL_CLOSED", "stall-wang-2026", "2026-10-01T09:00:00+08:00",
            "王姐摊位撤场，A位点位清空核验通过",
            site_asset_id=STALL_KM0, closed_at="2026-10-01T09:00:00+08:00",
            note="无遗留物，卫生合格")

    # —— 公共资产实际使用记录（期限内）——
    log.add("ASSET_USAGE_RECORDED", YARD_STATION, "2026-10-16T17:00:00+08:00",
            "记录云舒文旅5月1日至10月15日对集体院落的咖啡经营使用",
            asset_id=YARD_STATION, term_id=TERM_YUNSHU, party_id=OP_YUNSHU,
            used_from="2026-05-01T00:00:00+08:00",
            used_to="2026-10-15T23:59:59+08:00", usage_kind="cafe")
    log.add("ASSET_USAGE_RECORDED", YARD_YUNQI, "2026-10-20T17:00:00+08:00",
            "记录山居民宿5月1日至10月20日对8号院的使用",
            asset_id=YARD_YUNQI, term_id=TERM_SHANJU, party_id=OP_SHANJU,
            used_from="2026-05-01T00:00:00+08:00",
            used_to="2026-10-20T23:59:59+08:00", usage_kind="homestay")

    # —— 季度可分配收益：逐行标注依据 ——
    log.add("BENEFIT_ALLOCATED", ALLOC, "2026-10-08T18:00:00+08:00",
            "形成2026Q3分配结果：农户货款、寄售佣金、导流费、院落使用费分开列示",
            period="2026Q3",
            lines=[
                {"line_id": "L1", "party_id": FARMER_MA, "amount_cents": 405000,
                 "basis": "consignment_proceeds", "evidence_refs": [BATCH_HONEY],
                 "note": "寄售货款（销售额−佣金）"},
                {"line_id": "L2", "party_id": OP_YUNSHU, "amount_cents": 45000,
                 "basis": "consignment_commission", "evidence_refs": [BATCH_HONEY],
                 "note": "寄售佣金一成"},
                {"line_id": "L3", "party_id": OP_YUNSHU, "amount_cents": 5000,
                 "basis": "referral_commission", "evidence_refs": [REFERRAL],
                 "note": "跨村导流费（凭入住核销）"},
                {"line_id": "L4", "party_id": COL_HUALANG, "amount_cents": 20000,
                 "basis": "asset_usage_fee", "evidence_refs": [TERM_YUNSHU],
                 "note": "集体院落使用费"},
            ])
    log.add("BENEFIT_SETTLED", ALLOC, "2026-10-09T15:00:00+08:00",
            "2026Q3分配结果已逐笔兑付并留存银行回单",
            allocation_aggregate_id=ALLOC, evidence_ref="ev-bank-2026q3")

    # —— 季度公示：四板块分开 ——
    log.add("NOTICE_PUBLISHED", NOTICE, "2026-10-10T10:00:00+08:00",
            "发布画廊村2026年第三季度共益运营公示",
            quarter="2026Q3", scope_village="画廊村",
            sections={
                "asset_usage": [{
                    "term_id": TERM_YUNSHU, "party_id": OP_YUNSHU,
                    "asset_ids": [YARD_STATION], "usage_kind": "cafe",
                    "used_from": "2026-05-01T00:00:00+08:00",
                    "used_to": "2026-10-15T23:59:59+08:00",
                }],
                "repair_burden": [{
                    "repair_order_id": REPAIR, "asset_id": TOILET_KM0,
                    "fault": "供水管破裂停水", "claimed_by": OP_YUNSHU,
                    "cost_cents": 180000,
                    "borne_by": [{"party_id": OP_YUNSHU, "share_cents": 80000},
                                 {"party_id": COL_HUALANG, "share_cents": 100000}],
                }],
                "employment": {"pledges": [{
                    "term_id": TERM_YUNSHU, "positions_total": 6,
                    "local_positions_min": 4, "hires_total": 6, "hires_local": 5,
                    "payroll_evidence_refs": ["ev-payroll-202607",
                                              "ev-payroll-202608",
                                              "ev-payroll-202609"],
                }]},
                "distributable_benefit": {"allocations": [{
                    "aggregate_id": ALLOC, "total_cents": 475000, "settled": True,
                }]},
            },
            source_event_ids=[e["event_id"] for e in log.events
                              if e["aggregate_id"] in {TERM_YUNSHU, REPAIR, PLEDGE,
                                                       ALLOC, BATCH_HONEY, REFERRAL}])

    # —— 10 月 18 日：运营商提出退出，系统即时生成交割清单 ——
    exit_event = log.add("OPERATOR_EXITED", TERM_YUNSHU, "2026-10-18T09:00:00+08:00",
                         "云舒文旅提出旺季结束退出",
                         requested_at="2026-10-18T09:00:00+08:00",
                         reason="旺季许可到期，正常退出")
    snapshot = audit(log.events)
    checklist = snapshot["pending_handovers"][TERM_YUNSHU]["checklist"]
    log.add("HANDOVER_LIST_GENERATED", HANDOVER, "2026-10-18T09:00:05+08:00",
            "系统生成退出交割清单：院落与吧台设备待清场、数据责任待确认",
            term_id=TERM_YUNSHU, operator_party_id=OP_YUNSHU,
            generated_at="2026-10-18T09:00:05+08:00", checklist=checklist)

    # —— 按清单逐项交割：院落交还、可搬离设备登记放行 ——
    log.add("ASSET_RETURNED", YARD_STATION, "2026-10-19T09:00:00+08:00",
            "集体院落交还村集体，结构与固定设施完好",
            asset_id=YARD_STATION, term_id=TERM_YUNSHU,
            returned_by=OP_YUNSHU, condition_note="固定设施完好，卫生合格")
    log.add("ASSET_REMOVED", COFFEE_EQP, "2026-10-19T09:30:00+08:00",
            "运营商自带可搬离咖啡吧台按清单登记搬离",
            asset_id=COFFEE_EQP, removing_party=OP_YUNSHU,
            reason="退出交割清单内设备放行")
    log.add("HANDOVER_BLOCKER_RESOLVED", HANDOVER, "2026-10-19T10:00:00+08:00",
            "院落交还阻断项凭交接照片解除",
            handover_id=HANDOVER, blocker_id=f"B-eqp-{YARD_STATION}",
            resolution_evidence="ev-handover-yard-1019")
    log.add("HANDOVER_BLOCKER_RESOLVED", HANDOVER, "2026-10-19T10:05:00+08:00",
            "吧台设备放行阻断项凭出门登记解除",
            handover_id=HANDOVER, blocker_id=f"B-eqp-{COFFEE_EQP}",
            resolution_evidence="ev-handover-coffee-1019")
    log.add("HANDOVER_COMPLETED", HANDOVER, "2026-10-19T11:00:00+08:00",
            "交割完成：资产、款项、库存与数据责任全部移交，财政厕所仍归公共台账",
            handover_id=HANDOVER, receiving_party_id=COL_HUALANG,
            data_acknowledgement_ref="ev-data-handover-2026",
            completed_at="2026-10-19T11:00:00+08:00")

    # 自查：合规场景必须零违规、每条事件信封合法
    errors = [(e["event_id"], validate_event(e)) for e in log.events]
    bad = {eid: msgs for eid, msgs in errors if msgs}
    if bad:
        raise AssertionError(f"合规场景事件信封不合法：{bad}")
    violations = audit(log.events)["violations"]
    if violations:
        raise AssertionError(f"合规场景出现审计违规：{violations}")
    return log.events


# ================= 违规片段 =================

def _minimal_asset(log: EventLog, asset_id=NODE_KM0, village="画廊村") -> None:
    log.add("ASSET_REGISTERED", asset_id, "2026-05-01T00:00:00+08:00",
            "登记道路节点", asset_kind="road_node", village=village,
            owner="collective", funded_by="fiscal",
            location_name="测试节点", maintenance_responsible_party=COL_HUALANG)


def violation_season_too_long() -> dict:
    """季节许可超过180天 → 信封校验直接拒绝（防沉淀的第一道闸）。"""
    event = {
        "event_id": "evt-bad-season-01",
        "event_type": "TERM_GRANTED",
        "aggregate_type": "operating_term",
        "aggregate_id": "term-too-long",
        "occurred_at": "2026-04-01T00:00:00+08:00",
        "version": 1,
        "summary": "试图取得长达两年的季节性许可",
        "payload": {
            "party_id": OP_YUNSHU, "village": "画廊村", "scope": "station_cafe",
            "asset_ids": [YARD_STATION], "starts_at": "2026-05-01T00:00:00+08:00",
            "ends_at": "2028-10-31T23:59:59+08:00", "seasonal": True,
            "grant_basis": "direct",
        },
    }
    return {"event": event, "code": None, "validator": True}


def violation_usage_after_expiry() -> list[dict]:
    """到期后继续占用院落 → USAGE_OUTSIDE_TERM。"""
    log = EventLog()
    _minimal_asset(log, YARD_STATION)
    # 把院落改成院落类型
    log.events[0]["payload"]["asset_kind"] = "collective_yard"
    log.add("TERM_GRANTED", "term-exp", "2026-04-28T00:00:00+08:00",
            "短季许可", party_id=OP_YUNSHU, village="画廊村",
            scope="station_cafe", asset_ids=[YARD_STATION],
            starts_at="2026-05-01T00:00:00+08:00",
            ends_at="2026-08-31T23:59:59+08:00", seasonal=True,
            grant_basis="open_bid")
    log.add("TERM_EXPIRED", "term-exp", "2026-09-01T00:00:00+08:00", "许可到期")
    log.add("ASSET_USAGE_RECORDED", YARD_STATION, "2026-09-05T00:00:00+08:00",
            "到期后仍占用院落经营", asset_id=YARD_STATION, term_id="term-exp",
            party_id=OP_YUNSHU, used_from="2026-09-01T00:00:00+08:00",
            used_to="2026-09-30T23:59:59+08:00", usage_kind="cafe")
    return log.events


def violation_unverified_referral_claim() -> list[dict]:
    """把未经入住核销的导流写进跨村贡献 → CONTRIBUTION_UNVERIFIED_REFERRAL。"""
    log = EventLog()
    _minimal_asset(log)
    log.add("REFERRAL_RECORDED", "ref-fake", "2026-07-15T00:00:00+08:00",
            "登记导流但客人从未入住", source_party_id=OP_YUNSHU,
            source_village="画廊村", target_party_id=OP_SHANJU,
            target_village="云栖村", node_asset_id=NODE_KM0,
            channel="台卡", guest_ref="g-x", evidence_kind="qr_code",
            evidence_ref="ev-qr-x", recorded_at="2026-07-15T00:00:00+08:00")
    log.add("SERVICE_RECORDED", "cc-fake", "2026-07-16T00:00:00+08:00",
            "仅凭一张二维码就申报跨村导流贡献",
            contribution_kind="cross_village_referral",
            from_party=OP_YUNSHU, from_village="画廊村", to_village="云栖村",
            quantity=1, unit="人次", evidence_refs=["ref-fake"],
            period="2026Q3")
    return log.events


def violation_bad_debt_to_farmer() -> list[dict]:
    """销售方坏账摊给农户 → BAD_DEBT_WRONG_PARTY。"""
    log = EventLog()
    _minimal_asset(log, YARD_STATION)
    log.events[0]["payload"]["asset_kind"] = "collective_yard"
    log.add("TERM_GRANTED", "term-bd", "2026-05-01T00:00:00+08:00",
            "许可", party_id=OP_YUNSHU, village="画廊村", scope="station_cafe",
            asset_ids=[YARD_STATION], starts_at="2026-05-01T00:00:00+08:00",
            ends_at="2026-10-25T23:59:59+08:00", seasonal=True,
            grant_basis="open_bid")
    log.add("CONSIGNMENT_DELIVERED", "batch-bd", "2026-07-01T00:00:00+08:00",
            "寄售交付", term_id="term-bd", supplier_party_id=FARMER_MA,
            seller_party_id=OP_YUNSHU, village="画廊村", items_summary="蜂蜜",
            quantity=10, unit="瓶", unit_price_cents=3000,
            unsold_policy="return", delivered_at="2026-07-01T00:00:00+08:00")
    log.add("CONSIGNMENT_SOLD", "batch-bd", "2026-07-10T00:00:00+08:00",
            "售出", quantity=10, gross_cents=30000, commission_cents=3000,
            order_ref="o1", sold_at="2026-07-10T00:00:00+08:00")
    log.add("CONSIGNMENT_BAD_DEBT", "batch-bd", "2026-08-01T00:00:00+08:00",
            "运营商把自己赊销的坏账记到农户头上",
            amount_cents=30000, responsible_party_id=FARMER_MA,
            basis="seller_credit", evidence_ref="ev-x")
    return log.events


def violation_business_during_storm() -> list[dict]:
    """暴雨暂停期间仍在摊位销售 → SUSPENSION_VIOLATION。"""
    log = EventLog()
    _minimal_asset(log)
    _minimal_asset(log, STALL_KM0)
    log.events[1]["payload"]["asset_kind"] = "stall_site"
    log.add("SUSPENSION_ISSUED", "sus-x", "2026-08-12T06:00:00+08:00",
            "暴雨暂停摊位销售", reason="storm", scope_asset_ids=[STALL_KM0],
            service_kinds=["stall_sale"], starts_at="2026-08-12T06:00:00+08:00")
    log.add("TERM_GRANTED", "term-x", "2026-05-01T00:00:00+08:00",
            "许可", party_id=OP_YUNSHU, village="画廊村", scope="station_cafe",
            asset_ids=[STALL_KM0], starts_at="2026-05-01T00:00:00+08:00",
            ends_at="2026-10-25T23:59:59+08:00", seasonal=True,
            grant_basis="open_bid")
    log.add("CONSIGNMENT_DELIVERED", "batch-x", "2026-08-01T00:00:00+08:00",
            "寄售", term_id="term-x", supplier_party_id=FARMER_MA,
            seller_party_id=OP_YUNSHU, village="画廊村", items_summary="蜂蜜",
            quantity=10, unit="瓶", unit_price_cents=3000,
            unsold_policy="return", delivered_at="2026-08-01T00:00:00+08:00")
    log.add("CONSIGNMENT_SOLD", "batch-x", "2026-08-13T00:00:00+08:00",
            "暴雨中仍在摊位售卖", quantity=1, gross_cents=3000,
            commission_cents=300, order_ref="o2",
            sold_at="2026-08-13T00:00:00+08:00",
            point_of_sale_asset_id=STALL_KM0)
    return log.events


def violation_lift_with_honoring_guest() -> list[dict]:
    """承诺未照护就解封 → COMMITMENT_NOT_HONORED。"""
    log = EventLog()
    _minimal_asset(log, YARD_STATION)
    log.events[0]["payload"]["asset_kind"] = "collective_yard"
    log.add("TERM_GRANTED", "term-g", "2026-05-01T00:00:00+08:00",
            "许可", party_id=OP_YUNSHU, village="画廊村", scope="station_cafe",
            asset_ids=[YARD_STATION], starts_at="2026-05-01T00:00:00+08:00",
            ends_at="2026-10-25T23:59:59+08:00", seasonal=True,
            grant_basis="open_bid")
    log.add("PREPAYMENT_RECEIVED", TERM_YUNSHU, "2026-08-05T00:00:00+08:00",
            "团餐定金", term_id="term-g", prepayment_id="prep-g",
            guest_ref="g", amount_cents=20000, service_kind="catering",
            due_date="2026-08-13")
    log.add("SUSPENSION_ISSUED", "sus-g", "2026-08-12T06:00:00+08:00",
            "暴雨检修暂停", reason="storm", scope_asset_ids=[YARD_STATION],
            service_kinds=["new_booking"], starts_at="2026-08-12T06:00:00+08:00",
            protected_commitments=[{"commitment_id": "c-g",
                                    "prepayment_id": "prep-g"}])
    log.add("SUSPENSION_LIFTED", "sus-g", "2026-08-15T00:00:00+08:00",
            "未照护客人即解封", ended_at="2026-08-15T00:00:00+08:00")
    return log.events


def violation_repair_never_claimed() -> list[dict]:
    """财政厕所工单超过72小时无人认领 → REPAIR_NEVER_CLAIMED。"""
    log = EventLog()
    _minimal_asset(log, TOILET_KM0)
    log.events[0]["payload"]["asset_kind"] = "public_toilet"
    log.add("REPAIR_OPENED", "ro-orphan", "2026-07-10T09:00:00+08:00",
            "财政厕所损坏开单后无人认领", asset_id=TOILET_KM0,
            fault="化粪池堵塞", reported_by=VOLUNTEER_ZHOU,
            opened_at="2026-07-10T09:00:00+08:00")
    # 用四天后的一条无关事件把审计时钟推过认领期限
    log.add("SHIFT_SCHEDULED", "shift-late", "2026-07-15T08:00:00+08:00",
            "事后班次（用于推进审计时点）", shift_id="shift-late",
            volunteer_party_id=VOLUNTEER_ZHOU, node_asset_id=TOILET_KM0,
            starts_at="2026-07-15T08:00:00+08:00",
            ends_at="2026-07-15T12:00:00+08:00", duty="咨询")
    return log.events


def violation_overload_no_response() -> list[dict]:
    """超载只上报不处置 → LOAD_OVER_CAP_WITHOUT_DECLARATION。"""
    log = EventLog()
    _minimal_asset(log)
    log.add("CAPACITY_DEFINED", "cap-x", "2026-05-01T00:00:00+08:00",
            "容量800", node_asset_id=NODE_KM0, metric="persons", daily_cap=800)
    log.add("LOAD_REPORTED", NODE_KM0, "2026-10-02T00:00:00+08:00",
            "承载950但既不宣布超载也不暂停",
            node_asset_id=NODE_KM0, date="2026-10-02", load=950)
    return log.events


def violation_exit_smuggle() -> list[dict]:
    """退出提出后、清单生成前搬设备 → EXIT_FREEZE。"""
    log = EventLog()
    _minimal_asset(log, COFFEE_EQP)
    log.events[0]["payload"]["asset_kind"] = "equipment"
    log.events[0]["payload"]["owner"] = "operator"
    log.events[0]["payload"]["removable"] = True
    log.add("TERM_GRANTED", "term-exit", "2026-05-01T00:00:00+08:00",
            "许可", party_id=OP_YUNSHU, village="画廊村", scope="station_cafe",
            asset_ids=[COFFEE_EQP], starts_at="2026-05-01T00:00:00+08:00",
            ends_at="2026-10-25T23:59:59+08:00", seasonal=True,
            grant_basis="open_bid")
    log.add("OPERATOR_EXITED", "term-exit", "2026-10-18T00:00:00+08:00",
            "运营商提出退出", requested_at="2026-10-18T00:00:00+08:00",
            reason="到期退出")
    log.add("ASSET_REMOVED", COFFEE_EQP, "2026-10-18T01:00:00+08:00",
            "清单未出就连夜搬离设备", asset_id=COFFEE_EQP,
            removing_party=OP_YUNSHU, reason="私自搬离")
    return log.events


def violation_handover_incomplete() -> list[dict]:
    """院落交还后未登记阻断解除就完成交割 → HANDOVER_BLOCKED。"""
    log = EventLog()
    _minimal_asset(log, YARD_STATION)
    log.events[0]["payload"]["asset_kind"] = "collective_yard"
    log.add("TERM_GRANTED", "term-hi", "2026-05-01T00:00:00+08:00",
            "许可", party_id=OP_YUNSHU, village="画廊村", scope="station_cafe",
            asset_ids=[YARD_STATION], starts_at="2026-05-01T00:00:00+08:00",
            ends_at="2026-10-25T23:59:59+08:00", seasonal=True,
            grant_basis="open_bid")
    log.add("OPERATOR_EXITED", "term-hi", "2026-10-18T00:00:00+08:00",
            "运营商提出退出", requested_at="2026-10-18T00:00:00+08:00",
            reason="到期退出")
    snapshot = audit(log.events)
    checklist = snapshot["pending_handovers"]["term-hi"]["checklist"]
    log.add("HANDOVER_LIST_GENERATED", "ho-hi", "2026-10-18T00:00:05+08:00",
            "交割清单生成", term_id="term-hi", operator_party_id=OP_YUNSHU,
            generated_at="2026-10-18T00:00:05+08:00", checklist=checklist)
    # 院落物理上已交还，但漏登 BLOCKER_RESOLVED 就宣布交割完成
    log.add("ASSET_RETURNED", YARD_STATION, "2026-10-19T00:00:00+08:00",
            "院落交还", asset_id=YARD_STATION, term_id="term-hi",
            returned_by=OP_YUNSHU, condition_note="完好")
    log.add("HANDOVER_COMPLETED", "ho-hi", "2026-10-19T11:00:00+08:00",
            "阻断项未解除即宣布交割完成", handover_id="ho-hi",
            receiving_party_id=COL_HUALANG,
            data_acknowledgement_ref="ev-data-hi",
            completed_at="2026-10-19T11:00:00+08:00")
    return log.events


def violation_notice_missing_repair() -> list[dict]:
    """季度公示隐瞒未公开工单 → NOTICE_REPAIR_OMITTED。"""
    log = EventLog()
    _minimal_asset(log, TOILET_KM0)
    log.events[0]["payload"]["asset_kind"] = "public_toilet"
    log.add("TERM_GRANTED", "term-n", "2026-05-01T00:00:00+08:00",
            "许可", party_id=OP_YUNSHU, village="画廊村", scope="station_cafe",
            asset_ids=[TOILET_KM0], starts_at="2026-05-01T00:00:00+08:00",
            ends_at="2026-10-25T23:59:59+08:00", seasonal=True,
            grant_basis="open_bid")
    log.add("REPAIR_OPENED", "ro-q3", "2026-08-10T09:00:00+08:00",
            "厕所维修开单", asset_id=TOILET_KM0, fault="门锁损坏",
            reported_by=VOLUNTEER_ZHOU, opened_at="2026-08-10T09:00:00+08:00")
    log.add("REPAIR_CLAIMED", "ro-q3", "2026-08-10T10:00:00+08:00",
            "认领", repair_order_id="ro-q3", claimed_by=OP_YUNSHU, basis="许可条件")
    log.add("REPAIR_COMPLETED", "ro-q3", "2026-08-11T00:00:00+08:00",
            "完工", cost_cents=10000,
            borne_by=[{"party_id": OP_YUNSHU, "share_cents": 10000}],
            evidence_ref="ev-r", completed_at="2026-08-11T00:00:00+08:00")
    log.add("NOTICE_PUBLISHED", "notice-x", "2026-10-10T00:00:00+08:00",
            "公示只字不提维修负担", quarter="2026Q3", scope_village="画廊村",
            sections={
                "asset_usage": [{"term_id": "term-n"}],
                "repair_burden": [],
                "employment": {"pledges": []},
                "distributable_benefit": {"allocations": []},
            },
            source_event_ids=[])
    return log.events


def violation_settle_amount() -> list[dict]:
    """结算时少付农户货款（把佣金/坏账混扣）→ SETTLE_AMOUNT_MISMATCH。"""
    log = EventLog()
    _minimal_asset(log, YARD_STATION)
    log.events[0]["payload"]["asset_kind"] = "collective_yard"
    log.add("TERM_GRANTED", "term-s", "2026-05-01T00:00:00+08:00",
            "许可", party_id=OP_YUNSHU, village="画廊村", scope="station_cafe",
            asset_ids=[YARD_STATION], starts_at="2026-05-01T00:00:00+08:00",
            ends_at="2026-10-25T23:59:59+08:00", seasonal=True,
            grant_basis="open_bid")
    log.add("CONSIGNMENT_DELIVERED", "batch-s", "2026-07-01T00:00:00+08:00",
            "寄售", term_id="term-s", supplier_party_id=FARMER_MA,
            seller_party_id=OP_YUNSHU, village="画廊村", items_summary="蜂蜜",
            quantity=10, unit="瓶", unit_price_cents=3000,
            unsold_policy="return", delivered_at="2026-07-01T00:00:00+08:00")
    log.add("CONSIGNMENT_SOLD", "batch-s", "2026-07-10T00:00:00+08:00",
            "售罄", quantity=10, gross_cents=30000, commission_cents=3000,
            order_ref="o", sold_at="2026-07-10T00:00:00+08:00")
    log.add("CONSIGNMENT_SETTLED", "batch-s", "2026-08-01T00:00:00+08:00",
            "只向农户支付200元（应付270元）",
            paid_cents=20000, settled_at="2026-08-01T00:00:00+08:00")
    return log.events


VIOLATION_CASES = {
    "USAGE_OUTSIDE_TERM": (violation_usage_after_expiry, False),
    "CONTRIBUTION_UNVERIFIED_REFERRAL": (violation_unverified_referral_claim, False),
    "BAD_DEBT_WRONG_PARTY": (violation_bad_debt_to_farmer, False),
    "SUSPENSION_VIOLATION": (violation_business_during_storm, False),
    "COMMITMENT_NOT_HONORED": (violation_lift_with_honoring_guest, False),
    "REPAIR_NEVER_CLAIMED": (violation_repair_never_claimed, False),
    "LOAD_OVER_CAP_WITHOUT_DECLARATION": (violation_overload_no_response, False),
    "EXIT_FREEZE": (violation_exit_smuggle, False),
    "HANDOVER_BLOCKED": (violation_handover_incomplete, False),
    "NOTICE_REPAIR_OMITTED": (violation_notice_missing_repair, False),
    "SETTLE_AMOUNT_MISMATCH": (violation_settle_amount, False),
}


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "data" / "sample_season.json"
    out.write_text(json.dumps(compliant_season(), ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"已写出合规全季样例：{out}")


if __name__ == "__main__":
    main()
