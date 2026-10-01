"""Регрессии, найденные при сверке руководства с реализацией."""

import asyncio
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi"))
sys.path.insert(0, str(ROOT / "scr/pico/firmware"))

from robot.config import load
from robot.controller import Controller
from robot.execution import PlanExecutor
from robot.qr.gate import CardGate
from robot.supervisor import Supervisor
from robot.telemetry import Telemetry
from robot.transport.serial_client import FakePicoTransport
from robot.types import ControlRequest, DetectionBatch, MotionPlan, MotionStep
from controller import Controller as PicoController
from protocol import ZERO_SESSION


class ConsistencyTests(unittest.IsolatedAsyncioTestCase):
    def make_controller(self, link=None):
        return Controller(load(ROOT / "config/pi.dry-run.json"),
                          link or FakePicoTransport(), Supervisor(), Telemetry())

    async def test_late_ready_cannot_undo_stop(self):
        link = FakePicoTransport()
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed_handshake():
            entered.set()
            await release.wait()

        link.handshake = delayed_handshake
        control = self.make_controller(link)
        startup = asyncio.create_task(control.initialize())
        await entered.wait()
        await control.handle(ControlRequest("stop", "test", "stop", {}, 0))
        await control.stop_task
        release.set()
        await startup
        self.assertEqual(control.state, "STOPPED")
        self.assertFalse(control.armed)

    async def test_confirmed_stop_preserves_fault(self):
        control = self.make_controller()
        await control.initialize()
        control.fault("камера отключена")
        await control.stop_task
        self.assertEqual(control.state, "FAULT")
        self.assertEqual(control.stop_reason, "камера отключена")
        self.assertTrue(control.outputs_confirmed_off)

    async def test_qr_arming_discards_clean_period_before_arm(self):
        control = self.make_controller()
        await control.initialize()
        control.camera_healthy = True
        control.supervisor.mark_vision(time.monotonic_ns())
        control.gate.need_clean = False
        await control.handle(ControlRequest("start", "test", "start", {"mode": "qr"}, 0, 0))
        # Имитируем чистое поле, полученное пока ожидалось разрешение Pico.
        control.gate.need_clean = False
        await control.arm_task
        self.assertEqual(control.state, "READY")
        self.assertTrue(control.gate.need_clean)
        self.assertGreater(control.gate.start_at_ns, 0)

    async def test_late_last_done_is_not_success(self):
        link = FakePicoTransport()
        results = []
        executor = PlanExecutor(link, results.append)
        # Часы исполнителя независимы от часов asyncio: воспроизводим поздний DONE.
        clock = [0.0]

        async def delayed_move(*args):
            clock[0] = 2.0

        link.move = delayed_move
        plan = MotionPlan("plan", "test", "card", (MotionStep(10, 10, 100),), 100)
        with patch("robot.execution.time", type("Clock", (), {"monotonic": staticmethod(lambda: clock[0])})):
            executor.submit(plan)
            await executor.task
        self.assertEqual(results, ["маршрут превысил срок"])


class GateAndPicoTests(unittest.TestCase):
    def test_pre_arm_frames_cannot_unlock_gate(self):
        gate = CardGate(30, 2000)
        gate.reset_for_start(1_000_000_000)
        for index in range(5):
            stamp = index * 200_000_000
            gate.observe(DetectionBatch(index, stamp, stamp, ()), False, stamp)
        self.assertTrue(gate.need_clean)

    def test_hello_cannot_report_ready_after_failed_stop(self):
        class FailedMotion:
            def cancel(self):
                raise OSError("ошибка I2C")

        control = PicoController(FailedMotion(), lambda a, b: a - b, 1)
        replies = control.handle(("HELLO", ZERO_SESSION, 0, "a" * 32), 0)
        self.assertEqual(control.state, "FAULT")
        self.assertFalse(any(b"|READY|" in reply for reply in replies))
        self.assertTrue(any(b"DRIVER_FAULT" in reply for reply in replies))
