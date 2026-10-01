"""Единая точка запросов: режим, разрешение, STOP и ревизия состояния."""

import asyncio
import time
from collections import OrderedDict
from dataclasses import asdict

from robot.execution import PlanExecutor
from robot.planning import build, from_card
from robot.qr.gate import CardGate
from robot.transport.serial_client import LinkFault
from robot.types import Action, ControlRequest, RobotStatus


class Controller:
    def __init__(self, config, link, supervisor, telemetry):
        self.config, self.link = config, link
        self.supervisor, self.telemetry = supervisor, telemetry
        self.gate = CardGate(config.max_pwm_pct, config.max_step_ms)
        self.executor = PlanExecutor(link, self._plan_finished)
        self.mode = None
        self.state = "BOOTING"
        self.armed = False
        self.revision = 0
        self.stop_reason = None
        self.outputs_confirmed_off = False
        self.off_confirmed_at_ns = None
        self.hardware_ready = False
        self.camera_healthy = False
        self.link_healthy = False
        self.arm_task = None
        self.stop_task = None
        self.heartbeat_task = None
        self.last_heartbeat_ns = 0
        self.requests = OrderedDict()
        self.closing = False

    def status(self):
        plan, step, cmd = self.executor.snapshot()
        now = time.monotonic_ns()
        last_rx = getattr(self.link, "last_rx_ns", None)
        age_ms = (now - last_rx) // 1_000_000 if last_rx is not None else None
        off_fresh = (self.off_confirmed_at_ns is not None and
                     now - self.off_confirmed_at_ns <= 1_000_000_000 and
                     getattr(self.link, "fault", None) is None)
        return RobotStatus(self.mode, self.state, self.armed, self.revision,
                           plan.plan_id if plan else None, step, cmd,
                           self.camera_healthy, self.link_healthy,
                           self.outputs_confirmed_off and off_fresh, self.stop_reason,
                           True, self.hardware_ready, self.state == "EXECUTING", age_ms)

    def _result(self, request_id, accepted, code, plan_id=None):
        return {"request_id": request_id, "accepted": accepted, "code": code,
                "control_revision": self.revision, "status": asdict(self.status()),
                "metrics": dict(self.telemetry.counters), "plan_id": plan_id}

    async def initialize(self):
        self.state = "WAIT_HARDWARE"
        revision = self.revision
        try:
            await self.link.handshake()
            # STOP, принятый во время HELLO, нельзя затереть поздним READY.
            if revision != self.revision or self.state != "WAIT_HARDWARE":
                return
            self.link_healthy = True
            self.hardware_ready = True
            self.outputs_confirmed_off = True
            self.off_confirmed_at_ns = time.monotonic_ns()
            self.state = "WAIT_START"
        except Exception as exc:
            if revision == self.revision:
                self.link_healthy = False
                self.stop_reason = str(exc)

    async def handle(self, request: ControlRequest):
        if request.operation == "status":
            return self._result(request.request_id, True, "OK")
        if self.closing:
            return self._result(request.request_id, False, "SHUTTING_DOWN")
        identity = (request.source, request.operation, tuple(sorted(request.params.items())), request.expected_revision)
        previous = self.requests.get(request.request_id)
        if previous is not None:
            old_identity, old_result = previous
            return old_result if identity == old_identity else self._result(request.request_id, False, "ID_CONFLICT")
        if request.operation == "stop":
            # Запрет ставится синхронно до первого await.
            self.revision += 1
            self.state = "STOPPING"
            self.armed = False
            self.outputs_confirmed_off = False
            self.stop_reason = "user"
            self._start_stop("user")
            result = self._result(request.request_id, True, "STOPPING")
        elif request.expected_revision != self.revision:
            result = self._result(request.request_id, False, "STALE_REVISION")
        elif request.operation == "start":
            mode = request.params["mode"].upper()
            if self.state not in ("WAIT_START", "STOPPED", "FAULT"):
                result = self._result(request.request_id, False, "BUSY")
            elif mode == "QR" and not self.camera_healthy:
                result = self._result(request.request_id, False, "CAMERA_UNAVAILABLE")
            elif self.stop_task is not None and not self.stop_task.done():
                result = self._result(request.request_id, False, "STOPPING")
            else:
                self.mode = mode
                self.state = "ARMING"
                self.armed = False
                self.outputs_confirmed_off = False
                self.gate.reset_for_start()
                self.arm_task = asyncio.create_task(self._arm(self.revision))
                result = self._result(request.request_id, True, "ARMING")
        elif request.operation == "move":
            if self.state == "EXECUTING":
                result = self._result(request.request_id, False, "BUSY")
            elif self.state != "READY" or self.mode != "MANUAL":
                result = self._result(request.request_id, False, "NOT_READY")
            else:
                try:
                    action = Action(request.params["action"], request.params["pwm_pct"], request.params["duration_ms"])
                    plan = build((action,), "manual", request.request_id, self.config,
                                 self.link.max_pwm, self.link.max_step_ms)
                    self.executor.submit(plan)
                    self.state = "EXECUTING"
                    self.outputs_confirmed_off = False
                    result = self._result(request.request_id, True, "EXECUTING", plan.plan_id)
                except (ValueError, KeyError) as exc:
                    result = self._result(request.request_id, False, str(exc))
        else:
            result = self._result(request.request_id, False, "BAD_OPERATION")
        self.requests[request.request_id] = (identity, result)
        if len(self.requests) > 64:
            self.requests.popitem(last=False)
        return result

    async def _arm(self, revision):
        try:
            await self.link.handshake()
            if revision != self.revision or self.state != "ARMING":
                return
            self._check_camera_before_arm()
            await self.link.arm()
            if revision != self.revision or self.state != "ARMING":
                return
            self._check_camera_before_arm()
            # Чистое поле отсчитывается после разрешения, а не во время HELLO.
            self.gate.reset_for_start(time.monotonic_ns())
            self.link_healthy = True
            self.hardware_ready = True
            self.armed = True
            self.state = "READY"
            self.telemetry.record("controller", "armed", mode=self.mode)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if revision == self.revision:
                self.fault(str(exc))

    def _check_camera_before_arm(self):
        if self.mode == "QR":
            stamp = self.supervisor.vision_at
            if not self.camera_healthy or stamp is None or time.monotonic_ns() - stamp > 500_000_000:
                raise LinkFault("камера недоступна при ARM")

    def _start_stop(self, reason):
        # Запретить следующий MOVE сразу, до запуска асинхронной отправки STOP.
        self.executor.generation += 1
        if self.arm_task is not None and not self.arm_task.done():
            self.arm_task.cancel()
        if self.heartbeat_task is not None and not self.heartbeat_task.done():
            self.heartbeat_task.cancel()
        if self.stop_task is None or self.stop_task.done():
            self.stop_task = asyncio.create_task(self._stop(reason))

    async def _stop(self, reason):
        await self.executor.cancel()
        try:
            await self.link.stop(reason)
            self.outputs_confirmed_off = True
            self.off_confirmed_at_ns = time.monotonic_ns()
            # Подтверждение выключения выходов не устраняет причину аварии.
            self.state = "FAULT" if reason == "fault" else "STOPPED"
        except Exception as exc:
            self.outputs_confirmed_off = False
            self.state = "FAULT"
            self.stop_reason = f"STOP: {exc}"
        self.telemetry.record("controller", "stopped", reason=self.stop_reason,
                              confirmed=self.outputs_confirmed_off)

    def fault(self, reason):
        if self.state in ("STOPPING", "STOPPED", "FAULT"):
            return
        self.revision += 1
        self.armed = False
        self.state = "STOPPING"
        self.outputs_confirmed_off = False
        self.stop_reason = reason
        self.telemetry.counters["cancellations"] += 1
        if "тайм-аут" in reason or "timeout" in reason.lower():
            self.telemetry.counters["timeouts"] += 1
        self._start_stop("fault")

    def _plan_finished(self, error):
        if self.state != "EXECUTING":
            return
        if error:
            self.fault(error)
        else:
            self.state = "READY"
            self.outputs_confirmed_off = True
            self.off_confirmed_at_ns = time.monotonic_ns()
            self.telemetry.record("execution", "plan_completed")

    def observe(self, batch):
        now = time.monotonic_ns()
        if (now - batch.decoded_at_ns > 500_000_000 or
                now - batch.captured_at_ns > 500_000_000 or
                batch.decoded_at_ns < batch.captured_at_ns):
            return
        self.supervisor.mark_vision(batch.captured_at_ns)
        self.camera_healthy = True
        event = self.gate.observe(batch, self.state == "EXECUTING", now)
        if event is None:
            return
        if event.kind == "stop":
            self.revision += 1
            self.armed = False
            self.state = "STOPPING"
            self.outputs_confirmed_off = False
            self.stop_reason = "qr"
            self._start_stop("qr")
        elif event.kind in ("ambiguous", "id_conflict") and self.mode == "QR" and self.state in ("READY", "EXECUTING"):
            self.fault(event.kind)
        elif event.kind == "card" and self.mode == "QR" and self.state == "READY":
            try:
                plan = from_card(event.card, self.config, self.link.max_pwm, self.link.max_step_ms)
                self.executor.submit(plan)
                self.state = "EXECUTING"
                self.outputs_confirmed_off = False
            except ValueError as exc:
                self.telemetry.record("qr", "rejected", reason=str(exc))

    def tick(self):
        now = time.monotonic_ns()
        progress_healthy = self.supervisor.healthy(self.mode == "QR", now)
        self.supervisor.mark_control(now)
        if self.state != "EXECUTING" or (self.executor.task is not None and not self.executor.task.done()):
            self.supervisor.mark_execution(now)
        self.link_healthy = self.link.fault is None and self.link.session is not None
        if self.link.fault is not None:
            self.hardware_ready = False
        if self.state not in ("READY", "EXECUTING"):
            return
        if not self.link_healthy or not progress_healthy:
            self.fault("потеря связи или свежести зрения")
            return
        if now - self.last_heartbeat_ns >= 100_000_000:
            self.last_heartbeat_ns = now
            if self.heartbeat_task is None or self.heartbeat_task.done():
                self.heartbeat_task = asyncio.create_task(self._heartbeat())

    async def _heartbeat(self):
        try:
            await self.link.heartbeat()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.fault(str(exc))
