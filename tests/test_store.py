import unittest

from src.events import validate_domain_record
from src.store import EventStore


def make_event(**overrides):
    record = {
        "event_id": "evt-00000001",
        "event_type": "ASSET_REGISTERED",
        "aggregate_type": "shared_asset",
        "aggregate_id": "asset-1",
        "occurred_at": "2026-09-20T12:00:00+08:00",
        "version": 1,
        "summary": "登记资产",
        "payload": {"kind": "公共设施", "village": "梁家庄", "label": "村口公厕"},
    }
    record.update(overrides)
    return record


class StoreTest(unittest.TestCase):
    def test_retry_with_same_id_is_idempotent(self):
        """来源系统重试沿用原事件标识：同标识同内容幂等返回。"""
        store = EventStore()
        record = make_event()
        _, created = store.append(record)
        self.assertTrue(created)
        _, created = store.append(dict(record))
        self.assertFalse(created)
        self.assertEqual(len(store.all()), 1)

    def test_same_id_different_content_rejected(self):
        store = EventStore()
        store.append(make_event())
        with self.assertRaisesRegex(ValueError, "内容不一致"):
            store.append(make_event(summary="篡改后的摘要"))

    def test_version_must_be_continuous(self):
        store = EventStore()
        store.append(make_event())
        with self.assertRaisesRegex(ValueError, "版本不连续"):
            store.append(make_event(event_id="evt-00000002", version=3))

    def test_jsonl_roundtrip(self):
        store = EventStore()
        store.append(make_event())
        store.dump_jsonl("/tmp/events.jsonl")
        self.assertEqual(EventStore.load_jsonl("/tmp/events.jsonl").all(), store.all())


class BindingTest(unittest.TestCase):
    def test_event_type_must_match_aggregate(self):
        errors = validate_domain_record(make_event(aggregate_type="operating_term"))
        self.assertTrue(any("shared_asset" in e for e in errors))

    def test_payload_required_fields(self):
        errors = validate_domain_record(make_event(payload={"kind": "公共设施"}))
        self.assertIn("payload 缺少字段：village", errors)
        self.assertIn("payload 缺少字段：label", errors)

    def test_unknown_event_type_rejected(self):
        self.assertEqual(validate_domain_record(make_event(event_type="HACK")), ["未知事件类型：HACK"])


if __name__ == "__main__":
    unittest.main()
