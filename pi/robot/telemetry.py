"""Снимки состояния и ограниченный журнал структурированных событий."""

import json
import logging
import queue
import threading
import time
from collections import deque
from dataclasses import asdict


class Telemetry:
    def __init__(self):
        self.events = deque(maxlen=256)
        self.counters = {"parse_errors": 0, "timeouts": 0, "cancellations": 0}
        self.logger = logging.getLogger("robot")
        self.log_queue = queue.Queue(maxsize=256)
        threading.Thread(target=self._write_logs, daemon=True).start()

    def _write_logs(self):
        # Медленная запись журнала не задерживает STOP в цикле управления.
        while True:
            item = self.log_queue.get()
            self.logger.info(json.dumps(item, ensure_ascii=False))

    def record(self, component, event, **fields):
        item = {"at_ns": time.monotonic_ns(), "component": component, "event": event, **fields}
        self.events.append(item)
        try:
            self.log_queue.put_nowait(item)
        except queue.Full:
            pass  # При перегрузке сохраняется ограниченный журнал в памяти.

    def snapshot(self, status):
        return asdict(status)
