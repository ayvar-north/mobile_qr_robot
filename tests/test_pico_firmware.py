"""Run with: python -m unittest discover -s tests -p test_pico_firmware.py"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr/pico/firmware"))

from controller import Controller
from motion import Motion
from motor_driver import MotorDriver
from protocol import Reader, ZERO_SESSION, crc16, decode, encode


class FakePwm:
    def __init__(self):
        self.values = {}
        self.fail_on = None

    def set_percent(self, channel, percent):
        if channel == self.fail_on:
            raise OSError("I2C failure")
        self.values[channel] = percent


class FakeDriver:
    def __init__(self):
        self.values = (0, 0)
        self.stops = 0

    def set_tracks(self, left, right):
        self.values = left, right

    def stop_all(self):
        self.values = 0, 0
        self.stops += 1


def diff(a, b):
    return (a - b + 5000) % 10000 - 5000


class FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.driver = FakeDriver()
        self.motion = Motion(self.driver, diff, 10, 100)
        self.control = Controller(self.motion, diff, 1)
        self.nonce = "a" * 32
        self.control.handle(("HELLO", ZERO_SESSION, 0, self.nonce), 0)
        self.session = self.control.session

    def send(self, kind, seq, payload="-", now=0):
        return self.control.handle((kind, self.session, seq, payload), now)

    def test_crc_and_fragmented_frames(self):
        self.assertEqual(crc16(b"123456789"), 0x29b1)
        frame = encode("MOVE", self.session, 2, "10,-10,250")
        reader = Reader(diff)
        self.assertEqual(reader.feed(frame[:9], 0), [])
        self.assertEqual(reader.feed(frame[9:] + frame, 1),
                         [decode(frame), decode(frame)])
        bad = frame[:-5] + b"0000\n"
        self.assertEqual(reader.feed(bad, 2), [])

    def test_requires_arm_and_stops_on_deadline(self):
        self.assertIn(b"NOT_ARMED", self.send("MOVE", 1, "10,10,100")[0])
        self.send("ARM", 2)
        self.send("MOVE", 3, "10,10,100")
        self.control.tick(50)
        self.assertNotEqual(self.driver.values, (0, 0))
        done = self.control.tick(100)
        self.assertEqual(self.driver.values, (0, 0))
        self.assertIn(b"completed,100", done[0])
        self.assertEqual(self.control.state, "ARMED_IDLE")

    def test_repeated_move_does_not_extend_deadline(self):
        self.send("ARM", 1)
        first = self.send("MOVE", 2, "10,10,100")
        self.assertEqual(first, self.send("MOVE", 2, "10,10,100", 80))
        self.assertIn(b"ID_CONFLICT", self.send("MOVE", 2, "11,10,100")[0])
        self.control.tick(100)
        self.assertIn(b"completed", self.send("MOVE", 2, "10,10,100", 110)[0])
        self.assertEqual(self.driver.values, (0, 0))

    def test_heartbeat_timeout_revokes_session(self):
        self.send("ARM", 1)
        self.send("MOVE", 2, "10,10,1000")
        self.control.tick(250)
        self.send("HEARTBEAT", 3, now=250)
        self.send("HEARTBEAT", 3, now=490)  # Repeat cannot renew lease.
        result = self.control.tick(750)
        self.assertIn(b"link_timeout", result[0])
        self.assertEqual(self.driver.values, (0, 0))
        self.assertIn(b"BAD_SESSION", self.send("ARM", 4, now=751)[0])

    def test_stop_revokes_old_arm(self):
        self.send("ARM", 1)
        self.send("MOVE", 2, "10,10,1000")
        self.send("STOP", 3, "user", 5)
        self.assertEqual(self.driver.values, (0, 0))
        self.assertIn(b"BAD_SESSION", self.send("ARM", 4, now=6)[0])

    def test_motor_mapping_and_failed_second_side(self):
        pwm = FakePwm()
        motor = MotorDriver(pwm, "MA", "MC", False, True)
        motor.set_tracks(20, 30)
        self.assertEqual((pwm.values[0], pwm.values[1], pwm.values[2]), (20, 100, 0))
        self.assertEqual((pwm.values[6], pwm.values[7], pwm.values[8]), (30, 0, 100))
        pwm.fail_on = 6
        with self.assertRaises(OSError):
            motor.set_tracks(20, 30)
        self.assertEqual(pwm.values[0], 0)


if __name__ == "__main__":
    unittest.main()
