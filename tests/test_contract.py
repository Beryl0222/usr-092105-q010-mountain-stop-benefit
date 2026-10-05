import json
import unittest
from pathlib import Path

from src.events import validate_domain_record
from src.validator import validate_event


class ContractTest(unittest.TestCase):
    def test_sample_matches_envelope(self) -> None:
        sample = json.loads(
            (Path(__file__).parents[1] / "data" / "sample.json").read_text(encoding="utf-8")
        )
        self.assertEqual(validate_event(sample), [])
        self.assertEqual(validate_domain_record(sample), [])


if __name__ == "__main__":
    unittest.main()
