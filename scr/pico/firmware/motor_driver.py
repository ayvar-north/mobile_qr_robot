"""Знаковый PWM двух гусениц: положительный знак означает ход вперёд."""


CHANNELS = {"MA": (0, 1, 2), "MB": (3, 4, 5),
            "MC": (6, 7, 8), "MD": (9, 10, 11)}


class MotorDriver:
    def __init__(self, pwm, left_motor, right_motor, left_inverted, right_inverted):
        if left_motor not in CHANNELS or right_motor not in CHANNELS or left_motor == right_motor:
            raise ValueError("motor mapping")
        if type(left_inverted) is not bool or type(right_inverted) is not bool:
            raise ValueError("inversion")
        self.pwm = pwm
        self.channels = (CHANNELS[left_motor], CHANNELS[right_motor])
        self.inverted = (left_inverted, right_inverted)
        self.current = (0, 0)
        self.stop_all()  # При старте выключаем и неиспользуемые клеммы.
        print("[Моторы] Левая: %s, PWM/IN1/IN2=%s, инверсия=%s" %
              (left_motor, self.channels[0], left_inverted))
        print("[Моторы] Правая: %s, PWM/IN1/IN2=%s, инверсия=%s" %
              (right_motor, self.channels[1], right_inverted))

    def stop_all(self):
        self.current = (0, 0)
        error = None
        for pwm, in1, in2 in CHANNELS.values():
            for channel in (pwm, in1, in2):
                try:
                    self.pwm.set_percent(channel, 0)
                except OSError as exc:
                    error = exc
        if error:
            print("[Моторы] Ошибка выключения по I²C:", error)
            raise error

    def set_tracks(self, left, right):
        """Задать оба мотора без ожидания; при сбое I²C попытаться выключить все."""
        for value in (left, right):
            if type(value) is not int or not -100 <= value <= 100:
                raise ValueError("track PWM must be integer percent")
        values = (left, right)
        try:
            # До смены направления снимаем PWM сразу с обеих сторон.
            for pwm, _, _ in self.channels:
                self.pwm.set_percent(pwm, 0)
            for index, ((_, in1, in2), value) in enumerate(zip(self.channels, values)):
                direction = -value if self.inverted[index] else value
                self.pwm.set_percent(in1, 100 if direction > 0 else 0)
                self.pwm.set_percent(in2, 100 if direction < 0 else 0)
            for (pwm, _, _), value in zip(self.channels, values):
                self.pwm.set_percent(pwm, abs(value))
            self.current = values
        except OSError as exc:
            try:
                self.stop_all()
            finally:
                self.current = (0, 0)
                print("[Моторы] Ошибка I²C при задании PWM %s: %s" % (values, exc))
            raise
