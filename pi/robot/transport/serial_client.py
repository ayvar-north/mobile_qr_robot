"""Единственный владелец UART: сеанс, ID, ответы и ограниченные повторы."""

import asyncio
import secrets
import time

from robot.transport.codec import Message, Reader, ZERO_SESSION, encode


class LinkFault(RuntimeError):
    """Результат запроса к Pico неизвестен либо Pico сообщил отказ."""


class SerialClient:
    def __init__(self, path: str):
        self.path = path
        self.port = None
        self.reader = Reader()
        self.task = None
        self.session = None
        self.seq = 0
        self.max_pwm = 0
        self.max_step_ms = 0
        self.hb_timeout_ms = 0
        self.pending = {}
        self.ready_waiter = None
        self.fault = None
        self.last_rx_ns = None

    async def open(self):
        """Открывать физический UART разрешено только этому модулю."""
        if self.port is not None:
            return
        import serial
        self.port = serial.Serial(self.path, 115200, bytesize=8, parity="N", stopbits=1,
                                  timeout=0, write_timeout=0.05)
        self.port.reset_input_buffer()
        self.task = asyncio.create_task(self._read_loop())

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.port is not None:
            self.port.close()
            self.port = None

    def _write(self, message: Message):
        if self.port is None:
            raise LinkFault("UART закрыт")
        data = encode(message)
        if self.port.write(data) != len(data):
            raise LinkFault("неполная запись UART")

    async def _read_loop(self):
        try:
            while True:
                now = time.monotonic_ns()
                self.reader.expire(now)
                chunk = self.port.read(256)
                for message in self.reader.feed(chunk, now):
                    self.last_rx_ns = now
                    if message.kind == "READY":
                        if self.ready_waiter is not None and not self.ready_waiter.done():
                            self.ready_waiter.set_result(message)
                        elif self.session is not None and message.session != self.session:
                            self.fault = "неожиданный READY"
                    elif message.session == self.session or (self.session is None and message.session == ZERO_SESSION):
                        queue = self.pending.get(message.seq)
                        if queue is not None:
                            queue.put_nowait(message)
                        elif message.kind in ("DONE", "ERROR") and message.seq == 0:
                            self.fault = message.payload
                await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.fault = str(exc)

    async def handshake(self):
        """Каждый START создаёт новый nonce и новый сеанс."""
        if self.port is None or self.fault or (self.task is not None and self.task.done()):
            await self.close()
            await self.open()
        self.session = None
        self.pending.clear()
        self.seq = 0
        self.fault = None
        nonce = secrets.token_hex(16)
        self.ready_waiter = asyncio.get_running_loop().create_future()
        hello = Message("HELLO", ZERO_SESSION, 0, nonce)
        try:
            for _ in range(3):
                self._write(hello)
                try:
                    answer = await asyncio.wait_for(asyncio.shield(self.ready_waiter), 0.2)
                    break
                except asyncio.TimeoutError:
                    continue
            else:
                raise LinkFault("нет READY")
            if answer.session[:32] != nonce or answer.payload.split(",")[0] != "DISARMED":
                raise LinkFault("неверный READY")
            self.session = answer.session
            _, pwm, step, hb = answer.payload.split(",")
            self.max_pwm, self.max_step_ms, self.hb_timeout_ms = int(pwm), int(step), int(hb)
        finally:
            self.ready_waiter = None

    def _next_seq(self):
        if self.seq == 0xffffffff:
            raise LinkFault("исчерпан SEQ, нужен новый сеанс")
        self.seq += 1
        return self.seq

    async def request(self, kind: str, payload: str = "-", done_ms: int | None = None):
        """Повторяет исходный кадр с тем же ID; новый ID не повторяет движение."""
        if self.session is None or self.fault:
            raise LinkFault(self.fault or "нет сеанса")
        seq = self._next_seq()
        message = Message(kind, self.session, seq, payload)
        queue = asyncio.Queue()
        self.pending[seq] = queue
        deadline = time.monotonic() + ((done_ms + 500) / 1000 if done_ms is not None else 0.6)
        sent = 0
        next_retry = 0.0
        try:
            while True:
                if self.fault:
                    raise LinkFault(self.fault)
                if time.monotonic() >= deadline:
                    raise LinkFault(f"тайм-аут {kind}")
                if sent < 3 and time.monotonic() >= next_retry:
                    self._write(message)
                    sent += 1
                    next_retry = time.monotonic() + 0.2
                try:
                    answer = await asyncio.wait_for(queue.get(), min(0.2, max(0.001, deadline - time.monotonic())))
                except asyncio.TimeoutError:
                    continue
                if answer.kind == "ERROR":
                    raise LinkFault(answer.payload)
                if kind == "MOVE":
                    if answer.kind == "ACK" and answer.payload == "MOVE":
                        continue
                    if answer.kind == "DONE":
                        if answer.payload.split(",", 1)[0] != "completed":
                            raise LinkFault(answer.payload)
                        return seq
                elif kind == "STATUS" and answer.kind == "STATE":
                    return answer
                elif answer.kind == "ACK" and answer.payload == kind:
                    return answer
        finally:
            self.pending.pop(seq, None)

    async def arm(self):
        return await self.request("ARM")

    async def move(self, left: int, right: int, duration_ms: int):
        if max(abs(left), abs(right)) > self.max_pwm or duration_ms > self.max_step_ms:
            raise LinkFault("шаг превышает лимиты READY")
        return await self.request("MOVE", f"{left},{right},{duration_ms}", duration_ms)

    async def heartbeat(self):
        return await self.request("HEARTBEAT")

    async def stop(self, reason: str):
        """STOP доступен даже при утраченном сеансе; ACK подтверждает запись выходов."""
        session = self.session or ZERO_SESSION
        seq = self._next_seq()
        queue = asyncio.Queue()
        self.pending[seq] = queue
        frame = Message("STOP", session, seq, reason)
        try:
            for _ in range(3):
                self._write(frame)
                try:
                    while True:
                        answer = await asyncio.wait_for(queue.get(), 0.2)
                        if answer.kind == "ERROR":
                            raise LinkFault(answer.payload)
                        if answer.kind == "ACK" and answer.payload == "STOP":
                            self.session = None
                            return
                except asyncio.TimeoutError:
                    continue
            raise LinkFault("нет ACK STOP")
        finally:
            self.pending.pop(seq, None)


class FakePicoTransport:
    """Полная имитация интерфейса: этот объект никогда не открывает UART."""

    def __init__(self):
        self.session = None
        self.seq = 0
        self.max_pwm = 30
        self.max_step_ms = 2000
        self.hb_timeout_ms = 500
        self.fault = None
        self.moves = []

    async def open(self):
        pass

    async def close(self):
        pass

    async def handshake(self):
        self.session = secrets.token_hex(24)
        self.seq = 0
        self.fault = None

    async def arm(self):
        if self.session is None:
            raise LinkFault("нет сеанса")

    async def move(self, left, right, duration_ms):
        if self.session is None:
            raise LinkFault("нет разрешения")
        self.seq += 1
        self.moves.append((left, right, duration_ms))
        await asyncio.sleep(duration_ms / 1000)
        return self.seq

    async def heartbeat(self):
        if self.session is None:
            raise LinkFault("нет разрешения")

    async def stop(self, reason):
        self.session = None
