"""Ограниченный JSON Lines API через локальный Unix-сокет."""

import asyncio
import fcntl
import json
import os
import re
import time

from robot.types import ControlRequest


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("повторяющийся ключ API")
        result[key] = value
    return result


def parse_request(raw: bytes, source: str = "local") -> ControlRequest:
    if len(raw) > 2048 or not raw.endswith(b"\n"):
        raise ValueError("запрос слишком длинный или без LF")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("неверный JSON") from exc
    if type(data) is not dict or set(data) - {"api_v", "request_id", "op", "params", "expected_revision"}:
        raise ValueError("неверные поля API")
    if type(data.get("api_v")) is not int or data["api_v"] != 1:
        raise ValueError("неверная версия API")
    request_id = data.get("request_id")
    if type(request_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id):
        raise ValueError("неверный request_id")
    op = data.get("op")
    params = data.get("params")
    if type(params) is not dict:
        raise ValueError("params должен быть объектом")
    revision = data.get("expected_revision")
    if op in ("status", "stop"):
        if set(data) != {"api_v", "request_id", "op", "params"} or params:
            raise ValueError("лишние поля STATUS/STOP")
        revision = None
    elif op == "start":
        if set(data) != {"api_v", "request_id", "op", "params", "expected_revision"} or set(params) != {"mode"} or params["mode"] not in ("qr", "manual"):
            raise ValueError("неверный START")
    elif op == "move":
        if set(data) != {"api_v", "request_id", "op", "params", "expected_revision"} or set(params) != {"action", "pwm_pct", "duration_ms"}:
            raise ValueError("неверный MOVE")
        if params["action"] not in ("forward", "backward", "turn_left", "turn_right") or type(params["pwm_pct"]) is not int or type(params["duration_ms"]) is not int:
            raise ValueError("неверные параметры MOVE")
    else:
        raise ValueError("неизвестная операция")
    if op in ("start", "move") and (type(revision) is not int or revision < 0):
        raise ValueError("требуется expected_revision")
    return ControlRequest(request_id, source, op, params, time.monotonic_ns(), revision)


class LocalApi:
    def __init__(self, path: str, controller):
        self.path, self.controller = path, controller
        self.server = None
        self.lock_file = None

    async def start(self):
        # flock отличает работающий экземпляр от оставшегося после сбоя сокета.
        self.lock_file = open(self.path + ".lock", "a+b")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock_file.close()
            self.lock_file = None
            raise RuntimeError("robotd уже запущен") from exc
        if os.path.exists(self.path):
            os.unlink(self.path)
        self.server = await asyncio.start_unix_server(self._client, self.path, limit=2049)
        os.chmod(self.path, 0o660)

    async def close(self):
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            os.unlink(self.path)
        if self.lock_file is not None:
            self.lock_file.close()
            self.lock_file = None

    async def _client(self, reader, writer):
        try:
            raw = await asyncio.wait_for(reader.readline(), 1.0)
            request = parse_request(raw)
            result = await self.controller.handle(request)
        except Exception as exc:
            result = {"request_id": None, "accepted": False, "code": str(exc),
                      "control_revision": self.controller.revision,
                      "status": None, "plan_id": None}
        writer.write((json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        try:
            await asyncio.wait_for(writer.drain(), 0.2)
        except (asyncio.TimeoutError, ConnectionError):
            pass
        writer.close()
        await writer.wait_closed()


async def call(path: str, data: dict, timeout: float = 1.0) -> dict:
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(path), timeout)
    try:
        writer.write((json.dumps(data, separators=(",", ":")) + "\n").encode("utf-8"))
        await asyncio.wait_for(writer.drain(), timeout)
        raw = await asyncio.wait_for(reader.readline(), timeout)
        return json.loads(raw)
    finally:
        writer.close()
        await writer.wait_closed()
