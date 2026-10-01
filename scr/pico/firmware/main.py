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
    config.validate()
    i2c = I2C(config.I2C_ID, sda=Pin(config.I2C_SDA_GP),
              scl=Pin(config.I2C_SCL_GP), freq=100000)
    pwm = PCA9685(i2c, config.PCA9685_ADDRESS, config.PWM_FREQ_HZ)
    driver = MotorDriver(pwm, config.LEFT_MOTOR, config.RIGHT_MOTOR,
                         config.LEFT_INVERTED, config.RIGHT_INVERTED)
    try:
        # Новый номер загрузки не даёт принять старый сеанс после перезапуска.
        boot = next_counter()
        uart = UART(config.UART_ID, baudrate=115200, bits=8, parity=None,
                    stop=1, tx=Pin(config.UART_TX_GP), rx=Pin(config.UART_RX_GP),
                    timeout=0)
        motion = Motion(driver, time.ticks_diff, config.DIRECTION_DEADTIME_MS,
                        config.RAMP_PCT_PER_S)
        control = Controller(motion, time.ticks_diff, boot, config.MAX_PWM_PCT,
                             config.MAX_STEP_MS, config.HB_TIMEOUT_MS)
        reader = Reader(time.ticks_diff)
        pending = []
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
        except OSError:
            pass  # При отказе I²C выходы PCA9685 могут остаться активными.


if __name__ == "__main__":
    run()
