"""Неизменяемые данные, которыми обмениваются модули Pi."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Frame:
    frame_id: int
    captured_at_ns: int
    image: Any = field(compare=False, repr=False)


@dataclass(frozen=True)
class DetectionBatch:
    frame_id: int
    captured_at_ns: int
    decoded_at_ns: int
    payloads: tuple[str, ...]


@dataclass(frozen=True)
class Action:
    action: str
    pwm_pct: int | None = None
    duration_ms: int | None = None
    profile: str | None = None


@dataclass(frozen=True)
class CardCommand:
    card_id: str
    action: str
    steps: tuple[Action, ...]
    content_hash: str


@dataclass(frozen=True)
class MotionStep:
    left_pwm_pct: int
    right_pwm_pct: int
    duration_ms: int


@dataclass(frozen=True)
class MotionPlan:
    plan_id: str
    source: str
    source_id: str
    steps: tuple[MotionStep, ...]
    total_duration_ms: int
    calibration_id: str | None = None


@dataclass(frozen=True)
class ControlRequest:
    request_id: str
    source: str
    operation: str
    params: dict[str, Any]
    received_at_ns: int
    expected_revision: int | None = None


@dataclass(frozen=True)
class ExecutionEvent:
    session_id: str
    cmd_id: int
    kind: str
    reason: str


@dataclass(frozen=True)
class RobotStatus:
    mode: str | None
    state: str
    armed: bool
    control_revision: int
    plan_id: str | None
    step_index: int | None
    cmd_id: int | None
    camera_healthy: bool
    link_healthy: bool
    outputs_confirmed_off: bool
    stop_reason: str | None
    service_running: bool
    hardware_ready: bool
    executing: bool
    pico_reply_age_ms: int | None
