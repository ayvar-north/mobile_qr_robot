"""Проверки регистров PCA9685 и ручного опыта без подключённого Pico."""

import contextlib
import io
import runpy
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

FIRMWARE = Path(__file__).resolve().parents[1] / "scr/pico/firmware"
sys.path.insert(0, str(FIRMWARE))

from motor_driver import MotorDriver
from pca9685 import PCA9685


class RegisterI2C:
    """Модель I²C учитывает AI: без него адрес не растёт между байтами.

    Обычная заглушка writeto_mem пропустила бы исходную ошибку: обмен
    завершается успешно, хотя четыре байта не попадают в четыре регистра.
    """

    def __init__(self):
        self.registers = bytearray(256)
        self.registers[0] = 0x11  # Состояние после включения питания.
        self.registers[1] = 0x04
        self.addresses = [0x40, 0x70]
        self.writes = []
        self.ignore_register = None
        self.fail_motion_once = False

    def scan(self):
        return self.addresses

    def writeto_mem(self, address, register, data):
        if self.fail_motion_once and register == 0x06 and data[2]:
            self.fail_motion_once = False
            raise OSError("обрыв I²C во время импульса")
        self.writes.append((register, bytes(data)))
        for value in data:
            if register != self.ignore_register:
                self.registers[register] = value
            if self.registers[0] & 0x20:
                register += 1

    def readfrom_mem(self, address, register, length):
        increment = bool(self.registers[0] & 0x20)
        return bytes(self.registers[register + index if increment else register]
                     for index in range(length))

    def channel(self, channel):
        base = 0x06 + channel * 4
        return bytes(self.registers[base:base + 4])


class DriverRegisterTests(unittest.TestCase):
    def setUp(self):
        self.bus = RegisterI2C()
        self.output = io.StringIO()
        self.stdout = contextlib.redirect_stdout(self.output)
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def test_initialization_stops_old_outputs_before_waking_oscillator(self):
        # Состояние каналов от прошлой программы не обязано быть нулевым.
        self.bus.registers[0x06:0x36] = b"\xff" * 48
        PCA9685(self.bus, 0x40, 50)
        self.assertEqual(self.bus.registers[0] & 0x70, 0x20)
        self.assertEqual(self.bus.registers[0xFE], 121)
        for channel in range(12):
            self.assertEqual(self.bus.channel(channel), b"\x00\x00\x00\x10")
        wake_index = self.bus.writes.index((0x00, b"\x20"))
        for channel in range(12):
            off_index = self.bus.writes.index((0x06 + channel * 4, b"\x00\x00\x00\x10"))
            self.assertLess(off_index, wake_index)

    def test_pwm_and_direction_reach_separate_registers(self):
        pwm = PCA9685(self.bus, 0x40, 50)
        motor = MotorDriver(pwm, "MA", "MC", False, True)
        motor.set_tracks(20, 30)
        self.assertEqual(self.bus.channel(0), b"\x00\x00\x33\x03")
        self.assertEqual(self.bus.channel(1), b"\x00\x10\x00\x00")
        self.assertEqual(self.bus.channel(2), b"\x00\x00\x00\x10")
        self.assertEqual(self.bus.channel(6), b"\x00\x00\xcc\x04")
        self.assertEqual(self.bus.channel(7), b"\x00\x00\x00\x10")
        self.assertEqual(self.bus.channel(8), b"\x00\x10\x00\x00")
        motor.stop_all()
        for channel in range(12):
            self.assertEqual(self.bus.channel(channel), b"\x00\x00\x00\x10")

    def test_ack_without_register_update_is_reported(self):
        self.bus.ignore_register = 0xFE
        with self.assertRaisesRegex(OSError, "настройки регистров"):
            PCA9685(self.bus, 0x40, 50)

    def test_channel_readback_detects_corruption(self):
        pwm = PCA9685(self.bus, 0x40, 50)
        self.bus.registers[0x09] = 0
        with self.assertRaisesRegex(OSError, "канал 0"):
            pwm.check_percent(0, 0)

    def run_motor_test(self):
        # Часы идут только при sleep_ms: весь импульс воспроизводится без
        # ожидания, а обращения I²C используют ту же модель регистров.
        clock = [0]

        def sleep_ms(duration):
            clock[0] += duration

        machine = SimpleNamespace(I2C=lambda *a, **kw: self.bus, Pin=lambda gp: gp)
        with patch.dict(sys.modules, {"machine": machine}), \
                patch.object(time, "ticks_ms", lambda: clock[0], create=True), \
                patch.object(time, "ticks_diff", lambda a, b: a - b, create=True), \
                patch.object(time, "sleep_ms", sleep_ms, create=True):
            return runpy.run_path(str(FIRMWARE / "motor_test.py"))

    def test_motor_test_reads_running_pwm_and_verifies_stop(self):
        result = self.run_motor_test()
        self.assertEqual(result["peak"], (20, 0))
        self.assertEqual(result["result"], ("completed", 200))
        self.assertIn((0, 20, [0, 0, 51, 3]), result["snapshot"])
        self.assertIn("Опыт завершён", self.output.getvalue())
        for channel in range(12):
            self.assertEqual(self.bus.channel(channel), b"\x00\x00\x00\x10")

    def test_motor_test_missing_address_does_not_start(self):
        self.bus.addresses = []
        with self.assertRaisesRegex(OSError, "PCA9685 не найден"):
            self.run_motor_test()
        self.assertEqual(self.bus.writes, [])
        self.assertIn("создание и сканирование I²C", self.output.getvalue())
        self.assertNotIn("Опыт завершён", self.output.getvalue())

    def test_motor_test_i2c_failure_stops_and_reports_stage(self):
        self.bus.fail_motion_once = True
        with self.assertRaisesRegex(OSError, "обрыв I²C"):
            self.run_motor_test()
        self.assertIn("моторный импульс", self.output.getvalue())
        self.assertNotIn("Опыт завершён", self.output.getvalue())
        for channel in range(12):
            self.assertEqual(self.bus.channel(channel), b"\x00\x00\x00\x10")


if __name__ == "__main__":
    unittest.main()
