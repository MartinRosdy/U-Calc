"""Production preflight command that never connects to Telegram."""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from importlib.metadata import version

from .backup import verify_database
from .catalog import CATALOG_VERSION, ENGINE_VERSION
from .config import Settings
from .locking import single_instance_lock
from .storage import NORMS_VERSION, SCHEMA_VERSION, CalculationRepository


@dataclass(frozen=True, slots=True)
class DoctorResult:
    application_version: str
    engine_version: str
    catalog_version: str
    norms_version: str
    schema_version: int
    integrity: str
    allowlist_size: int


def check_installation(settings: Settings) -> DoctorResult:
    """Validate production configuration and SQLite without Telegram networking."""
    # Resolve the timezone now, rather than relying only on the name validation in from_env.
    _ = settings.timezone
    application_version = version("u-calc")
    if application_version != ENGINE_VERSION:
        raise RuntimeError(
            "Версия установленного U-Calc не совпадает с расчётным движком: "
            f"app={application_version}, engine={ENGINE_VERSION}"
        )
    with single_instance_lock(settings.database_path):
        repository = CalculationRepository(settings.database_path)
        repository.initialize()
        schema_version, integrity = verify_database(settings.database_path)
    if schema_version != SCHEMA_VERSION:
        raise RuntimeError(
            f"После миграции ожидалась schema v{SCHEMA_VERSION}, получена v{schema_version}"
        )
    return DoctorResult(
        application_version=application_version,
        engine_version=ENGINE_VERSION,
        catalog_version=CATALOG_VERSION,
        norms_version=NORMS_VERSION,
        schema_version=schema_version,
        integrity=integrity,
        allowlist_size=len(settings.allowed_user_ids),
    )


def main() -> None:
    try:
        settings = Settings.from_env()
        result = check_installation(settings)
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        print(f"U-Calc doctor: ERROR — {exc}", file=sys.stderr)
        raise SystemExit(2) from None

    access = (
        f"allowlist ({result.allowlist_size} users)"
        if result.allowlist_size
        else "public with rate limits"
    )
    print("U-Calc doctor: OK")
    print("BOT_TOKEN: configured (value is never displayed)")
    print(
        f"Version: app {result.application_version}; engine {result.engine_version}; "
        f"catalog {result.catalog_version}"
    )
    print(f"Norms: {result.norms_version}")
    print(f"SQLite: {settings.database_path.resolve()}")
    print(f"Integrity: {result.integrity}; schema v{result.schema_version}")
    print(f"Timezone: {settings.app_timezone}")
    print(f"Access: {access}")
    print(
        f"Limits: {settings.rate_limit_per_minute} actions/min; "
        f"{settings.global_rate_limit_per_minute} global actions/min; "
        f"{settings.calculation_rate_limit_per_minute} calculations/min; "
        f"{settings.max_message_length} chars/message"
    )
    print(
        f"Retention: calculations {settings.history_retention_days} days; "
        f"drafts {settings.draft_ttl_days} days"
    )


if __name__ == "__main__":
    main()
