"""Запись регистров PCA9685. Готовые I²C и адрес передаёт вызывающий код."""

import time


class PCA9685:
    MODE1 = 0x00
    PRESCALE = 0xFE
    LED0 = 0x06

    def __init__(self, i2c, address, frequency_hz):
        self.i2c = i2c
        self.address = address
        if not (24 <= frequency_hz <= 1526):
            raise ValueError("frequency_hz")
        # Сначала выключаем все 12 моторных каналов, затем меняем частоту.
        for channel in range(12):
            self.set_percent(channel, 0)
        self._write(self.MODE1, 0)
        old = self._read(self.MODE1)
        prescale = int(25000000 / (4096 * frequency_hz) + 0.5) - 1
        self._write(self.MODE1, (old & 0x7f) | 0x10)
        self._write(self.PRESCALE, prescale)
        self._write(self.MODE1, old)
        time.sleep_ms(5) if hasattr(time, "sleep_ms") else time.sleep(0.005)
        self._write(self.MODE1, old | 0x80)

    def _write(self, register, value):
        self.i2c.writeto_mem(self.address, register, bytes((value,)))

    def _read(self, register):
        return self.i2c.readfrom_mem(self.address, register, 1)[0]

    def set_percent(self, channel, percent):
        if type(channel) is not int or not 0 <= channel < 16:
            raise ValueError("channel")
        if type(percent) is not int or not 0 <= percent <= 100:
            raise ValueError("percent")
        base = self.LED0 + 4 * channel
        if percent == 0:
            data = bytes((0, 0, 0, 0x10))  # Постоянный низкий уровень, включая точные 0%.
        elif percent == 100:
            data = bytes((0, 0x10, 0, 0))  # Постоянный высокий уровень, включая точные 100%.
        else:
            count = 4096 * percent // 100
            data = bytes((0, 0, count & 0xff, count >> 8))
        self.i2c.writeto_mem(self.address, base, data)
