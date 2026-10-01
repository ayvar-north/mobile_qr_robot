"""Точка запуска Pico: проверка настроек, выключение выходов и цикл UART."""

import time
from machine import I2C, Pin, UART

import config
from boot_counter import next_counter
from controller import Controller
from motion import Motion
from motor_driver import MotorDriver
from pca9685 import PCA9685
from protocol import Reader


def run():
    print("[Pico] Запуск main.py; проверка config.py")
    config.validate()
    print("[Pico] I²C%d: SDA=GP%d, SCL=GP%d, адрес=0x%02X" %
          (config.I2C_ID, config.I2C_SDA_GP, config.I2C_SCL_GP,
           config.PCA9685_ADDRESS))
    i2c = I2C(config.I2C_ID, sda=Pin(config.I2C_SDA_GP),
              scl=Pin(config.I2C_SCL_GP), freq=100000)
    addresses = i2c.scan()
    print("[Pico] Адреса I²C:", ["0x%02X" % address for address in addresses])
    if config.PCA9685_ADDRESS not in addresses:
        raise OSError("PCA9685 не найден: проверьте питание логики, SDA/SCL и перемычки")
    pwm = PCA9685(i2c, config.PCA9685_ADDRESS, config.PWM_FREQ_HZ)
    driver = MotorDriver(pwm, config.LEFT_MOTOR, config.RIGHT_MOTOR,
                         config.LEFT_INVERTED, config.RIGHT_INVERTED)
    try:
        # Новый номер загрузки не даёт принять старый сеанс после перезапуска.
        boot = next_counter()
        print("[Pico] Номер загрузки:", boot)
        uart = UART(config.UART_ID, baudrate=115200, bits=8, parity=None,
                    stop=1, tx=Pin(config.UART_TX_GP), rx=Pin(config.UART_RX_GP),
                    timeout=0)
        motion = Motion(driver, time.ticks_diff, config.DIRECTION_DEADTIME_MS,
                        config.RAMP_PCT_PER_S)
        control = Controller(motion, time.ticks_diff, boot, config.MAX_PWM_PCT,
                             config.MAX_STEP_MS, config.HB_TIMEOUT_MS)
        reader = Reader(time.ticks_diff)
        pending = []
        last_state = control.state
        print("[Pico] UART%d: TX=GP%d, RX=GP%d, 115200 8N1" %
              (config.UART_ID, config.UART_TX_GP, config.UART_RX_GP))
        print("[Pico] Пределы: PWM=%d%%, шаг=%d мс, heartbeat=%d мс" %
              (config.MAX_PWM_PCT, config.MAX_STEP_MS, config.HB_TIMEOUT_MS))
        print("[Pico] DISARMED: ждём HELLO/ARM от Pi; моторы сами не запускаются")
        while True:
            now = time.ticks_ms()
            pending.extend(control.tick(now))  # Сначала местные таймеры, потом UART.
            reader.expire(now)
            available = uart.any()
            if available:
                chunk = uart.read(min(available, 256)) or b""
                frames = reader.feed(chunk, now)
                # STOP в текущей порции имеет приоритет над остальными командами.
                stopped = False
                for frame in frames:
                    if frame[0] == "STOP":
                        stopped = True
                        pending.extend(control.handle(frame, now))
                if not stopped:
                    for frame in frames:
                        pending.extend(control.handle(frame, now))
            pending.extend(control.tick(time.ticks_ms()))
            # Пишем в USB Shell только смену состояния, без сообщений на
            # каждый такт разгона и heartbeat. GPIO UART остаётся протокольным.
            if control.state != last_state:
                print("[Pico] Состояние: %s -> %s; ошибка=%s" %
                      (last_state, control.state, control.fault))
                last_state = control.state
            # Не даём неисправному UART бесконечно накапливать ответы в памяти.
            if len(pending) > 32:
                control._stop("driver_error", time.ticks_ms())
                raise RuntimeError("UART output stalled")
            for _ in range(min(len(pending), 8)):
                frame = pending[0]
                written = uart.write(frame)
                if not written:
                    break
                if written < len(frame):
                    pending[0] = frame[written:]
                    break
                pending.pop(0)
            time.sleep_ms(5)
    finally:
        try:
            driver.stop_all()
            print("[Pico] Завершение main.py: команды выключения отправлены")
        except OSError as exc:
            print("[Pico] Не удалось выключить выходы; отключите моторное питание:", exc)


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print("[Pico] Ошибка main.py:", exc)
        raise
