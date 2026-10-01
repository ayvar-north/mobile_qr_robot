"""Опциональный адаптер текстовых команд Bluetooth к локальному API.

BlueZ должен предоставить RFCOMM-поток уже сопряжённого и доверенного телефона.
Эта граница не создаёт второй контроллер и не принимает команды оболочки.
"""

import asyncio
import uuid

from robot.remote.local_api import call


def parse_line(raw: bytes):
    if len(raw) > 128 or not raw.endswith(b"\n"):
        raise ValueError("строка Bluetooth слишком длинная")
    try:
        command = raw.decode("ascii").strip().upper()
    except UnicodeError as exc:
        raise ValueError("только ASCII") from exc
    mapping = {"STATUS": ("status", {}), "STOP": ("stop", {}),
               "START QR": ("start", {"mode": "qr"}),
               "START MANUAL": ("start", {"mode": "manual"})}
    if command not in mapping:
        raise ValueError("неизвестная команда Bluetooth")
    return mapping[command]


async def relay(reader, writer, socket_path):
    """Принимать только четыре команды с ограничением частоты 5 запросов/с."""
    last = 0.0
    try:
        while True:
            raw = await asyncio.wait_for(reader.readline(), 30)
            if not raw:
                break
            now = asyncio.get_running_loop().time()
            if now - last < 0.2:
                continue
            last = now
            try:
                op, params = parse_line(raw)
                data = {"api_v": 1, "request_id": uuid.uuid4().hex, "op": op, "params": params}
                if op == "start":
                    status = await call(socket_path, {"api_v": 1, "request_id": uuid.uuid4().hex,
                                                      "op": "status", "params": {}})
                    data["expected_revision"] = status["control_revision"]
                result = await call(socket_path, data)
                response = f"{result['code']}\n"
            except Exception as exc:
                response = f"ERROR {exc}\n"
            writer.write(response.encode("ascii", errors="replace"))
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()
