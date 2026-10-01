"""Copy this directory to Pico and run main.py after filling config.py."""

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
            pending.extend(control.tick(now))  # Expire locally before reading UART.
            reader.expire(now)
            available = uart.any()
            if available:
                chunk = uart.read(min(available, 256)) or b""
                frames = reader.feed(chunk, now)
                # STOP from a completed batch wins over other requests.
                stopped = False
                for frame in frames:
                    if frame[0] == "STOP":
                        stopped = True
                        pending.extend(control.handle(frame, now))
                if not stopped:
                    for frame in frames:
                        pending.extend(control.handle(frame, now))
            pending.extend(control.tick(time.ticks_ms()))
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
            pass  # I2C failure may leave PCA9685 outputs active.


if __name__ == "__main__":
    run()
