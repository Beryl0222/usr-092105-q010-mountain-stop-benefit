"""校验领域事件信封与事件载荷。

信封约定（保持跨系统稳定）：
- ``event_id`` 唯一标识，来源系统重试沿用原标识；
- ``aggregate_id`` 指向业务对象，``version`` 从 1 起递增；
- ``occurred_at`` 为事实真实发生时间。

业务字段统一放在 ``payload`` 下，结构由 :mod:`src.catalog` 单一目录声明。
校验只返回可直接展示给接入方的中文错误。
"""

from datetime import datetime

from src.catalog import AGGREGATES, EVENTS, RULES

REQUIRED = ("event_id", "event_type", "aggregate_type", "aggregate_id",
            "occurred_at", "version", "summary")


def _check_field(name: str, spec: dict, value) -> list[str]:
    errors: list[str] = []
    kind = spec.get("type")
    if kind == "string" and not isinstance(value, str):
        errors.append(f"payload.{name} 必须是字符串")
    elif kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        errors.append(f"payload.{name} 必须是整数")
    elif kind == "boolean" and not isinstance(value, bool):
        errors.append(f"payload.{name} 必须是布尔值")
    elif kind == "array":
        if not isinstance(value, list):
            errors.append(f"payload.{name} 必须是数组")
        else:
            min_items = spec.get("min_items")
            if min_items is not None and len(value) < min_items:
                errors.append(f"payload.{name} 至少包含 {min_items} 项")
            item_spec = spec.get("items", {})
            for i, item in enumerate(value):
                errors += [f"payload.{name}[{i}]：{e}"
                           for e in _check_leaf(item_spec, item)]
    elif kind == "object" and not isinstance(value, dict):
        errors.append(f"payload.{name} 必须是对象")
    if "enum" in spec and value not in spec["enum"]:
        errors.append(f"payload.{name} 取值不合法：{value!r}，允许 {spec['enum']}")
    if kind == "integer" and isinstance(value, int) and not isinstance(value, bool):
        minimum = spec.get("min")
        if minimum is not None and value < minimum:
            errors.append(f"payload.{name} 不得小于 {minimum}")
    return errors


def _check_leaf(spec: dict, value) -> list[str]:
    """校验数组元素等没有字段名的叶子值。"""
    errors: list[str] = []
    kind = spec.get("type")
    if kind == "string" and not isinstance(value, str):
        errors.append("必须是字符串")
    elif kind == "object" and not isinstance(value, dict):
        errors.append("必须是对象")
    return errors


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def validate_event(record: dict) -> list[str]:
    """返回中文错误列表；为空表示通过。"""
    errors = [f"缺少字段：{name}" for name in REQUIRED if name not in record]
    if errors:
        return errors

    if not isinstance(record["event_id"], str) or len(record["event_id"]) < 8:
        errors.append("event_id 必须是不少于 8 个字符的字符串")
    if not isinstance(record["aggregate_id"], str) or not record["aggregate_id"]:
        errors.append("aggregate_id 必须是非空字符串")
    if not isinstance(record["summary"], str) or len(record["summary"]) < 2:
        errors.append("summary 必须是不少于 2 个字符的中文事实摘要")
    if not isinstance(record["version"], int) or isinstance(record["version"], bool) \
            or record["version"] < 1:
        errors.append("version 必须是正整数")
    if not isinstance(record["occurred_at"], str) or _parse_dt(record["occurred_at"]) is None:
        errors.append("occurred_at 必须是 ISO 8601 日期时间")

    event_type = record.get("event_type")
    spec = EVENTS.get(event_type)
    if spec is None:
        errors.append(f"未知事件类型：{event_type!r}")
        return errors

    expected_aggregate = spec["aggregate"]
    if record.get("aggregate_type") != expected_aggregate:
        errors.append(
            f"事件 {event_type} 的 aggregate_type 必须是 {expected_aggregate}，"
            f"不能是 {record.get('aggregate_type')!r}"
        )
    if record.get("aggregate_type") not in AGGREGATES:
        errors.append(f"未知业务对象类型：{record.get('aggregate_type')!r}")

    payload = record.get("payload", {})
    if not isinstance(payload, dict):
        errors.append("payload 必须是对象")
        return errors

    for name, field_spec in spec.get("req", {}).items():
        if name not in payload:
            errors.append(f"{event_type} 缺少必填字段 payload.{name}")
        else:
            errors += _check_field(name, field_spec, payload[name])
    for name, field_spec in spec.get("opt", {}).items():
        if name in payload:
            errors += _check_field(name, field_spec, payload[name])

    errors += _cross_field_rules(event_type, payload)
    return errors


def _cross_field_rules(event_type: str, payload: dict) -> list[str]:
    errors: list[str] = []
    if event_type == "TERM_GRANTED":
        start = _parse_dt(payload.get("starts_at", ""))
        end = _parse_dt(payload.get("ends_at", ""))
        if start and end:
            if end <= start:
                errors.append("ends_at 必须晚于 starts_at：许可不得倒签或零天授权")
            elif payload.get("seasonal") and \
                    (end - start).days > RULES["max_seasonal_term_days"]:
                errors.append(
                    f"季节性许可最长 {RULES['max_seasonal_term_days']} 天，"
                    "到期重新竞价或轮换，不得沉淀成永久占用"
                )
    return errors
