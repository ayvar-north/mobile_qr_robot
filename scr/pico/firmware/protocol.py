"""Кадры UART V1: ASCII, CRC и ограниченный приёмный буфер; без machine."""

TYPES = ("HELLO", "READY", "ARM", "MOVE", "HEARTBEAT", "STOP",
         "STATUS", "STATE", "ACK", "DONE", "ERROR")
ZERO_SESSION = "0" * 48
STOP_REASONS = ("user", "qr", "fault", "shutdown", "mode_change", "recovery")


def crc16(data):
    """CRC-16/CCITT-FALSE по точным байтам кадра до разделителя CRC."""
    crc = 0xffff
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xffff if crc & 0x8000 else (crc << 1) & 0xffff
    return crc


def integer(token, signed=False):
    if not token or token in ("-0", "+0") or token[0] == "+":
        raise ValueError("number")
    digits = token[1:] if token[0] == "-" and signed else token
    if not digits or not digits.isdigit() or (len(digits) > 1 and digits[0] == "0"):
        raise ValueError("number")
    if token[0] == "-" and (not signed or digits == "0"):
        raise ValueError("number")
    value = int(token)
    if value < -2147483648 or value > 4294967295:
        raise ValueError("number")
    return value


def _session(token):
    if len(token) != 48 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("session")


def encode(kind, session, seq, payload="-"):
    if kind not in TYPES or type(seq) is not int or not 0 <= seq <= 0xffffffff:
        raise ValueError("type or seq")
    _session(session)
    if not payload or any(c in payload for c in "|\r\n"):
        raise ValueError("payload")
    head = ("V1|%s|%s|%d|%s" % (kind, session, seq, payload)).encode("ascii")
    frame = head + ("|%04X\n" % crc16(head)).encode("ascii")
    if len(frame) > 256:
        raise ValueError("frame length")
    return frame


def decode(frame):
    if len(frame) > 256 or not frame.endswith(b"\n") or b"\r" in frame:
        raise ValueError("frame")
    try:
        line = frame[:-1].decode("ascii")
    except UnicodeError:
        raise ValueError("ascii")
    fields = line.split("|")
    if len(fields) != 6:
        raise ValueError("fields")
    version, kind, session, seq_text, payload, check = fields
    if version != "V1":
        raise ValueError("version")
    if kind not in TYPES:
        raise ValueError("type")
    _session(session)
    seq = integer(seq_text)
    if seq > 0xffffffff or not payload or any(c in payload for c in "|\r\n"):
        raise ValueError("payload")
    if len(check) != 4 or any(c not in "0123456789ABCDEF" for c in check):
        raise ValueError("crc")
    if crc16(frame[:-6]) != int(check, 16):
        raise ValueError("crc")
    parts = payload.split(",")
    if kind == "HELLO":
        if seq != 0 or len(payload) != 32 or any(c not in "0123456789abcdef" for c in payload) or session != ZERO_SESSION:
            raise ValueError("hello")
    elif kind in ("ARM", "HEARTBEAT", "STATUS"):
        if payload != "-" or seq == 0:
            raise ValueError("empty payload")
    elif kind == "STOP":
        if payload not in STOP_REASONS:
            raise ValueError("stop reason")
    elif kind == "MOVE":
        if len(parts) != 3 or seq == 0:
            raise ValueError("move")
        left, right, duration = integer(parts[0], True), integer(parts[1], True), integer(parts[2])
        if not (-100 <= left <= 100 and -100 <= right <= 100 and duration >= 1):
            raise ValueError("move range")
    else:
        raise ValueError("unexpected inbound type")
    return kind, session, seq, payload


class Reader:
    def __init__(self, ticks_diff):
        self.diff = ticks_diff
        self.data = bytearray()
        self.since = None
        self.discard = False
        self.errors = 0

    def feed(self, chunk, now):
        """Собрать полные строки; длинные и повреждённые кадры отбросить."""
        frames = []
        for byte in chunk:
            if self.since is not None and self.diff(now, self.since) > 100:
                self.data = bytearray()
                self.since = None
                self.discard = False
                self.errors += 1
            if self.discard:
                if byte == 10:
                    self.discard = False
                continue
            if self.since is None:
                self.since = now
            if len(self.data) >= 256:
                self.data = bytearray()
                self.since = None
                self.discard = byte != 10
                self.errors += 1
                continue
            self.data.append(byte)
            if byte == 10:
                try:
                    frames.append(decode(bytes(self.data)))
                except ValueError:
                    self.errors += 1
                self.data = bytearray()
                self.since = None
        return frames

    def expire(self, now):
        if self.since is not None and self.diff(now, self.since) > 100:
            self.data = bytearray()
            self.since = None
            self.errors += 1
