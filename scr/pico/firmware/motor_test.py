"""Короткая проверка левой гусеницы через Thonny; инструкция — §3.9 README.

Запускайте вручную на Pico с поднятыми гусеницами. Модули прошивки должны
быть сохранены на Pico, а main.py и программа управления на Pi остановлены.
Перед запуском подготовьте доступное отключение моторного питания.
"""

import time
from machine import I2C, Pin

import config
from pca9685 import PCA9685
from motor_driver import MotorDriver
from motion import Motion


def check_outputs(pwm, driver):
    """Проверить PWM и направление обеих сторон чтением памяти PCA9685.

    Возвращаем снимок регистров для печати после выключения моторов.
    Считывание регистров не показывает, есть ли питание на силовых мостах.
    """
    snapshot = []
    for channels, inverted, value in zip(driver.channels, driver.inverted, driver.current):
        direction = -value if inverted else value
        expected = (abs(value), 100 if direction > 0 else 0,
                    100 if direction < 0 else 0)
        for channel, percent in zip(channels, expected):
            data = pwm.check_percent(channel, percent)
            snapshot.append((channel, percent, list(data)))
    return snapshot


def print_outputs(label, snapshot):
    print("[Тест]", label, "(ON_L, ON_H, OFF_L, OFF_H):")
    for channel, percent, data in snapshot:
        print("  Канал %d: %d%%, регистры=%s" % (channel, percent, data))


driver = None
failure = None
stage = "проверка config.py"

try:
    print("[Тест] motor_test.py: диагностика PCA9685 с проверкой AI")
    # Показываем настройки именно из загруженного на Pico файла.
    config.validate()
    print("[Тест] I²C%d: SDA=GP%d, SCL=GP%d, адрес=0x%02X" %
          (config.I2C_ID, config.I2C_SDA_GP, config.I2C_SCL_GP,
           config.PCA9685_ADDRESS))
    stage = "создание и сканирование I²C"
    bus = I2C(config.I2C_ID,
              sda=Pin(config.I2C_SDA_GP),
              scl=Pin(config.I2C_SCL_GP),
              freq=100000)
    addresses = bus.scan()
    print("[Тест] Найдены адреса:", ["0x%02X" % address for address in addresses])
    if config.PCA9685_ADDRESS not in addresses:
        raise OSError("PCA9685 не найден: проверьте питание логики, SDA/SCL и перемычки")
    stage = "настройка PCA9685 и выключение выходов"
    pwm = PCA9685(bus, config.PCA9685_ADDRESS, config.PWM_FREQ_HZ)
    driver = MotorDriver(pwm, config.LEFT_MOTOR, config.RIGHT_MOTOR,
                         config.LEFT_INVERTED, config.RIGHT_INVERTED)
    print_outputs("Перед движением", check_outputs(pwm, driver))
    # Motion выполняет один шаг с плавным разгоном и остановкой по времени.
    motion = Motion(driver, time.ticks_diff,
                    config.DIRECTION_DEADTIME_MS,
                    config.RAMP_PCT_PER_S)

    # min выбирает меньшее число: не превышаем пределы из config.py.
    power = min(20, config.MAX_PWM_PCT)
    duration = min(200, config.MAX_STEP_MS)
    print("[Тест] PWM=%d%%, длительность=%d мс, разгон=%d %%/с" %
          (power, duration, config.RAMP_PCT_PER_S))
    print("[Тест] Назначение клемм: левая %s, правая %s" %
          (config.LEFT_MOTOR, config.RIGHT_MOTOR))
    print("[Тест] 20% на 200 мс могут быть недостаточны для старта мотора.")
    print("[Тест] Питание моторов и вращение программно не измеряются.")

    # Проверяем только левую гусеницу; ноль оставляет правую выключенной.
    print("Начинаем короткий моторный опыт")
    stage = "моторный импульс"
    started = time.ticks_ms()
    motion.start(power, 0, duration, started)
    target = motion.active["target"]
    samples = []
    peak = (0, 0)
    snapshot = None
    result = None

    # Каждые несколько миллисекунд проверяем, не закончился ли срок шага.
    while motion.active is not None:
        now = time.ticks_ms()
        result = motion.tick(now)
        elapsed = time.ticks_diff(now, started)
        if motion.active is not None:
            peak = tuple(max(a, abs(b)) for a, b in zip(peak, motion.current))
            if not samples or elapsed - samples[-1][0] >= 50:
                samples.append((elapsed, motion.current))
            if snapshot is None and motion.current == motion.active["target"]:
                snapshot = check_outputs(pwm, driver)
        # Во время импульса только собираем данные: печать в USB может
        # задержать следующий tick и тем самым продлить работу моторов.
        time.sleep_ms(5)
except BaseException as exc:
    # Исключение печатаем только после попытки остановки в finally.
    failure = exc
    raise
finally:
    # При завершении, ошибке или Ctrl+C пытаемся выключить все моторы.
    try:
        if driver is not None:
            driver.stop_all()
            for channel in range(12):
                pwm.check_percent(channel, 0)
            print("[Тест] Выключение: регистры каналов 0–11 проверены, все 0%")
    except OSError as exc:
        print("[Тест] Выключение не подтверждено! Отключите моторное питание:", exc)
        raise
    finally:
        if failure is not None:
            print("[Тест] Ошибка на этапе '%s': %s" % (stage, failure))

print("[Тест] Задание PWM левой/правой:", target)
print("[Тест] Разгон (мс, PWM левой/правой):", samples)
print("[Тест] Максимальный заданный PWM:", peak)
print("[Тест] Результат Motion:", result)
if snapshot is not None:
    print_outputs("Прочитано при достижении целевого PWM", snapshot)
else:
    print("[Тест] Целевой PWM не достигнут; снимка регистров движения нет.")
print("Опыт завершён, моторные выходы выключены")
print("[Тест] Это подтверждает регистры, но не вращение. Если мотор стоит,")
print("[Тест] проверьте моторное питание VIN, фактическую клемму и контакты.")
