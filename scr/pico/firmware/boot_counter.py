"""Счётчик загрузок с двумя записями; сомнительный журнал блокирует ARM."""

from protocol import crc16


def next_counter(prefix="boot"):
    records = []
    for slot in (0, 1):
        try:
            with open("%s%d.dat" % (prefix, slot), "rb") as source:
                data = source.read(14)
            if len(data) != 13 or data[8:9] != b":":
                continue
            raw = data[:8]
            check = data[9:]
            if any(c not in b"0123456789abcdef" for c in raw) or any(c not in b"0123456789ABCDEF" for c in check):
                continue
            if crc16(raw) != int(check, 16):
                continue
            records.append((int(raw, 16), slot))
        except OSError:
            pass
    if not records:
        # Первый запуск журнала делают вручную при отключённом питании моторов.
        raise RuntimeError("boot counter journal absent or corrupt")
    records.sort()
    if len(records) == 2 and records[1][0] - records[0][0] > 1:
        raise RuntimeError("boot counter journal ambiguous")
    value, slot = records[-1]
    if value == 0xffffffff:
        raise RuntimeError("boot counter exhausted")
    value += 1
    raw = ("%08x" % value).encode("ascii")
    target = "%s%d.dat" % (prefix, 1 - slot)
    # Пишем старый слот, сохраняя предыдущую исправную запись.
    with open(target, "wb") as output:
        output.write(raw + b":" + ("%04X" % crc16(raw)).encode("ascii"))
        output.flush()
    with open(target, "rb") as check:
        if check.read() != raw + b":" + ("%04X" % crc16(raw)).encode("ascii"):
            raise RuntimeError("boot counter write failed")
    return value


def initialize(prefix="boot"):
    """Один раз вызвать из USB REPL без питания моторов; не вызывать при старте."""
    for slot in (0, 1):
        try:
            with open("%s%d.dat" % (prefix, slot), "rb"):
                raise RuntimeError("journal already exists")
        except OSError:
            pass
    raw = b"00000000"
    with open(prefix + "0.dat", "wb") as output:
        output.write(raw + b":" + ("%04X" % crc16(raw)).encode("ascii"))
