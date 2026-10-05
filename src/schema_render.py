"""从事件目录渲染 ``contracts/domain.schema.json``。

目录是唯一事实来源；渲染结果只是便于外部系统按 JSON Schema 联调的派生物。
运行：``python3 -m src.schema_render``。
"""

import json
from pathlib import Path

from src.catalog import AGGREGATES, EVENTS

_BOUNDARY_DOC = {
    "shared_asset": "跨村交换边界：公共资产与道路节点",
    "operating_term": "跨村交换边界：经营许可与期限",
    "community_contribution": "跨村交换边界：跨村贡献交换（须附证据）",
    "benefit_distribution": "跨村交换边界：收益分配结果",
}


def _json_type(spec: dict) -> str:
    return {"string": "string", "integer": "integer",
            "boolean": "boolean", "array": "array",
            "object": "object"}[spec.get("type", "string")]


def render_field(spec: dict) -> dict:
    node: dict = {"type": _json_type(spec)}
    if "enum" in spec:
        node["enum"] = list(spec["enum"])
    if "min" in spec:
        node["minimum"] = spec["min"]
    if spec.get("type") == "array":
        node["items"] = render_field(spec.get("items", {})) if spec.get("items") else {}
        if "min_items" in spec:
            node["minItems"] = spec["min_items"]
    return node


def render_payload_schema(event_type: str) -> dict:
    spec = EVENTS[event_type]
    properties = {name: render_field(field)
                  for group in ("req", "opt")
                  for name, field in spec.get(group, {}).items()}
    return {
        "type": "object",
        "required": list(spec.get("req", {}).keys()),
        "properties": properties,
        "additionalProperties": True,
    }


def render_schema() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "百里画廊沿线共益运营领域事件",
        "description": (
            "用于跨村、跨机构交换事实记录的公共信封。事件由 event_id 唯一标识，"
            "aggregate_id 指向业务对象，version 从 1 开始递增，occurred_at 保留真实发生时间；"
            "来源系统重试时必须沿用原事件标识。"
        ),
        "type": "object",
        "required": ["event_id", "event_type", "aggregate_type", "aggregate_id",
                     "occurred_at", "version", "summary", "payload"],
        "properties": {
            "event_id": {"type": "string", "minLength": 8, "description": "事件唯一标识"},
            "event_type": {
                "type": "string",
                "enum": list(EVENTS.keys()),
                "description": "本领域事件类型（见 src/catalog.py 事件目录）",
            },
            "aggregate_type": {
                "type": "string",
                "enum": list(AGGREGATES.keys()),
                "description": "业务对象类型；前四项为跨村交换边界："
                               + "；".join(_BOUNDARY_DOC.values()),
            },
            "aggregate_id": {"type": "string", "minLength": 1, "description": "业务对象标识"},
            "occurred_at": {"type": "string", "format": "date-time", "description": "事实发生时间"},
            "version": {"type": "integer", "minimum": 1, "description": "对象版本"},
            "summary": {"type": "string", "minLength": 2, "description": "中文事实摘要"},
            "payload": {"type": "object", "description": "事件业务字段，结构随 event_type 而定"},
        },
        "$defs": {
            f"payload_{event_type}": render_payload_schema(event_type)
            for event_type in EVENTS
        },
        "additionalProperties": True,
    }


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "contracts" / "domain.schema.json"
    target.write_text(
        json.dumps(render_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已渲染 {target}（{len(EVENTS)} 个事件类型 / {len(AGGREGATES)} 类业务对象）")


if __name__ == "__main__":
    main()
