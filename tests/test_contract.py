import json
import unittest
from pathlib import Path

from src.catalog import AGGREGATES, EVENTS
from src.validator import validate_event

ROOT = Path(__file__).parents[1]


class ContractTest(unittest.TestCase):
    def test_sample_matches_envelope(self) -> None:
        sample = json.loads((ROOT / "data" / "sample.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_event(sample), [])

    def test_season_sample_matches_envelope(self) -> None:
        events = json.loads(
            (ROOT / "data" / "sample_season.json").read_text(encoding="utf-8"))
        for event in events:
            self.assertEqual(validate_event(event), [],
                             f"{event['event_id']} 载荷不合法")

    def test_boundary_aggregates_stay_stable(self) -> None:
        # 四个跨村交换边界是对外公共标识，只增不删、不改名
        for name in ("shared_asset", "operating_term",
                     "community_contribution", "benefit_distribution"):
            self.assertIn(name, AGGREGATES)
            self.assertTrue(AGGREGATES[name]["boundary"])

    def test_event_to_aggregate_pairing(self) -> None:
        # 既有五个事件标识保留在原边界聚合上
        self.assertEqual(EVENTS["ASSET_REGISTERED"]["aggregate"], "shared_asset")
        self.assertEqual(EVENTS["TERM_GRANTED"]["aggregate"], "operating_term")
        self.assertEqual(EVENTS["SERVICE_RECORDED"]["aggregate"],
                         "community_contribution")
        self.assertEqual(EVENTS["BENEFIT_ALLOCATED"]["aggregate"],
                         "benefit_distribution")
        self.assertEqual(EVENTS["OPERATOR_EXITED"]["aggregate"], "operating_term")

    def test_unknown_event_rejected(self) -> None:
        record = {
            "event_id": "evt-bad-0001", "event_type": "NO_SUCH_EVENT",
            "aggregate_type": "shared_asset", "aggregate_id": "a1",
            "occurred_at": "2026-09-20T12:00:00+08:00", "version": 1,
            "summary": "未知事件", "payload": {},
        }
        self.assertTrue(any("未知事件类型" in m for m in validate_event(record)))

    def test_event_aggregate_mismatch_rejected(self) -> None:
        record = {
            "event_id": "evt-bad-0002", "event_type": "TERM_GRANTED",
            "aggregate_type": "shared_asset", "aggregate_id": "t1",
            "occurred_at": "2026-04-01T00:00:00+08:00", "version": 1,
            "summary": "聚合配对错误", "payload": {},
        }
        self.assertTrue(any("aggregate_type 必须是" in m
                            for m in validate_event(record)))


if __name__ == "__main__":
    unittest.main()
