"""Запись регистров PCA9685. Готовые I²C и адрес передаёт вызывающий код."""

import time


class PCA9685:
    MODE1 = 0x00
    MODE2 = 0x01
    AUTO_INCREMENT = 0x20
    SLEEP = 0x10
    PRESCALE = 0xFE
    LED0 = 0x06

    def __init__(self, i2c, address, frequency_hz):
        self.i2c = i2c
        self.address = address
        if not (24 <= frequency_hz <= 1526):
            raise ValueError("frequency_hz")
        print("[PCA9685] Адрес 0x%02X, заданная частота %d Гц" %
              (address, frequency_hz))
        # set_percent записывает сразу четыре последовательных регистра.
        # Без AI каждый байт попадает в один и тот же регистр: I²C не выдаёт
        # ошибку, но PWM и направление не устанавливаются. Включаем AI ДО
        # первого выключения каналов и сохраняем его при настройке частоты.
        self._write(self.MODE1, self.AUTO_INCREMENT | self.SLEEP)
        # Выходы должны выдавать обычные, неинвертированные логические уровни.
        self._write(self.MODE2, 0x04)
        for channel in range(12):
            self.set_percent(channel, 0)
        prescale = int(25000000 / (4096 * frequency_hz) + 0.5) - 1
        self._write(self.PRESCALE, prescale)
        self._write(self.MODE1, self.AUTO_INCREMENT)
        time.sleep_ms(5) if hasattr(time, "sleep_ms") else time.sleep(0.005)
        self._write(self.MODE1, self.AUTO_INCREMENT | 0x80)
        # Ответ ACK на I²C ещё не подтверждает содержимое регистров.
        mode1 = self._read(self.MODE1)
        mode2 = self._read(self.MODE2)
        actual_prescale = self._read(self.PRESCALE)
        print("[PCA9685] Прочитано: MODE1=0x%02X, MODE2=0x%02X, PRESCALE=%d" %
              (mode1, mode2, actual_prescale))
        if (mode1 & (self.AUTO_INCREMENT | self.SLEEP | 0x40) != self.AUTO_INCREMENT
                or mode2 != 0x04 or actual_prescale != prescale):
            raise OSError("PCA9685: настройки регистров не совпали")
        for channel in range(12):
            self.check_percent(channel, 0)
        print("[PCA9685] AI включён, SLEEP выключен; каналы 0–11 проверены: 0%")

    def _write(self, register, value):
        self.i2c.writeto_mem(self.address, register, bytes((value,)))

    def _read(self, register):
        return self.i2c.readfrom_mem(self.address, register, 1)[0]

    def set_percent(self, channel, percent):
        data = self._percent_data(channel, percent)
        self.i2c.writeto_mem(self.address, self.LED0 + 4 * channel, data)

    def _percent_data(self, channel, percent):
        if type(channel) is not int or not 0 <= channel < 16:
            raise ValueError("channel")
        if type(percent) is not int or not 0 <= percent <= 100:
            raise ValueError("percent")
        if percent == 0:
            data = bytes((0, 0, 0, 0x10))  # Постоянный низкий уровень, включая точные 0%.
        elif percent == 100:
            data = bytes((0, 0x10, 0, 0))  # Постоянный высокий уровень, включая точные 100%.
        else:
            count = 4096 * percent // 100
            data = bytes((0, 0, count & 0xff, count >> 8))
        return data

    def check_percent(self, channel, percent):
        """Прочитать четыре регистра канала и проверить записанный PWM.

        Это проверка памяти PCA9685, а не измерение напряжения или вращения
        мотора. В рабочем цикле её не вызываем, чтобы не замедлять остановку.
        """
        expected = self._percent_data(channel, percent)
        actual = self.i2c.readfrom_mem(self.address, self.LED0 + 4 * channel, 4)
        if actual != expected:
            raise OSError("PCA9685: канал %d, ожидалось %s, прочитано %s" %
                          (channel, list(expected), list(actual)))
        return actual
