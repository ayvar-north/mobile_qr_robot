"""Сборка приложения, жизненный цикл устройств и сигналы ОС."""

import argparse
import asyncio
import logging
import signal
import time

from robot.config import load
from robot.controller import Controller
from robot.remote.local_api import LocalApi
from robot.supervisor import Supervisor
from robot.telemetry import Telemetry
from robot.transport.serial_client import FakePicoTransport, SerialClient
from robot.vision.worker import VisionWorker


async def run(config_path):
    config = load(config_path)
    link = FakePicoTransport() if config.dry_run else SerialClient(config.uart_path)
    telemetry = Telemetry()
    supervisor = Supervisor()
    controller = Controller(config, link, supervisor, telemetry)
    vision = VisionWorker(config)
    api = LocalApi(config.socket_path, controller)
    ending = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(name, ending.set)
    try:
        await api.start()
        vision.start()
        last_retry = 0
        last_vision_retry = 0
        controller.state = "WAIT_HARDWARE"
        while not ending.is_set():
            now = time.monotonic_ns()
            if vision.stop_flag.is_set():
                vision.stop_flag.clear()
                controller.revision += 1
                controller.armed = False
                controller.state = "STOPPING"
                controller.outputs_confirmed_off = False
                controller.stop_reason = "qr"
                controller._start_stop("qr")
            batch = vision.latest()
            if batch is not None:
                controller.observe(batch)
            controller.camera_healthy = (vision.healthy() and supervisor.vision_at is not None
                                         and now - supervisor.vision_at <= 500_000_000)
            if not vision.healthy() and controller.mode == "QR":
                controller.fault("ошибка камеры или декодера")
            if controller.state == "WAIT_HARDWARE" and now - last_retry > 1_000_000_000:
                last_retry = now
                try:
                    if not config.dry_run and link.port is None:
                        await link.open()
                    await controller.initialize()
                except Exception as exc:
                    controller.stop_reason = str(exc)
            controller.tick()
            if hasattr(link, "reader"):
                telemetry.counters["parse_errors"] = link.reader.errors
            if config.camera_path is not None and not vision.healthy() and now - last_vision_retry > 1_000_000_000:
                last_vision_retry = now
                # Завершение зависшего процесса не задерживает STOP в цикле событий.
                await asyncio.to_thread(vision.close)
                vision.start()
                controller.gate.reset_for_start()
                controller.gate.last_frame = -1
                supervisor.vision_at = None
            await asyncio.sleep(0.02)
    finally:
        controller.closing = True
        controller.revision += 1
        controller.armed = False
        controller.state = "STOPPING"
        controller._start_stop("shutdown")
        try:
            await asyncio.wait_for(controller.stop_task, 0.7)
        except asyncio.TimeoutError:
            telemetry.record("bootstrap", "stop_uncertain")
        await api.close()
        vision.close()
        await link.close()


def main():
    parser = argparse.ArgumentParser(prog="robotd")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
