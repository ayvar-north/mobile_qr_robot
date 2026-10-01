"""Строгая схема QR v1: карточка содержит только разрешённые данные."""

import hashlib
import json
import re

from robot.types import Action, CardCommand


class QrRejected(ValueError):
    """Данные карточки не прошли проверку."""


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise QrRejected("повторяющийся ключ")
        result[key] = value
    return result


def _action(obj, max_pwm, max_step):
    if type(obj) is not dict or "action" not in obj:
        raise QrRejected("отсутствует action")
    name = obj["action"]
    if name in ("forward", "backward", "turn_left", "turn_right"):
        if set(obj) != {"action", "pwm_pct", "duration_ms"}:
            raise QrRejected("неверные поля движения")
        pwm, duration = obj["pwm_pct"], obj["duration_ms"]
        if type(pwm) is not int or type(duration) is not int or not 1 <= pwm <= max_pwm or not 1 <= duration <= max_step:
            raise QrRejected("PWM или длительность вне пределов")
        return Action(name, pwm, duration)
    if name == "turn_around":
        if set(obj) != {"action", "profile"} or type(obj["profile"]) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", obj["profile"]):
            raise QrRejected("неверный профиль")
        return Action(name, profile=obj["profile"])
    raise QrRejected("неизвестное действие")


def parse(text: str, max_pwm: int = 30, max_step_ms: int = 2000) -> CardCommand:
    """Проверить весь маршрут до возвращения хотя бы одного шага."""
    if type(text) is not str or len(text.encode("utf-8")) > 1024:
        raise QrRejected("слишком длинный QR")
    try:
        obj = json.loads(text, object_pairs_hook=_pairs)
    except (ValueError, TypeError) as exc:
        raise QrRejected("неверный JSON") from exc
    if type(obj) is not dict or obj.get("schema") != "qr-robot" or type(obj.get("v")) is not int or obj["v"] != 1:
        raise QrRejected("неверная схема или версия")
    card_id = obj.get("card_id")
    if type(card_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", card_id):
        raise QrRejected("неверный card_id")
    name = obj.get("action")
    if name == "stop":
        if set(obj) != {"schema", "v", "card_id", "action"}:
            raise QrRejected("у STOP нет параметров")
        steps = ()
    elif name == "route":
        if set(obj) != {"schema", "v", "card_id", "action", "steps"} or type(obj["steps"]) is not list or not 1 <= len(obj["steps"]) <= 10:
            raise QrRejected("неверный маршрут")
        steps = tuple(_action(step, max_pwm, max_step_ms) for step in obj["steps"])
    else:
        if set(obj) - {"schema", "v", "card_id"} not in ({"action", "pwm_pct", "duration_ms"}, {"action", "profile"}):
            raise QrRejected("неверные поля карточки")
        steps = (_action({key: value for key, value in obj.items() if key not in ("schema", "v", "card_id")}, max_pwm, max_step_ms),)
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return CardCommand(card_id, name, steps, hashlib.sha256(canonical.encode("utf-8")).hexdigest())
