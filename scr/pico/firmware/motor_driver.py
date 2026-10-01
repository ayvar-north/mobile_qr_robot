"""Signed track PWM. Positive is forward relative to the chassis."""


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
        self.stop_all()  # Also disables unused terminals at startup.

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
            raise error

    def set_tracks(self, left, right):
        for value in (left, right):
            if type(value) is not int or not -100 <= value <= 100:
                raise ValueError("track PWM must be integer percent")
        values = (left, right)
        try:
            # Drop both enables before changing any direction.
            for pwm, _, _ in self.channels:
                self.pwm.set_percent(pwm, 0)
            for index, ((_, in1, in2), value) in enumerate(zip(self.channels, values)):
                direction = -value if self.inverted[index] else value
                self.pwm.set_percent(in1, 100 if direction > 0 else 0)
                self.pwm.set_percent(in2, 100 if direction < 0 else 0)
            for (pwm, _, _), value in zip(self.channels, values):
                self.pwm.set_percent(pwm, abs(value))
            self.current = values
        except OSError:
            try:
                self.stop_all()
            finally:
                self.current = (0, 0)
            raise
