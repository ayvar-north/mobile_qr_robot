"""Отдельный процесс зрения с очередью только для самого свежего кадра."""

import multiprocessing as mp
import queue
import threading
import time

from robot.qr.schema import QrRejected, parse
from robot.vision.capture import CameraCapture
from robot.vision.decoder import QrDecoder


def _latest(target, item):
    try:
        target.put_nowait(item)
    except queue.Full:
        try:
            target.get_nowait()
        except queue.Empty:
            pass
        try:
            target.put_nowait(item)
        except queue.Full:
            pass


def _run(path, width, height, fps, max_pwm, max_step_ms, outbox, stop_flag, fault_flag, ending):
    capture = CameraCapture(path, width, height, fps)
    frames = queue.Queue(maxsize=1)
    try:
        capture.open()
        decoder = QrDecoder()

        def read_forever():
            try:
                while not ending.is_set():
                    _latest(frames, capture.read())
            except Exception:
                fault_flag.set()

        thread = threading.Thread(target=read_forever, daemon=True)
        thread.start()
        while not ending.is_set() and not fault_flag.is_set():
            try:
                frame = frames.get(timeout=0.1)
            except queue.Empty:
                continue
            batch = decoder.decode(frame)
            # При переполнении обычный пакет заменяется; STOP хранится отдельно.
            for payload in batch.payloads:
                try:
                    if parse(payload, max_pwm, max_step_ms).action == "stop":
                        stop_flag.set()
                except QrRejected:
                    pass
            _latest(outbox, batch)
    except Exception:
        fault_flag.set()
    finally:
        capture.close()


class VisionWorker:
    def __init__(self, config):
        self.config = config
        self.outbox = mp.Queue(maxsize=1)
        self.stop_flag = mp.Event()
        self.fault_flag = mp.Event()
        self.ending = mp.Event()
        self.process = None

    def start(self):
        if self.config.camera_path is None:
            return
        self.stop_flag.clear()
        self.fault_flag.clear()
        self.ending.clear()
        self.latest()  # Старые наблюдения другого процесса не относятся к новому сеансу.
        self.process = mp.Process(target=_run, args=(self.config.camera_path,
            self.config.camera_width, self.config.camera_height, self.config.camera_fps,
            self.config.max_pwm_pct, self.config.max_step_ms, self.outbox,
            self.stop_flag, self.fault_flag, self.ending), daemon=True)
        self.process.start()

    def latest(self):
        result = None
        while True:
            try:
                result = self.outbox.get_nowait()
            except queue.Empty:
                return result

    def healthy(self):
        return self.process is not None and self.process.is_alive() and not self.fault_flag.is_set()

    def close(self):
        self.ending.set()
        if self.process is not None:
            self.process.join(timeout=0.5)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=0.5)
