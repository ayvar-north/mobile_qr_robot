"""Кодек протокола V1, совместимый с реализацией Pico."""

from dataclasses import dataclass

ZERO_SESSION = "0" * 48
TYPES = frozenset(("HELLO", "READY", "ARM", "MOVE", "HEARTBEAT", "STOP", "STATUS", "STATE", "ACK", "DONE", "ERROR"))
STOP_REASONS = frozenset(("user", "qr", "fault", "shutdown", "mode_change", "recovery"))
ERROR_CODES = frozenset(("BAD_MESSAGE", "BAD_VERSION", "BAD_SESSION", "NOT_ARMED", "BUSY", "OUT_OF_RANGE", "ID_CONFLICT", "STALE_ID", "DRIVER_FAULT", "BOOT_COUNTER_FAULT"))


@dataclass(frozen=True)
class Message:
    kind: str
    session: str
    seq: int
    payload: str


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE по точным байтам без разделителя CRC."""
    crc = 0xffff
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xffff if crc & 0x8000 else (crc << 1) & 0xffff
    return crc


def _integer(token: str, signed: bool = False) -> int:
    digits = token[1:] if signed and token.startswith("-") else token
    if (not digits or not digits.isascii() or not digits.isdigit() or
            (len(digits) > 1 and digits[0] == "0") or token == "-0" or token.startswith("+")):
        raise ValueError("число не каноническое")
    value = int(token)
    if not (-2147483648 if signed else 0) <= value <= 4294967295:
        raise ValueError("число вне диапазона")
    return value


def _session(value: str) -> None:
    if len(value) != 48 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("неверный SESSION")


def _validate(message: Message) -> None:
    kind, session, seq, payload = message.kind, message.session, message.seq, message.payload
    if kind not in TYPES or type(seq) is not int or not 0 <= seq <= 0xffffffff:
        raise ValueError("неверный TYPE или SEQ")
    _session(session)
    if not payload or any(c in payload for c in "|\r\n") or not payload.isascii():
        raise ValueError("неверный PAYLOAD")
    parts = payload.split(",")
    if kind == "HELLO":
        if session != ZERO_SESSION or seq != 0 or len(payload) != 32 or any(c not in "0123456789abcdef" for c in payload):
            raise ValueError("неверный HELLO")
    elif kind == "READY":
        if seq != 0 or len(parts) != 4 or parts[0] not in ("DISARMED", "BOOT_SAFE", "FAULT"):
            raise ValueError("неверный READY")
        values = [_integer(p) for p in parts[1:]]
        if not 1 <= values[0] <= 100 or not 1 <= values[1] <= 2000 or not 1 <= values[2] <= 10000:
            raise ValueError("неверные лимиты READY")
    elif kind in ("ARM", "HEARTBEAT", "STATUS"):
        if seq == 0 or payload != "-":
            raise ValueError("неверный пустой запрос")
    elif kind == "MOVE":
        if seq == 0 or len(parts) != 3:
            raise ValueError("неверный MOVE")
        left, right, duration = _integer(parts[0], True), _integer(parts[1], True), _integer(parts[2])
        if not (-100 <= left <= 100 and -100 <= right <= 100 and (left or right) and duration >= 1):
            raise ValueError("MOVE вне диапазона")
    elif kind == "STOP":
        if payload not in STOP_REASONS:
            raise ValueError("неверная причина STOP")
    elif kind == "STATE":
        if seq == 0 or len(parts) != 6 or parts[0] not in ("BOOT_SAFE", "DISARMED", "ARMED_IDLE", "MOVING", "FAULT"):
            raise ValueError("неверный STATE")
        _integer(parts[1]); _integer(parts[2], True); _integer(parts[3], True); _integer(parts[4])
        if not parts[5].isascii() or not parts[5].replace("_", "").isalnum():
            raise ValueError("неверный fault")
    elif kind == "ACK":
        if seq == 0 or payload not in ("ARM", "MOVE", "HEARTBEAT", "STOP"):
            raise ValueError("неверный ACK")
    elif kind == "DONE":
        if seq == 0 or len(parts) != 2 or parts[0] not in ("completed", "stopped", "link_timeout", "session_replaced", "driver_error"):
            raise ValueError("неверный DONE")
        _integer(parts[1])
    elif kind == "ERROR":
        if payload not in ERROR_CODES:
            raise ValueError("неверный ERROR")


def encode(message: Message) -> bytes:
    _validate(message)
    head = f"V1|{message.kind}|{message.session}|{message.seq}|{message.payload}".encode("ascii")
    result = head + f"|{crc16(head):04X}\n".encode("ascii")
    if len(result) > 256:
        raise ValueError("кадр слишком длинный")
    return result


def decode(frame: bytes) -> Message:
    if len(frame) > 256 or not frame.endswith(b"\n") or b"\r" in frame:
        raise ValueError("неверная длина кадра")
    try:
        fields = frame[:-1].decode("ascii").split("|")
    except UnicodeError as exc:
        raise ValueError("только ASCII") from exc
    if len(fields) != 6 or fields[0] != "V1":
        raise ValueError("неверная оболочка")
    if len(fields[5]) != 4 or any(c not in "0123456789ABCDEF" for c in fields[5]):
        raise ValueError("неверная CRC")
    if crc16(frame[:-6]) != int(fields[5], 16):
        raise ValueError("ошибка CRC")
    message = Message(fields[1], fields[2], _integer(fields[3]), fields[4])
    _validate(message)
    return message


class Reader:
    """Собирает части строк и отбрасывает переполненный либо просроченный кадр."""

    def __init__(self):
        self.data = bytearray()
        self.since_ns = None
        self.discard = False
        self.errors = 0

    def expire(self, now_ns: int) -> None:
        if self.since_ns is not None and now_ns - self.since_ns > 100_000_000:
            self.data.clear()
            self.since_ns = None
            self.discard = False
            self.errors += 1

    def feed(self, chunk: bytes, now_ns: int) -> list[Message]:
        result = []
        self.expire(now_ns)
        for byte in chunk:
            if self.discard:
                if byte == 10:
                    self.discard = False
                continue
            if self.since_ns is None:
                self.since_ns = now_ns
            self.data.append(byte)
            if len(self.data) > 256:
                self.data.clear()
                self.since_ns = None
                self.discard = byte != 10
                self.errors += 1
            elif byte == 10:
                try:
                    result.append(decode(bytes(self.data)))
                except ValueError:
                    self.errors += 1
                self.data.clear()
                self.since_ns = None
        return result
