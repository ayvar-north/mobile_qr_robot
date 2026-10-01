"""Чистое преобразование проверенной команды в план PWM/время."""

from uuid import uuid4

from robot.config import RobotConfig
from robot.types import Action, CardCommand, MotionPlan, MotionStep


def _step(action: Action, config: RobotConfig) -> tuple[MotionStep, str | None]:
    if action.action == "turn_around":
        profile = next((p for p in config.profiles if p.profile_id == action.profile), None)
        if profile is None or not profile.verified:
            raise ValueError("профиль разворота не проверен")
        pwm, duration = profile.pwm_pct, profile.duration_ms
        name = "turn_left" if profile.direction == "left" else "turn_right"
        calibration_id = profile.profile_id
    else:
        pwm, duration, name = action.pwm_pct, action.duration_ms, action.action
        calibration_id = None
    if type(pwm) is not int or type(duration) is not int or not 1 <= pwm <= config.max_pwm_pct or not 1 <= duration <= config.max_step_ms:
        raise ValueError("шаг превышает пределы")
    signs = {"forward": (1, 1), "backward": (-1, -1), "turn_left": (-1, 1), "turn_right": (1, -1)}
    left, right = signs[name]
    return MotionStep(left * pwm, right * pwm, duration), calibration_id


def build(actions: tuple[Action, ...], source: str, source_id: str, config: RobotConfig,
          pico_max_pwm: int, pico_max_step_ms: int) -> MotionPlan:
    """Собрать и проверить весь план до первой отправки MOVE."""
    if not 1 <= len(actions) <= 10:
        raise ValueError("число шагов вне предела")
    pairs = tuple(_step(item, config) for item in actions)
    steps = tuple(pair[0] for pair in pairs)
    if any(max(abs(s.left_pwm_pct), abs(s.right_pwm_pct)) > pico_max_pwm or s.duration_ms > pico_max_step_ms for s in steps):
        raise ValueError("план превышает пределы Pico")
    total = sum(s.duration_ms for s in steps)
    if total > config.max_plan_ms:
        raise ValueError("план слишком длинный")
    if source == "manual" and (len(steps) != 1 or total > config.manual_max_ms):
        raise ValueError("ручной импульс слишком длинный")
    ids = [item[1] for item in pairs if item[1] is not None]
    return MotionPlan(uuid4().hex, source, source_id, steps, total, ids[0] if ids else None)


def from_card(card: CardCommand, config: RobotConfig, pico_max_pwm: int,
              pico_max_step_ms: int) -> MotionPlan:
    if card.action == "stop":
        raise ValueError("STOP не является маршрутом")
    return build(card.steps, "qr", card.card_id, config, pico_max_pwm, pico_max_step_ms)
