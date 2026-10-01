"""Аппаратный режим закрыт, пока паспорт подключения не подтверждён."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi"))

from robot.config import load


class HardwareConfig(unittest.TestCase):
    def test_unset_hardware_cannot_start(self):
        with self.assertRaises(ValueError):
            load(ROOT / "config/pi.hardware.example.json")


if __name__ == "__main__":
    unittest.main()
