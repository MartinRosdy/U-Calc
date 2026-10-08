from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VALID_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str = field(repr=False)
    database_path: Path = Path("data/u_calc.db")
    log_level: str = "INFO"
    app_timezone: str = "Asia/Tashkent"
    allowed_user_ids: frozenset[int] = frozenset()
    rate_limit_per_minute: int = 30
    calculation_rate_limit_per_minute: int = 6
    max_message_length: int = 4096
    history_retention_days: int = 730
    draft_ttl_days: int = 30

    @classmethod
    def from_env(cls) -> Settings:
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("Не задан BOT_TOKEN. Передайте токен через переменную окружения.")

        database_path = Path(os.getenv("DATABASE_PATH", "data/u_calc.db").strip())
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in VALID_LOG_LEVELS:
            allowed = ", ".join(sorted(VALID_LOG_LEVELS))
            raise RuntimeError(f"Некорректный LOG_LEVEL. Допустимо: {allowed}")

        timezone_name = os.getenv("APP_TIMEZONE", "Asia/Tashkent").strip()
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise RuntimeError(f"Неизвестный APP_TIMEZONE: {timezone_name}") from exc

        allowed_user_ids = _parse_user_ids(os.getenv("ALLOWED_USER_IDS", ""))
        rate_limit = _bounded_int("RATE_LIMIT_PER_MINUTE", 30, 5, 300)
        calculation_rate_limit = _bounded_int("CALCULATION_RATE_LIMIT_PER_MINUTE", 6, 1, 60)
        max_message_length = _bounded_int("MAX_MESSAGE_LENGTH", 4096, 100, 4096)
        history_retention_days = _bounded_int("HISTORY_RETENTION_DAYS", 730, 1, 3650)
        draft_ttl_days = _bounded_int("DRAFT_TTL_DAYS", 30, 1, 365)
        return cls(
            bot_token=token,
            database_path=database_path,
            log_level=log_level,
            app_timezone=timezone_name,
            allowed_user_ids=allowed_user_ids,
            rate_limit_per_minute=rate_limit,
            calculation_rate_limit_per_minute=calculation_rate_limit,
            max_message_length=max_message_length,
            history_retention_days=history_retention_days,
            draft_ttl_days=draft_ttl_days,
        )

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def logging_level(self) -> int:
        return getattr(logging, self.log_level)

    def is_user_allowed(self, telegram_user_id: int) -> bool:
        return not self.allowed_user_ids or telegram_user_id in self.allowed_user_ids


def _parse_user_ids(raw: str) -> frozenset[int]:
    if not raw.strip():
        return frozenset()
    result: set[int] = set()
    for item in raw.split(","):
        value = item.strip()
        if not value.isdigit() or int(value) <= 0:
            raise RuntimeError(
                "ALLOWED_USER_IDS должен быть списком положительных Telegram ID через запятую"
            )
        result.add(int(value))
    return frozenset(result)


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} должен быть целым числом") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} должен быть от {minimum} до {maximum}")
    return value
