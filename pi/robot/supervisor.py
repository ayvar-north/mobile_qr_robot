"""Контроль свежести цикла и результатов зрения перед heartbeat."""

import time


class Supervisor:
    def __init__(self):
        now = time.monotonic_ns()
        self.controller_at = now
        self.executor_at = now
        self.vision_at = None

    def mark_control(self, now_ns=None):
        self.controller_at = now_ns or time.monotonic_ns()

    def mark_execution(self, now_ns=None):
        self.executor_at = now_ns or time.monotonic_ns()

    def mark_vision(self, decoded_at_ns):
        self.vision_at = decoded_at_ns

    def healthy(self, qr_mode: bool, now_ns=None):
        now = now_ns or time.monotonic_ns()
        if now - self.controller_at > 200_000_000 or now - self.executor_at > 200_000_000:
            return False
        if qr_mode and (self.vision_at is None or now - self.vision_at > 500_000_000):
            return False
        return True
