"""追加式事件存储。

来源系统重试时必须沿用原事件标识：同一标识且内容一致的写入
幂等返回；内容不一致或版本不连续直接拒绝，保证账本可审计、可回放。
"""
import json
from pathlib import Path


class EventStore:
    def __init__(self):
        self._events = []
        self._by_id = {}
        self._heads = {}

    def append(self, record: dict):
        """追加事件，返回 (事件, 是否新写入)。重试同标识同内容时幂等返回。"""
        event_id = record["event_id"]
        existing = self._by_id.get(event_id)
        if existing is not None:
            if existing == record:
                return existing, False
            raise ValueError(f"事件标识 {event_id} 已存在且内容不一致")
        key = (record["aggregate_type"], record["aggregate_id"])
        expected = self._heads.get(key, 0) + 1
        if record["version"] != expected:
            raise ValueError(f"聚合 {key} 版本不连续：期望 {expected}，实际 {record['version']}")
        self._events.append(record)
        self._by_id[event_id] = record
        self._heads[key] = record["version"]
        return record, True

    def all(self) -> list[dict]:
        return list(self._events)

    def for_aggregate(self, aggregate_type: str, aggregate_id: str) -> list[dict]:
        return [
            e
            for e in self._events
            if e["aggregate_type"] == aggregate_type and e["aggregate_id"] == aggregate_id
        ]

    def dump_jsonl(self, path) -> None:
        """导出为 JSONL，供跨村交换与离线审计。"""
        Path(path).write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self._events),
            encoding="utf-8",
        )

    @classmethod
    def load_jsonl(cls, path) -> "EventStore":
        store = cls()
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                store.append(json.loads(line))
        return store
