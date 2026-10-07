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
        return cls(
            bot_token=token,
            database_path=database_path,
            log_level=log_level,
            app_timezone=timezone_name,
            allowed_user_ids=allowed_user_ids,
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
