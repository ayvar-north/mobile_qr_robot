"""Загрузка настроек без открытия устройств и без побочных действий."""

import json
from dataclasses import dataclass
from pathlib import Path


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("повторяющийся ключ конфигурации")
        result[key] = value
    return result


def _int(value, minimum, maximum, name):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name}: требуется целое число {minimum}..{maximum}")
    return value


@dataclass(frozen=True)
class TurnProfile:
    profile_id: str
    direction: str
    pwm_pct: int
    duration_ms: int
    verified: bool
    tested_at: str
    conditions: str


@dataclass(frozen=True)
class RobotConfig:
    dry_run: bool
    uart_path: str | None
    camera_path: str | None
    socket_path: str
    max_pwm_pct: int
    max_step_ms: int
    max_plan_ms: int
    manual_max_ms: int
    camera_width: int
    camera_height: int
    camera_fps: int
    profiles: tuple[TurnProfile, ...]
    hardware_verified: bool


def load(path: str | Path) -> RobotConfig:
    """Отклонить неизвестные ключи и не заменять неизвестное железо догадками."""
    data = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    allowed = {"version", "dry_run", "uart_path", "camera_path", "socket_path",
               "max_pwm_pct", "max_step_ms", "max_plan_ms", "manual_max_ms",
               "camera_width", "camera_height", "camera_fps", "turn_profiles",
               "hardware_verified"}
    if type(data) is not dict or set(data) != allowed or type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("неверная версия или набор полей конфигурации")
    if type(data["dry_run"]) is not bool or type(data["hardware_verified"]) is not bool:
        raise ValueError("dry_run/hardware_verified должны быть bool")
    for name in ("uart_path", "camera_path"):
        if data[name] is not None and (type(data[name]) is not str or not data[name].startswith("/dev/")):
            raise ValueError(f"{name}: требуется путь /dev/... или null")
    if not data["dry_run"] and (not data["hardware_verified"] or not data["uart_path"]):
        raise ValueError("аппаратный запуск требует подтверждённого паспорта и UART")
    if type(data["socket_path"]) is not str or not data["socket_path"].startswith("/"):
        raise ValueError("socket_path должен быть абсолютным")
    profiles = []
    if type(data["turn_profiles"]) is not list:
        raise ValueError("turn_profiles должен быть списком")
    for item in data["turn_profiles"]:
        if type(item) is not dict or set(item) != {"profile_id", "direction", "pwm_pct", "duration_ms", "verified", "tested_at", "conditions"}:
            raise ValueError("неверный профиль разворота")
        if (type(item["profile_id"]) is not str or not item["profile_id"] or
                item["direction"] not in ("left", "right") or type(item["verified"]) is not bool or
                type(item["tested_at"]) is not str or type(item["conditions"]) is not str):
            raise ValueError("неверные поля профиля")
        if item["verified"] and (not item["tested_at"] or not item["conditions"]):
            raise ValueError("подтверждённому профилю нужны дата и условия проверки")
        profiles.append(TurnProfile(item["profile_id"], item["direction"],
                                    _int(item["pwm_pct"], 1, 100, "pwm_pct"),
                                    _int(item["duration_ms"], 1, 2000, "duration_ms"),
                                    item["verified"], item["tested_at"], item["conditions"]))
    if len({p.profile_id for p in profiles}) != len(profiles):
        raise ValueError("повторяющийся profile_id")
    return RobotConfig(data["dry_run"], data["uart_path"], data["camera_path"],
                       data["socket_path"], _int(data["max_pwm_pct"], 1, 100, "max_pwm_pct"),
                       _int(data["max_step_ms"], 1, 2000, "max_step_ms"),
                       _int(data["max_plan_ms"], 1, 20000, "max_plan_ms"),
                       _int(data["manual_max_ms"], 1, 300, "manual_max_ms"),
                       _int(data["camera_width"], 1, 4096, "camera_width"),
                       _int(data["camera_height"], 1, 4096, "camera_height"),
                       _int(data["camera_fps"], 1, 120, "camera_fps"), tuple(profiles),
                       data["hardware_verified"])
