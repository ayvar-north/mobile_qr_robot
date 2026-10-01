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

# Проверяем настройки из файла на Pico. При ошибке движение не начинаем.
config.validate()

# Создаём связь с моторной платой по пинам и адресу из паспорта проводки.
bus = I2C(config.I2C_ID,
          sda=Pin(config.I2C_SDA_GP),
          scl=Pin(config.I2C_SCL_GP),
          freq=100000)
pwm = PCA9685(bus, config.PCA9685_ADDRESS, config.PWM_FREQ_HZ)
driver = MotorDriver(pwm, config.LEFT_MOTOR, config.RIGHT_MOTOR,
                     config.LEFT_INVERTED, config.RIGHT_INVERTED)

try:
    # Motion выполняет один шаг с плавным разгоном и остановкой по времени.
    motion = Motion(driver, time.ticks_diff,
                    config.DIRECTION_DEADTIME_MS,
                    config.RAMP_PCT_PER_S)

    # min выбирает меньшее число: не превышаем пределы из config.py.
    power = min(20, config.MAX_PWM_PCT)
    duration = min(200, config.MAX_STEP_MS)

    # Проверяем только левую гусеницу; ноль оставляет правую выключенной.
    print("Начинаем короткий моторный опыт")
    motion.start(power, 0, duration, time.ticks_ms())

    # Каждые несколько миллисекунд проверяем, не закончился ли срок шага.
    while motion.active is not None:
        motion.tick(time.ticks_ms())
        time.sleep_ms(5)
finally:
    # При завершении, ошибке или Ctrl+C пытаемся выключить все моторы.
    driver.stop_all()

print("Опыт завершён, моторные выходы выключены")
