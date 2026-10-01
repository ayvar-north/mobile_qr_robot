"""Граница предъявления QR при потере кадров и конфликте идентификаторов."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from robot.qr.gate import CardGate
from robot.types import DetectionBatch


def payload(card_id, pwm):
    return json.dumps({"schema": "qr-robot", "v": 1, "card_id": card_id,
                       "action": "forward", "pwm_pct": pwm, "duration_ms": 100})


class GateFaults(unittest.TestCase):
    def test_missing_frames_do_not_count_as_clean_interval(self):
        gate = CardGate(30, 2000)
        base = 1_000_000_000
        gate.reset_for_start()
        gate.observe(DetectionBatch(1, base, base, ()), False, base)
        later = base + 900_000_000
        gate.observe(DetectionBatch(2, later, later, ()), False, later)
        for frame, offset in ((3, 1000), (4, 1100), (5, 1200)):
            stamp = base + offset * 1_000_000
            self.assertIsNone(gate.observe(DetectionBatch(frame, stamp, stamp,
                (payload("one", 20),)), False, stamp))

    def test_same_id_different_content_is_conflict(self):
        gate = CardGate(30, 2000)
        now = 1_000_000_000
        result = gate.observe(DetectionBatch(1, now, now,
            (payload("same", 20), payload("same", 21))), False, now)
        self.assertEqual(result.kind, "id_conflict")


if __name__ == "__main__":
    unittest.main()
