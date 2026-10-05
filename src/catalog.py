"""百里画廊沿线共益运营事件目录。

本模块是契约的唯一事实来源：
- ``AGGREGATES`` 声明全部业务对象，其中 ``boundary=True`` 的四个对象是跨村交换边界；
- ``EVENTS`` 声明事件类型、所属聚合、中文说明与载荷字段约束；
- ``RULES`` 集中维护审计口径（期限上限、工单认领先期等）。

``validator`` 与 ``schema_render`` 都从本目录生成，避免多处维护造成语义漂移。
"""

# 聚合：shared_asset / operating_term / community_contribution / benefit_distribution
# 是跨村交换边界，村与村、村与运营商之间只通过这四类对象的事件交换事实。
AGGREGATES: dict[str, dict[str, object]] = {
    "shared_asset": {
        "label": "公共资产与道路节点",
        "boundary": True,
        "note": "道路节点、财政厕所、公共设施、村集体院落、摊位点位、在场设备",
    },
    "operating_term": {
        "label": "经营许可与期限",
        "boundary": True,
        "note": "驿站、民宿、院落、设施经营的有期限授权，到期不得沉淀为永久占用",
    },
    "community_contribution": {
        "label": "跨村贡献交换",
        "boundary": True,
        "note": "跨村导流、志愿互助等需要在村际结算的贡献，必须附证据",
    },
    "benefit_distribution": {
        "label": "收益分配结果",
        "boundary": True,
        "note": "可分配收益与寄售货款等分账结果，逐行标注依据",
    },
    "seasonal_stall": {"label": "季节性摊位", "boundary": False},
    "consignment": {"label": "农产品寄售", "boundary": False},
    "referral": {"label": "民宿导流", "boundary": False},
    "volunteer_shift": {"label": "志愿班次", "boundary": False},
    "employment_pledge": {"label": "就业承诺", "boundary": False},
    "eco_capacity": {"label": "生态容量", "boundary": False},
    "suspension": {"label": "业务暂停与旅客承诺", "boundary": False},
    "repair_order": {"label": "维修工单", "boundary": False},
    "public_notice": {"label": "季度公示", "boundary": False},
    "handover": {"label": "退出交割清单", "boundary": False},
}

# 审计口径。季节许可只覆盖一个旺季；维修工单 72 小时内必须有人认领。
RULES = {
    "max_seasonal_term_days": 180,
    "repair_claim_hours": 72,
}

