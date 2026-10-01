"""Отмена маршрута должна опережать следующий обычный шаг."""

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi"))

from robot.config import load
from robot.controller import Controller
from robot.qr.gate import CardGate
from robot.supervisor import Supervisor
from robot.telemetry import Telemetry
from robot.transport.serial_client import FakePicoTransport
from robot.types import Action, ControlRequest, DetectionBatch
from robot.planning import build


class StopPriority(unittest.IsolatedAsyncioTestCase):
    async def test_stop_cancels_remaining_route(self):
        config = load(ROOT / "config/pi.dry-run.json")
        link = FakePicoTransport()
        controller = Controller(config, link, Supervisor(), Telemetry())
        await controller.initialize()
        await controller.handle(ControlRequest("start", "test", "start", {"mode": "manual"}, 0, 0))
        await asyncio.sleep(0)
        plan = build((Action("forward", 20, 100), Action("backward", 20, 100)),
                     "qr", "route", config, 30, 2000)
        controller.executor.submit(plan)
        controller.state = "EXECUTING"
        await asyncio.sleep(0.02)
        await controller.handle(ControlRequest("stop", "test", "stop", {}, 0))
        await controller.stop_task
        await asyncio.sleep(0.22)
        self.assertEqual(link.moves, [(20, 20, 100)])
        self.assertEqual(controller.state, "STOPPED")

    async def test_stop_qr_wins_over_motion_qr(self):
        gate = CardGate(30, 2000)
        now = time.monotonic_ns()
        motion = json.dumps({"schema": "qr-robot", "v": 1, "card_id": "move",
                             "action": "forward", "pwm_pct": 20, "duration_ms": 100})
        stop = json.dumps({"schema": "qr-robot", "v": 1, "card_id": "stop", "action": "stop"})
        event = gate.observe(DetectionBatch(1, now, now, (motion, stop)), False, now)
        self.assertEqual(event.kind, "stop")


if __name__ == "__main__":
    unittest.main()
