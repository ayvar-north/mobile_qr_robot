"""Конечный шаг движения без долгого sleep; время задаёт вызывающий код."""


class Motion:
    def __init__(self, driver, ticks_diff, deadtime_ms, ramp_pct_per_s):
        self.driver = driver
        self.diff = ticks_diff
        self.deadtime_ms = deadtime_ms
        self.ramp = ramp_pct_per_s
        self.active = None
        self.current = (0, 0)
        self.last_direction = (0, 0)

    def start(self, left, right, duration_ms, now):
        if self.active is not None:
            raise ValueError("busy")
        if type(duration_ms) is not int or duration_ms < 1:
            raise ValueError("duration_ms")
        target = (left, right)
        reverse = any(a and b and (a > 0) != (b > 0)
                      for a, b in zip(self.last_direction, target))
        self.active = {"start": now, "last": now, "duration": duration_ms,
                       "target": target,
                       "wait_since": now if reverse else None}
        self.tick(now)

    def tick(self, now):
        """Один короткий такт: срок шага, пауза реверса и плавный разгон."""
        step = self.active
        if step is None:
            return None
        elapsed = max(0, self.diff(now, step["start"]))
        if elapsed >= step["duration"]:
            self.cancel()
            return ("completed", elapsed)
        dt = max(0, self.diff(now, step["last"]))
        step["last"] = now
        target = step["target"]
        reversal = any(a and b and (a > 0) != (b > 0)
                       for a, b in zip(self.current, target))
        if reversal:
            self.driver.set_tracks(0, 0)
            self.current = (0, 0)
            step["wait_since"] = now
            return None
        if step["wait_since"] is not None:
            if self.diff(now, step["wait_since"]) < self.deadtime_ms:
                return None
            step["wait_since"] = None
        change = max(1, self.ramp * dt // 1000) if dt else 0
        next_values = tuple(max(a - change, min(a + change, b))
                            for a, b in zip(self.current, target))
        if next_values != self.current:
            self.driver.set_tracks(*next_values)
            self.current = next_values
        return None

    def cancel(self):
        self.active = None
        self.last_direction = tuple(1 if value > 0 else -1 if value < 0 else old
                                    for value, old in zip(self.current, self.last_direction))
        self.current = (0, 0)
        self.driver.stop_all()