# 载荷字段说明：
#   "req" 为必填字段，"opt" 为可选字段；
#   字段约束支持 type(string/integer/boolean/array/object)、enum、items、min、min_items。
EVENTS: dict[str, dict[str, object]] = {
    # —— 公共资产与道路节点 ——
    "ASSET_REGISTERED": {
        "aggregate": "shared_asset",
        "label": "登记公共资产或道路节点",
        "req": {
            "asset_kind": {"enum": ["road_node", "public_toilet", "public_facility",
                                    "collective_yard", "stall_site", "equipment"]},
            "village": {"type": "string"},
            "owner": {"enum": ["collective", "government", "operator"]},
            "funded_by": {"enum": ["fiscal", "collective", "social", "operator"]},
            "location_name": {"type": "string"},
            "maintenance_responsible_party": {"type": "string"},
        },
        "opt": {
            "road_node_asset_id": {"type": "string"},
            "present_at_asset_id": {"type": "string"},
            "removable": {"type": "boolean"},
        },
    },
    "ASSET_USAGE_RECORDED": {
        "aggregate": "shared_asset",
        "label": "记录某期限内对公共资产的实际使用",
        "req": {
            "asset_id": {"type": "string"},
            "term_id": {"type": "string"},
            "party_id": {"type": "string"},
            "used_from": {"type": "string"},
            "used_to": {"type": "string"},
            "usage_kind": {"enum": ["cafe", "homestay", "stall", "storage", "service", "other"]},
        },
    },
    "ASSET_RETURNED": {
        "aggregate": "shared_asset",
        "label": "到期交还公共资产",
        "req": {
            "asset_id": {"type": "string"},
            "term_id": {"type": "string"},
            "returned_by": {"type": "string"},
            "condition_note": {"type": "string"},
        },
    },
    "ASSET_REMOVED": {
        "aggregate": "shared_asset",
        "label": "设备或设施搬离点位（受退出交割约束）",
        "req": {
            "asset_id": {"type": "string"},
            "removing_party": {"type": "string"},
            "reason": {"type": "string"},
        },
    },
    # —— 经营许可与期限 ——
    "TERM_GRANTED": {
        "aggregate": "operating_term",
        "label": "授予有期限经营许可",
        "req": {
            "party_id": {"type": "string"},
            "village": {"type": "string"},
            "scope": {"enum": ["station_cafe", "homestay", "facility_operation", "collective_yard"]},
            "asset_ids": {"type": "array", "items": {"type": "string"}, "min_items": 1},
            "starts_at": {"type": "string"},
            "ends_at": {"type": "string"},
            "seasonal": {"type": "boolean"},
            "grant_basis": {"enum": ["open_bid", "rotation", "direct"]},
        },
        "opt": {"conditions": {"type": "object"}},
    },
    "TERM_EXPIRED": {
        "aggregate": "operating_term",
        "label": "经营许可到期失效",
        "req": {},
        "opt": {"note": {"type": "string"}},
    },
    "TERM_REVOKED": {
        "aggregate": "operating_term",
        "label": "经营许可因违规被撤销",
        "req": {"reason": {"type": "string"}},
    },
    "PREPAYMENT_RECEIVED": {
        "aggregate": "operating_term",
        "label": "运营商收取旅客预付款",
        "req": {
            "term_id": {"type": "string"},
            "prepayment_id": {"type": "string"},
            "guest_ref": {"type": "string"},
            "amount_cents": {"type": "integer", "min": 0},
            "service_kind": {"enum": ["stay", "catering", "stall_order"]},
            "due_date": {"type": "string"},
        },
    },
    "PREPAYMENT_FULFILLED": {
        "aggregate": "operating_term",
        "label": "预付款对应服务已兑现",
        "req": {"prepayment_id": {"type": "string"}},
    },
    "PREPAYMENT_REFUNDED": {
        "aggregate": "operating_term",
        "label": "预付款已退还旅客",
        "req": {"prepayment_id": {"type": "string"}, "amount_cents": {"type": "integer", "min": 0}},
    },
    "OPERATOR_EXITED": {
        "aggregate": "operating_term",
        "label": "运营商提出退出，触发交割清单",
        "req": {"requested_at": {"type": "string"}, "reason": {"type": "string"}},
    },
    # —— 跨村贡献交换边界 ——
    "SERVICE_RECORDED": {
        "aggregate": "community_contribution",
        "label": "登记跨村贡献交换（须附证据）",
        "req": {
            "contribution_kind": {"enum": ["cross_village_referral", "volunteer_support",
                                           "consignment_service", "other"]},
            "from_party": {"type": "string"},
            "from_village": {"type": "string"},
            "to_village": {"type": "string"},
            "quantity": {"type": "integer", "min": 1},
            "unit": {"type": "string"},
            "evidence_refs": {"type": "array", "items": {"type": "string"}, "min_items": 1},
            "period": {"type": "string"},
        },
    },
    # —— 收益分配边界 ——
    "BENEFIT_ALLOCATED": {
        "aggregate": "benefit_distribution",
        "label": "形成一期可审计分配结果",
        "req": {
            "period": {"type": "string"},
            "lines": {
                "type": "array",
                "min_items": 1,
                "items": {
                    "type": "object",
                },
            },
        },
    },
    "BENEFIT_SETTLED": {
        "aggregate": "benefit_distribution",
        "label": "分配结果已兑付",
        "req": {"allocation_aggregate_id": {"type": "string"}, "evidence_ref": {"type": "string"}},
    },
    # —— 季节性摊位 ——
    "STALL_PERMIT_ISSUED": {
        "aggregate": "seasonal_stall",
        "label": "发放季节性摊位许可",
        "req": {
            "site_asset_id": {"type": "string"},
            "party_id": {"type": "string"},
            "village": {"type": "string"},
            "season": {"type": "string"},
            "starts_at": {"type": "string"},
            "ends_at": {"type": "string"},
        },
    },
    "STALL_CLOSED": {
        "aggregate": "seasonal_stall",
        "label": "摊位撤场、点位清空并核验",
        "req": {"site_asset_id": {"type": "string"}, "closed_at": {"type": "string"}},
        "opt": {"note": {"type": "string"}},
    },
    # —— 农产品寄售 ——
    "CONSIGNMENT_DELIVERED": {
        "aggregate": "consignment",
        "label": "农户向运营商交付寄售批次",
        "req": {
            "term_id": {"type": "string"},
            "supplier_party_id": {"type": "string"},
            "seller_party_id": {"type": "string"},
            "village": {"type": "string"},
            "items_summary": {"type": "string"},
            "quantity": {"type": "integer", "min": 1},
            "unit": {"type": "string"},
            "unit_price_cents": {"type": "integer", "min": 0},
            "unsold_policy": {"enum": ["return", "discount_purchase"]},
            "delivered_at": {"type": "string"},
        },
    },
    "CONSIGNMENT_SOLD": {
        "aggregate": "consignment",
        "label": "寄售商品售出（货款归农户，佣金归销售方）",
        "req": {
            "quantity": {"type": "integer", "min": 1},
            "gross_cents": {"type": "integer", "min": 0},
            "commission_cents": {"type": "integer", "min": 0},
            "order_ref": {"type": "string"},
            "sold_at": {"type": "string"},
        },
        "opt": {"point_of_sale_asset_id": {"type": "string"}},
    },
    "CONSIGNMENT_RETURNED": {
        "aggregate": "consignment",
        "label": "未售出商品退回实际供货农户",
        "req": {"quantity": {"type": "integer", "min": 1},
                "reason": {"type": "string"}, "returned_at": {"type": "string"}},
    },
    "CONSIGNMENT_BAD_DEBT": {
        "aggregate": "consignment",
        "label": "寄售坏账核销，责任落到批次实际参与方",
        "req": {
            "amount_cents": {"type": "integer", "min": 1},
            "responsible_party_id": {"type": "string"},
            "basis": {"enum": ["seller_price_risk", "seller_credit", "supplier_agreed_risk"]},
            "evidence_ref": {"type": "string"},
        },
    },
    "CONSIGNMENT_SETTLED": {
        "aggregate": "consignment",
        "label": "寄售批次与农户结清",
        "req": {"paid_cents": {"type": "integer", "min": 0},
                "settled_at": {"type": "string"}},
    },
    # —— 民宿导流 ——
    "REFERRAL_RECORDED": {
        "aggregate": "referral",
        "label": "登记一条民宿导流线索",
        "req": {
            "source_party_id": {"type": "string"},
            "source_village": {"type": "string"},
            "target_party_id": {"type": "string"},
            "target_village": {"type": "string"},
            "node_asset_id": {"type": "string"},
            "channel": {"type": "string"},
            "guest_ref": {"type": "string"},
            "evidence_kind": {"enum": ["voucher", "qr_code", "booking_code", "signed_slip"]},
            "evidence_ref": {"type": "string"},
            "recorded_at": {"type": "string"},
        },
    },
    "REFERRAL_VERIFIED": {
        "aggregate": "referral",
        "label": "导流经入住核销，证据成立",
        "req": {"referral_id": {"type": "string"}, "booking_id": {"type": "string"},
                "checked_in_at": {"type": "string"}, "payout_cents": {"type": "integer", "min": 0}},
    },
    "REFERRAL_REJECTED": {
        "aggregate": "referral",
        "label": "导流证据被驳回（重复、伪造或未入住）",
        "req": {"referral_id": {"type": "string"}, "reason": {"type": "string"}},
    },
    # —— 志愿班次 ——
    "SHIFT_SCHEDULED": {
        "aggregate": "volunteer_shift",
        "label": "排定志愿班次",
        "req": {"shift_id": {"type": "string"}, "volunteer_party_id": {"type": "string"},
                "node_asset_id": {"type": "string"}, "starts_at": {"type": "string"},
                "ends_at": {"type": "string"}, "duty": {"type": "string"}},
    },
    "SHIFT_FULFILLED": {
        "aggregate": "volunteer_shift",
        "label": "志愿班次完成并签到",
        "req": {"shift_id": {"type": "string"}, "evidence_ref": {"type": "string"},
                "served_minutes": {"type": "integer", "min": 1}},
    },
    "SHIFT_CANCELLED": {
        "aggregate": "volunteer_shift",
        "label": "志愿班次取消",
        "req": {"shift_id": {"type": "string"}, "reason": {"type": "string"}},
    },
    # —— 就业承诺 ——
    "PLEDGE_MADE": {
        "aggregate": "employment_pledge",
        "label": "运营商在许可中作出就业承诺",
        "req": {"term_id": {"type": "string"}, "operator_party_id": {"type": "string"},
                "positions_total": {"type": "integer", "min": 1},
                "local_positions_min": {"type": "integer", "min": 0},
                "wage_min_cents": {"type": "integer", "min": 0}, "season": {"type": "string"}},
    },
    "PLEDGE_FULFILLED": {
        "aggregate": "employment_pledge",
        "label": "就业承诺兑现并提交工资凭证",
        "req": {"term_id": {"type": "string"}, "hires_total": {"type": "integer", "min": 0},
                "hires_local": {"type": "integer", "min": 0},
                "payroll_evidence_refs": {"type": "array", "items": {"type": "string"}, "min_items": 1},
                "period": {"type": "string"}},
    },
    "PLEDGE_SHORTFALL": {
        "aggregate": "employment_pledge",
        "label": "就业承诺未兑现",
        "req": {"term_id": {"type": "string"}, "positions_gap": {"type": "integer", "min": 0},
                "local_gap": {"type": "integer", "min": 0}, "note": {"type": "string"}},
    },
    # —— 生态容量 ——
    "CAPACITY_DEFINED": {
        "aggregate": "eco_capacity",
        "label": "定义节点日生态容量",
        "req": {"node_asset_id": {"type": "string"},
                "metric": {"enum": ["persons", "vehicles"]},
                "daily_cap": {"type": "integer", "min": 1}},
    },
    "LOAD_REPORTED": {
        "aggregate": "eco_capacity",
        "label": "上报节点当日实际承载量",
        "req": {"node_asset_id": {"type": "string"}, "date": {"type": "string"},
                "load": {"type": "integer", "min": 0}},
    },
    "OVERLOAD_DECLARED": {
        "aggregate": "eco_capacity",
        "label": "宣布节点超载",
        "req": {"node_asset_id": {"type": "string"}, "date": {"type": "string"},
                "load": {"type": "integer", "min": 1}},
    },
    "OVERLOAD_CLEARED": {
        "aggregate": "eco_capacity",
        "label": "节点超载解除",
        "req": {"node_asset_id": {"type": "string"}, "date": {"type": "string"}},
    },
    # —— 业务暂停与旅客承诺 ——
    "SUSPENSION_ISSUED": {
        "aggregate": "suspension",
        "label": "因暴雨、检修或超载精准暂停部分业务",
        "req": {
            "reason": {"enum": ["storm", "maintenance", "overload"]},
            "scope_asset_ids": {"type": "array", "items": {"type": "string"}, "min_items": 1},
            "service_kinds": {
                "type": "array",
                "min_items": 1,
                "items": {"enum": ["new_booking", "stall_sale", "traffic_entry",
                                   "consignment_sale", "new_referral"]},
            },
            "starts_at": {"type": "string"},
        },
        "opt": {
            "expected_end": {"type": "string"},
            "scope_term_ids": {"type": "array", "items": {"type": "string"}},
            "protected_commitments": {"type": "array", "items": {"type": "object"}},
            "note": {"type": "string"},
        },
    },
    "SUSPENSION_LIFTED": {
        "aggregate": "suspension",
        "label": "暂停解除",
        "req": {"ended_at": {"type": "string"}},
    },
    "COMMITMENT_HONORED": {
        "aggregate": "suspension",
        "label": "暂停期间对已入住/已付款旅客承诺已照护兑现",
        "req": {"suspension_id": {"type": "string"}, "commitment_id": {"type": "string"},
                "note": {"type": "string"}, "honored_at": {"type": "string"}},
    },
    # —— 维修工单 ——
    "REPAIR_OPENED": {
        "aggregate": "repair_order",
        "label": "公共设施故障开单",
        "req": {"asset_id": {"type": "string"}, "fault": {"type": "string"},
                "reported_by": {"type": "string"}, "opened_at": {"type": "string"}},
    },
    "REPAIR_CLAIMED": {
        "aggregate": "repair_order",
        "label": "维修责任被认领",
        "req": {"repair_order_id": {"type": "string"}, "claimed_by": {"type": "string"},
                "basis": {"type": "string"}},
    },
    "REPAIR_COMPLETED": {
        "aggregate": "repair_order",
        "label": "维修完工并记录负担分摊",
        "req": {"cost_cents": {"type": "integer", "min": 0},
                "borne_by": {"type": "array", "items": {"type": "object"}, "min_items": 1},
                "evidence_ref": {"type": "string"}, "completed_at": {"type": "string"}},
    },
    # —— 季度公示 ——
    "NOTICE_PUBLISHED": {
        "aggregate": "public_notice",
        "label": "发布季度公示（四板块分开呈现）",
        "req": {"quarter": {"type": "string"}, "scope_village": {"type": "string"},
                "sections": {"type": "object"}, "source_event_ids": {"type": "array",
                                                                   "items": {"type": "string"}}},
    },
    # —— 退出交割 ——
    "HANDOVER_LIST_GENERATED": {
        "aggregate": "handover",
        "label": "退出时自动生成交割清单",
        "req": {"term_id": {"type": "string"}, "operator_party_id": {"type": "string"},
                "generated_at": {"type": "string"}, "checklist": {"type": "object"}},
    },
    "HANDOVER_BLOCKER_RESOLVED": {
        "aggregate": "handover",
        "label": "交割阻断项已清偿并留证",
        "req": {"handover_id": {"type": "string"}, "blocker_id": {"type": "string"},
                "resolution_evidence": {"type": "string"}},
    },
    "HANDOVER_COMPLETED": {
        "aggregate": "handover",
        "label": "交割完成，资产、款项与数据责任移交完毕",
        "req": {"handover_id": {"type": "string"}, "receiving_party_id": {"type": "string"},
                "data_acknowledgement_ref": {"type": "string"}, "completed_at": {"type": "string"}},
    },
}


def event_aggregate(event_type: str) -> str | None:
    entry = EVENTS.get(event_type)
    return entry["aggregate"] if entry else None  # type: ignore[return-value]
