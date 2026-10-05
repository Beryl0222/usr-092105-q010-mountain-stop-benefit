"""事件类型与聚合的绑定关系及 payload 必备字段。

跨村交换边界只固定信封公共字段（见 contracts/domain.schema.json）；
本模块把每个事件类型落到唯一聚合上，并声明写入前必须带齐的
payload 字段，接入方在本地即可发现缺漏，不必等到年底对账。
"""

AGGREGATE_TYPES = (
    "shared_asset",
    "operating_term",
    "community_contribution",
    "benefit_distribution",
)

# 事件类型 -> (所属聚合, payload 必备字段)
EVENT_BINDING = {
    # shared_asset：道路节点、公共设施、集体院落、季节摊位，
    # 以及附着其上的生态容量、设备、维修工单与精准暂停。
    "ASSET_REGISTERED": ("shared_asset", ("kind", "village", "label")),
    "CAPACITY_DECLARED": ("shared_asset", ("metric", "limit")),
    "EQUIPMENT_INSTALLED": ("shared_asset", ("equipment_id", "owner", "label")),
    "EQUIPMENT_REMOVED": ("shared_asset", ("equipment_id", "owner", "destination")),
    "WORK_ORDER_OPENED": ("shared_asset", ("work_order_id", "issue", "responsible")),
    "WORK_ORDER_CLOSED": ("shared_asset", ("work_order_id", "cost", "shares")),
    "SERVICE_SUSPENDED": ("shared_asset", ("suspension_id", "reason", "protected_commitments")),
    "SERVICE_RESUMED": ("shared_asset", ("suspension_id",)),
    # operating_term：经营许可的授予、续期、到期、腾退与退出交割。
    "TERM_GRANTED": ("operating_term", ("asset_id", "operator", "scope", "start", "end")),
    "TERM_RENEWED": ("operating_term", ("new_end",)),
    "TERM_EXPIRED": ("operating_term", ()),
    "TERM_VACATED": ("operating_term", ()),
    "EXIT_REQUESTED": ("operating_term", ("operator",)),
    "EXIT_ITEM_CLEARED": ("operating_term", ("operator", "item_key", "evidence")),
    "OPERATOR_EXITED": ("operating_term", ("operator",)),
    # community_contribution：既有承诺、导流、志愿班次、就业兑现与寄售流水。
    "SERVICE_RECORDED": ("community_contribution", ("action", "asset_id")),
    "CONTRIBUTION_RECORDED": ("community_contribution", ("kind", "contributor", "evidence")),
    "CONSIGNMENT_STOCKED": (
        "community_contribution",
        ("asset_id", "operator", "producer", "item", "qty", "way"),
    ),
    "CONSIGNMENT_SOLD": (
        "community_contribution",
        ("asset_id", "operator", "producer", "item", "qty", "amount", "participants"),
    ),
    "CONSIGNMENT_RETURNED": ("community_contribution", ("qty", "amount", "reason", "participants")),
    "BAD_DEBT_RECORDED": ("community_contribution", ("amount", "reason", "participants")),
    # benefit_distribution：季度公示与分配结果。
    "DISCLOSURE_PUBLISHED": ("benefit_distribution", ("quarter", "sections")),
    "BENEFIT_ALLOCATED": ("benefit_distribution", ("quarter", "party", "amount")),
}


def aggregate_of(event_type: str) -> str:
    """返回事件类型所属聚合，未知类型直接拒绝。"""
    try:
        return EVENT_BINDING[event_type][0]
    except KeyError:
        raise ValueError(f"未知事件类型：{event_type}") from None


def validate_domain_record(record: dict) -> list[str]:
    """校验事件类型与聚合的绑定及 payload 必备字段，返回可展示的中文错误。"""
    event_type = record.get("event_type")
    binding = EVENT_BINDING.get(event_type)
    if binding is None:
        return [f"未知事件类型：{event_type}"]
    errors = []
    aggregate_type, required = binding
    if record.get("aggregate_type") != aggregate_type:
        errors.append(f"{event_type} 必须挂在聚合 {aggregate_type} 上")
    payload = record.get("payload")
    if not isinstance(payload, dict):
        errors.append("缺少 payload 业务内容")
    else:
        errors.extend(f"payload 缺少字段：{name}" for name in required if name not in payload)
    return errors
