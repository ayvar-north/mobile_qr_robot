"""Pico session, movement and heartbeat state machine."""

from protocol import ZERO_SESSION, encode, integer


class Controller:
    def __init__(self, motion, ticks_diff, boot_counter, max_pwm=30,
                 max_step_ms=2000, hb_timeout_ms=500):
        self.motion = motion
        self.diff = ticks_diff
        self.boot_counter = boot_counter
        self.max_pwm = max_pwm
        self.max_step_ms = max_step_ms
        self.hb_timeout_ms = hb_timeout_ms
        self.state = "DISARMED"
        self.fault = "none"
        self.session = None
        self.nonce = None
        self.handshake_counter = 0
        self.revoked = True
        self.hb_at = None
        self.max_seq = 0
        self.cache = []
        self.move_record = None
        self.active = None

    def _answer(self, kind, seq, payload, session=None):
        return encode(kind, session or self.session or ZERO_SESSION, seq, payload)

    def _remember(self, seq, request, responses):
        record = (seq, request, responses)
        self.cache.append(record)
        if len(self.cache) > 16:
            self.cache.pop(0)
        self.max_seq = max(self.max_seq, seq)
        return responses

    def _error(self, seq, code, request=None):
        response = [self._answer("ERROR", seq, code)]
        return self._remember(seq, request, response) if request is not None else response

    def _stop(self, reason, now):
        active = self.active
        self.active = None
        self.revoked = True
        self.hb_at = None
        try:
            self.motion.cancel()
            if self.state != "FAULT":
                self.state = "DISARMED"
        except OSError:
            self.state = "FAULT"
            self.fault = "DRIVER_FAULT"
        responses = []
        if active is not None:
            seq, started = active
            elapsed = max(0, self.diff(now, started))
            answer = self._answer("DONE", seq, "%s,%d" % (reason, elapsed)) if self.state != "FAULT" else self._answer("DONE", seq, "driver_error,%d" % elapsed)
            if self.move_record is not None:
                self.move_record[2][:] = [answer]
            responses.append(answer)
        return responses

    def tick(self, now):
        responses = []
        if self.state in ("ARMED_IDLE", "MOVING") and self.diff(now, self.hb_at) >= self.hb_timeout_ms:
            responses.extend(self._stop("link_timeout", now))
        if self.state == "MOVING":
            try:
                done = self.motion.tick(now)
            except OSError:
                responses.extend(self._stop("driver_error", now))
                self.state = "FAULT"
                self.fault = "DRIVER_FAULT"
                return responses
            if done:
                seq, _ = self.active
                self.active = None
                self.state = "ARMED_IDLE"
                answer = self._answer("DONE", seq, "%s,%d" % done)
                self.move_record[2][:] = [answer]
                responses.append(answer)
        return responses

    def handle(self, request, now):
        kind, session, seq, payload = request
        if kind == "STOP":
            responses = self._stop("stopped", now)
            if self.state == "FAULT":
                responses.append(self._answer("ERROR", seq, "DRIVER_FAULT", session))
            else:
                responses.append(self._answer("ACK", seq, "STOP", session))
            return responses
        if kind == "HELLO":
            if self.state == "FAULT":
                return [self._answer("ERROR", 0, self.fault, ZERO_SESSION)]
            if payload != self.nonce or self.revoked:
                responses = self._stop("session_replaced", now)
                if self.handshake_counter == 0xffffffff:
                    self.state = "FAULT"
                    self.fault = "BOOT_COUNTER_FAULT"
                    return responses + [self._answer("ERROR", 0, self.fault, ZERO_SESSION)]
                self.handshake_counter += 1
                self.nonce = payload
                self.session = "%s%08x%08x" % (payload, self.boot_counter, self.handshake_counter)
                self.revoked = False
                self.max_seq = 0
                self.cache = []
                self.move_record = None
            else:
                responses = []
            responses.append(self._answer("READY", 0, "DISARMED,%d,%d,%d" %
                                          (self.max_pwm, self.max_step_ms, self.hb_timeout_ms)))
            return responses
        if session != self.session or self.revoked:
            if kind == "STATUS" and session == self.session:
                return [self._state(seq, now)]
            return [self._answer("ERROR", seq, "BAD_SESSION", session)]
        request_key = (kind, payload)
        if self.move_record is not None and seq == self.move_record[0]:
            if request_key != self.move_record[1]:
                return [self._answer("ERROR", seq, "ID_CONFLICT")]
            return self.move_record[2][:]
        for old_seq, old_request, responses in self.cache:
            if seq == old_seq:
                if request_key != old_request:
                    return [self._answer("ERROR", seq, "ID_CONFLICT")]
                return responses[:]
        if seq <= self.max_seq:
            return [self._answer("ERROR", seq, "STALE_ID")]
        if kind == "STATUS":
            return self._remember(seq, request_key, [self._state(seq, now)])
        if self.state == "FAULT":
            return self._error(seq, "DRIVER_FAULT", request_key)
        if kind == "ARM":
            if self.state != "DISARMED":
                return self._error(seq, "BUSY", request_key)
            self.state = "ARMED_IDLE"
            self.hb_at = now
            return self._remember(seq, request_key, [self._answer("ACK", seq, "ARM")])
        if kind == "HEARTBEAT":
            if self.state not in ("ARMED_IDLE", "MOVING"):
                return self._error(seq, "NOT_ARMED", request_key)
            self.hb_at = now
            return self._remember(seq, request_key, [self._answer("ACK", seq, "HEARTBEAT")])
        if kind == "MOVE":
            if self.state == "MOVING":
                return self._error(seq, "BUSY", request_key)
            if self.state != "ARMED_IDLE":
                return self._error(seq, "NOT_ARMED", request_key)
            left, right, duration = (integer(item, i < 2) for i, item in enumerate(payload.split(",")))
            if (abs(left) > self.max_pwm or abs(right) > self.max_pwm or
                    duration > self.max_step_ms or (left == 0 and right == 0)):
                return self._error(seq, "OUT_OF_RANGE", request_key)
            try:
                self.motion.start(left, right, duration, now)
            except OSError:
                self._stop("driver_error", now)
                self.state = "FAULT"
                self.fault = "DRIVER_FAULT"
                return self._error(seq, "DRIVER_FAULT", request_key)
            response = [self._answer("ACK", seq, "MOVE")]
            self.active = (seq, now)
            self.move_record = (seq, request_key, response)
            self.state = "MOVING"
            return self._remember(seq, request_key, response)
        return self._error(seq, "BAD_MESSAGE", request_key)

    def _state(self, seq, now):
        if self.active is None:
            active, left, right, remaining = 0, 0, 0, 0
        else:
            active = self.active[0]
            left, right = self.motion.active["target"]
            remaining = max(0, self.motion.active["duration"] -
                            max(0, self.diff(now, self.motion.active["start"])))
        return self._answer("STATE", seq, "%s,%d,%d,%d,%d,%s" %
                            (self.state, active, left, right, remaining, self.fault))
