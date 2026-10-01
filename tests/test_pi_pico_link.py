"""Сквозная проверка Pi-клиента с настоящим протоколом Pico и фальшивым UART."""

import asyncio
import sys
import time
import unittest
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi"))
sys.path.insert(0, str(ROOT / "scr/pico/firmware"))

from controller import Controller as PicoController
from motion import Motion
from protocol import decode as pico_decode
from robot.transport.serial_client import SerialClient


class FakeDriver:
    def __init__(self):
        self.values = (0, 0)

    def set_tracks(self, left, right):
        self.values = left, right

    def stop_all(self):
        self.values = (0, 0)


class FakePort:
    def __init__(self):
        self.start = time.monotonic()
        self.driver = FakeDriver()
        self.pico = PicoController(Motion(self.driver, lambda a, b: a - b, 10, 100),
                                   lambda a, b: a - b, 1)
        self.responses = deque()
        self.drop_done = True
        self.moves_sent = 0

    def now(self):
        return int((time.monotonic() - self.start) * 1000)

    def write(self, data):
        request = pico_decode(data)
        if request[0] == "MOVE":
            self.moves_sent += 1
        self.responses.extend(self.pico.handle(request, self.now()))
        return len(data)

    def read(self, count):
        for response in self.pico.tick(self.now()):
            if self.drop_done and b"|DONE|" in response:
                self.drop_done = False
            else:
                self.responses.append(response)
        return self.responses.popleft() if self.responses else b""

    def reset_input_buffer(self):
        self.responses.clear()

    def close(self):
        pass


class LinkContract(unittest.IsolatedAsyncioTestCase):
    async def test_lost_done_retries_original_move_only(self):
        port = FakePort()
        client = SerialClient("unused")
        client.port = port
        client.task = asyncio.create_task(client._read_loop())
        try:
            await client.handshake()
            await client.arm()
            await client.move(10, 10, 50)
            self.assertEqual(port.moves_sent, 2)
            self.assertEqual(port.driver.values, (0, 0))
            await client.stop("user")
            self.assertIsNone(client.session)
            self.assertTrue(port.pico.revoked)
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
