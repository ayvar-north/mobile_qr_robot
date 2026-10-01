"""Контрактные проверки Pi без камеры и физических моторов."""

import asyncio
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from robot.config import load
from robot.controller import Controller
from robot.planning import from_card
from robot.qr.gate import CardGate
from robot.qr.schema import QrRejected, parse
from robot.remote.local_api import parse_request
from robot.supervisor import Supervisor
from robot.telemetry import Telemetry
from robot.transport.codec import Message, Reader, crc16, decode, encode
from robot.transport.serial_client import FakePicoTransport
from robot.types import ControlRequest, DetectionBatch


CONFIG = Path(__file__).resolve().parents[1] / "config/pi.dry-run.json"


def card(card_id="one", action="forward", duration=100):
    return json.dumps({"schema": "qr-robot", "v": 1, "card_id": card_id,
                       "action": action, "pwm_pct": 20, "duration_ms": duration})


class SchemaAndPlan(unittest.TestCase):
    def test_rejects_bad_final_route_step_before_plan(self):
        raw = json.dumps({"schema": "qr-robot", "v": 1, "card_id": "route",
                          "action": "route", "steps": [
                              {"action": "forward", "pwm_pct": 20, "duration_ms": 100},
                              {"action": "backward", "pwm_pct": True, "duration_ms": 100}]})
        with self.assertRaises(QrRejected):
            parse(raw)

    def test_strict_schema_and_plan_signs(self):
        config = load(CONFIG)
        parsed = parse(card(action="turn_left"))
        plan = from_card(parsed, config, 30, 2000)
        self.assertEqual((plan.steps[0].left_pwm_pct, plan.steps[0].right_pwm_pct), (-20, 20))
        with self.assertRaises(QrRejected):
            parse(card().replace('"v": 1', '"v": true'))
        with self.assertRaises(QrRejected):
            parse('{"schema":"qr-robot","schema":"qr-robot","v":1,"card_id":"a","action":"stop"}')

    def test_gate_requires_clean_start_and_reexposure(self):
        gate = CardGate(30, 2000)
        raw = card()
        base = 1_000_000_000
        gate.reset_for_start()
        self.assertIsNone(gate.observe(DetectionBatch(1, base, base, (raw,)), False, base))
        for frame, offset in enumerate((100, 300, 500, 700, 900), start=2):
            stamp = base + offset * 1_000_000
            gate.observe(DetectionBatch(frame, stamp, stamp, ()), False, stamp)
        for frame, offset in ((7, 1100), (8, 1300)):
            stamp = base + offset * 1_000_000
            self.assertIsNone(gate.observe(DetectionBatch(frame, stamp, stamp, (raw,)), False, stamp))
        stamp = base + 1_500_000_000
        event = gate.observe(DetectionBatch(9, stamp, stamp, (raw,)), False, stamp)
        self.assertEqual(event.kind, "card")
        stamp = base + 1_600_000_000
        self.assertIsNone(gate.observe(DetectionBatch(10, stamp, stamp, (raw,)), False, stamp))



class Protocol(unittest.TestCase):
    def test_vectors_and_reader(self):
        self.assertEqual(crc16(b"123456789"), 0x29B1)
        session = "a" * 32 + "0000000100000001"
        vectors = (("HELLO", "0" * 48, 0, "a" * 32, "C478"),
                   ("READY", session, 0, "DISARMED,30,2000,500", "9B73"),
                   ("ARM", session, 1, "-", "2804"),
                   ("MOVE", session, 2, "10,-10,250", "29F0"),
                   ("ACK", session, 2, "MOVE", "FA57"),
                   ("DONE", session, 2, "completed,250", "CC9E"),
                   ("STOP", session, 3, "user", "A127"),
                   ("STATE", session, 4, "DISARMED,0,0,0,0,none", "FB17"))
        reader = Reader()
        for kind, sid, seq, payload, check in vectors:
            frame = encode(Message(kind, sid, seq, payload))
            self.assertTrue(frame.endswith(("|" + check + "\n").encode()))
            self.assertEqual(decode(frame), Message(kind, sid, seq, payload))
            self.assertEqual(reader.feed(frame[:5], 0), [])
            self.assertEqual(reader.feed(frame[5:], 1), [Message(kind, sid, seq, payload)])

    def test_api_rejects_duplicate_and_bool(self):
        with self.assertRaises(ValueError):
            parse_request(b'{"api_v":1,"api_v":1,"request_id":"a","op":"stop","params":{}}\n')
        with self.assertRaises(ValueError):
            parse_request(b'{"api_v":1,"request_id":"a","op":"move","params":{"action":"forward","pwm_pct":true,"duration_ms":100},"expected_revision":0}\n')


class ControllerFlow(unittest.IsolatedAsyncioTestCase):
    async def test_manual_stop_and_stale_start(self):
        config = load(CONFIG)
        link = FakePicoTransport()
        control = Controller(config, link, Supervisor(), Telemetry())
        await control.initialize()
        self.assertEqual(control.state, "WAIT_START")
        start = ControlRequest("start1", "test", "start", {"mode": "manual"}, 0, 0)
        self.assertEqual((await control.handle(start))["code"], "ARMING")
        await asyncio.sleep(0)
        self.assertEqual(control.state, "READY")
        move = ControlRequest("move1", "test", "move", {"action": "forward",
                              "pwm_pct": 20, "duration_ms": 100}, 0, 0)
        self.assertTrue((await control.handle(move))["accepted"])
        stop = ControlRequest("stop1", "test", "stop", {}, 0)
        self.assertEqual((await control.handle(stop))["code"], "STOPPING")
        await control.stop_task
        self.assertEqual(control.state, "STOPPED")
        self.assertTrue(control.outputs_confirmed_off)
        self.assertEqual((await control.handle(start))["code"], "ARMING")
        stale = ControlRequest("start2", "test", "start", {"mode": "manual"}, 0, 0)
        self.assertEqual((await control.handle(stale))["code"], "STALE_REVISION")


if __name__ == "__main__":
    unittest.main()
