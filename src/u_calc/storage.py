import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .catalog import CATALOG_VERSION, ENGINE_VERSION

SCHEMA_VERSION = 6
DRAFT_FORMAT_VERSION = 1
NORMS_VERSION = "ШНҚ 2.04.05-22 (ред. 07.07.2026)"


@dataclass(frozen=True, slots=True)
class SavedCalculation:
    id: int
    created_at: str
    total_kw: float
    recommended_kw: float
    climate_key: str
    building_type: str
    report: str
    engine_version: str
    catalog_version: str
    answers: dict[str, Any]
    object_name: str
    calculation_version: int
    status: str
    updated_at: str
    parent_id: int | None
    norms_version: str


@dataclass(frozen=True, slots=True)
class CalculationDraft:
    telegram_user_id: int
    current_step: str
    data: dict[str, Any]
    created_at: str
    updated_at: str
    format_version: int
    expires_at: str


@dataclass(frozen=True, slots=True)
class UserSettings:
    telegram_user_id: int
    locale: str
    default_profile_id: int | None
    prepared_by: str


@dataclass(frozen=True, slots=True)
class CalculationProfile:
    id: int
    telegram_user_id: int
    name: str
    settings: dict[str, Any]
    version: int
    is_default: bool
    created_at: str
    updated_at: str


class CalculationRepository:
    """Small SQLite repository suitable for a single-process bot deployment."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS calculations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    building_type TEXT NOT NULL,
                    climate_key TEXT NOT NULL,
                    total_kw REAL NOT NULL,
                    recommended_kw REAL NOT NULL,
                    answers_json TEXT NOT NULL,
                    report TEXT NOT NULL,
                    engine_version TEXT NOT NULL DEFAULT 'legacy',
                    catalog_version TEXT NOT NULL DEFAULT 'legacy'
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS calculations_user_created
                ON calculations (telegram_user_id, created_at DESC)
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(calculations)").fetchall()
            }
            if "engine_version" not in columns:
                connection.execute(
                    "ALTER TABLE calculations ADD COLUMN engine_version TEXT "
                    "NOT NULL DEFAULT 'legacy'"
                )
            if "catalog_version" not in columns:
                connection.execute(
                    "ALTER TABLE calculations ADD COLUMN catalog_version TEXT "
                    "NOT NULL DEFAULT 'legacy'"
                )
            migrations = {
                "object_name": "TEXT NOT NULL DEFAULT 'Без названия'",
                "calculation_version": "INTEGER NOT NULL DEFAULT 1",
                "status": "TEXT NOT NULL DEFAULT 'completed'",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
                "author_user_id": "INTEGER",
                "parent_id": "INTEGER",
                "norms_version": "TEXT NOT NULL DEFAULT 'legacy'",
                "request_id": "TEXT",
            }
            for column, definition in migrations.items():
                if column not in columns:
                    connection.execute(f"ALTER TABLE calculations ADD COLUMN {column} {definition}")
            connection.execute("UPDATE calculations SET updated_at=created_at WHERE updated_at=''")
            connection.execute(
                "UPDATE calculations SET author_user_id=telegram_user_id "
                "WHERE author_user_id IS NULL"
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS calculations_user_request
                ON calculations (telegram_user_id, request_id)
                WHERE request_id IS NOT NULL
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS calculation_drafts (
                    telegram_user_id INTEGER PRIMARY KEY,
                    current_step TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    format_version INTEGER NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    telegram_user_id INTEGER PRIMARY KEY,
                    locale TEXT NOT NULL DEFAULT 'ru' CHECK (locale IN ('ru', 'uz')),
                    default_profile_id INTEGER,
                    prepared_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS calculation_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL,
                    name TEXT NOT NULL COLLATE NOCASE,
                    settings_json TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (telegram_user_id, name)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS calculation_profiles_owner_updated
                ON calculation_profiles (telegram_user_id, updated_at DESC)
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS calculation_profiles_one_default
                ON calculation_profiles (telegram_user_id)
                WHERE is_default = 1
                """
            )
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def get_user_settings(self, telegram_user_id: int) -> UserSettings:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO user_settings (
                    telegram_user_id, locale, created_at, updated_at
                ) VALUES (?, 'ru', ?, ?)
                """,
                (telegram_user_id, now, now),
            )
            row = connection.execute(
                """
                SELECT telegram_user_id, locale, default_profile_id, prepared_by
                FROM user_settings WHERE telegram_user_id=?
                """,
                (telegram_user_id,),
            ).fetchone()
        return UserSettings(**dict(row))

    def set_locale(self, telegram_user_id: int, locale: str) -> None:
        if locale not in {"ru", "uz"}:
            raise ValueError("Поддерживаются языки ru и uz")
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_settings (
                    telegram_user_id, locale, created_at, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    locale=excluded.locale, updated_at=excluded.updated_at
                """,
                (telegram_user_id, locale, now, now),
            )

    def set_prepared_by(self, telegram_user_id: int, prepared_by: str) -> None:
        prepared_by = prepared_by.strip()
        if len(prepared_by) > 120:
            raise ValueError("Имя автора должно содержать не более 120 символов")
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_settings (
                    telegram_user_id, locale, prepared_by, created_at, updated_at
                ) VALUES (?, 'ru', ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    prepared_by=excluded.prepared_by, updated_at=excluded.updated_at
                """,
                (telegram_user_id, prepared_by, now, now),
            )

    def create_profile(
        self,
        telegram_user_id: int,
        name: str,
        settings: dict[str, Any] | None = None,
        *,
        make_default: bool = False,
    ) -> CalculationProfile:
        name = name.strip()
        if not 1 <= len(name) <= 60:
            raise ValueError("Название профиля должно содержать от 1 до 60 символов")
        profiles = self.list_profiles(telegram_user_id)
        if len(profiles) >= 20:
            raise ValueError("Можно создать не больше 20 профилей")
        if any(profile.name.casefold() == name.casefold() for profile in profiles):
            raise ValueError("Профиль с таким названием уже существует")
        payload = json.dumps(settings or {}, ensure_ascii=False, sort_keys=True)
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as connection:
            if make_default:
                connection.execute(
                    "UPDATE calculation_profiles SET is_default=0 WHERE telegram_user_id=?",
                    (telegram_user_id,),
                )
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO calculation_profiles (
                        telegram_user_id, name, settings_json, is_default, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (telegram_user_id, name, payload, int(make_default), now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Профиль с таким названием уже существует") from exc
            profile_id = int(cursor.lastrowid)
            if make_default:
                self._set_default_reference(connection, telegram_user_id, profile_id, now)
            row = connection.execute(
                "SELECT * FROM calculation_profiles WHERE id=?", (profile_id,)
            ).fetchone()
        return self._profile(row)

    def list_profiles(self, telegram_user_id: int) -> list[CalculationProfile]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM calculation_profiles
                WHERE telegram_user_id=?
                ORDER BY is_default DESC, name COLLATE NOCASE
                """,
                (telegram_user_id,),
            ).fetchall()
        return [self._profile(row) for row in rows]

    def get_profile(self, telegram_user_id: int, profile_id: int) -> CalculationProfile | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM calculation_profiles WHERE telegram_user_id=? AND id=?",
                (telegram_user_id, profile_id),
            ).fetchone()
        return self._profile(row) if row else None

    def rename_profile(self, telegram_user_id: int, profile_id: int, name: str) -> bool:
        name = name.strip()
        if not 1 <= len(name) <= 60:
            raise ValueError("Название профиля должно содержать от 1 до 60 символов")
        if any(
            profile.id != profile_id and profile.name.casefold() == name.casefold()
            for profile in self.list_profiles(telegram_user_id)
        ):
            raise ValueError("Профиль с таким названием уже существует")
        now = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE calculation_profiles SET name=?, version=version+1, updated_at=?
                    WHERE telegram_user_id=? AND id=?
                    """,
                    (name, now, telegram_user_id, profile_id),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Профиль с таким названием уже существует") from exc
        return cursor.rowcount > 0

    def update_profile_settings(
        self,
        telegram_user_id: int,
        profile_id: int,
        settings: dict[str, Any],
    ) -> bool:
        try:
            indoor = float(settings["indoor"])
            air_changes = float(settings["air_changes"])
            safety_factor = float(settings["safety_factor"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Профиль содержит неполные числовые параметры") from exc
        if not math.isfinite(indoor) or not -30 <= indoor <= 50:
            raise ValueError("Температура профиля должна быть от -30 до +50 °C")
        if air_changes not in {0.3, 0.5, 0.8, 1.0}:
            raise ValueError("Воздухообмен профиля должен быть 0,3 / 0,5 / 0,8 / 1,0")
        if safety_factor not in {1.0, 1.1, 1.15, 1.2}:
            raise ValueError("Запас профиля должен быть 0 / 10 / 15 / 20%")
        payload = json.dumps(
            {
                "air_changes": air_changes,
                "indoor": indoor,
                "safety_factor": safety_factor,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE calculation_profiles
                SET settings_json=?, version=version+1, updated_at=?
                WHERE telegram_user_id=? AND id=?
                """,
                (payload, now, telegram_user_id, profile_id),
            )
        return cursor.rowcount > 0

    def duplicate_profile(
        self, telegram_user_id: int, profile_id: int, name: str
    ) -> CalculationProfile | None:
        source = self.get_profile(telegram_user_id, profile_id)
        if source is None:
            return None
        return self.create_profile(telegram_user_id, name, source.settings)

    def set_default_profile(self, telegram_user_id: int, profile_id: int) -> bool:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM calculation_profiles WHERE telegram_user_id=? AND id=?",
                (telegram_user_id, profile_id),
            ).fetchone()
            if exists is None:
                return False
            connection.execute(
                "UPDATE calculation_profiles SET is_default=0 WHERE telegram_user_id=?",
                (telegram_user_id,),
            )
            connection.execute(
                "UPDATE calculation_profiles SET is_default=1 WHERE id=?",
                (profile_id,),
            )
            self._set_default_reference(connection, telegram_user_id, profile_id, now)
        return True

    def delete_profile(self, telegram_user_id: int, profile_id: int) -> bool:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM calculation_profiles WHERE telegram_user_id=? AND id=?",
                (telegram_user_id, profile_id),
            )
            if cursor.rowcount:
                connection.execute(
                    """
                    UPDATE user_settings SET default_profile_id=NULL, updated_at=?
                    WHERE telegram_user_id=? AND default_profile_id=?
                    """,
                    (now, telegram_user_id, profile_id),
                )
        return cursor.rowcount > 0

    @staticmethod
    def _set_default_reference(
        connection: sqlite3.Connection, telegram_user_id: int, profile_id: int, now: str
    ) -> None:
        connection.execute(
            """
            INSERT INTO user_settings (
                telegram_user_id, locale, default_profile_id, created_at, updated_at
            ) VALUES (?, 'ru', ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                default_profile_id=excluded.default_profile_id,
                updated_at=excluded.updated_at
            """,
            (telegram_user_id, profile_id, now, now),
        )

    def save(
        self,
        telegram_user_id: int,
        answers: dict[str, Any],
        total_kw: float,
        recommended_kw: float,
        report: str,
        *,
        parent_id: int | None = None,
        request_id: str | None = None,
    ) -> int:
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as connection:
            object_name = str(answers.get("object_name") or "Без названия")[:120]
            row = connection.execute(
                """
                SELECT COALESCE(MAX(calculation_version), 0) + 1
                FROM calculations
                WHERE telegram_user_id=? AND object_name=?
                """,
                (telegram_user_id, object_name),
            ).fetchone()
            calculation_version = int(row[0])
            if request_id:
                existing = connection.execute(
                    "SELECT id FROM calculations WHERE telegram_user_id=? AND request_id=?",
                    (telegram_user_id, request_id),
                ).fetchone()
                if existing is not None:
                    return int(existing["id"])
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO calculations (
                    telegram_user_id, created_at, building_type, climate_key,
                    total_kw, recommended_kw, answers_json, report,
                    engine_version, catalog_version, object_name,
                    calculation_version, status, updated_at, author_user_id,
                    parent_id, norms_version, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_user_id,
                    created_at,
                    answers.get("building_type", "unknown"),
                    answers.get("climate_key", "manual"),
                    total_kw,
                    recommended_kw,
                    json.dumps(answers, ensure_ascii=False, sort_keys=True),
                    report,
                    ENGINE_VERSION,
                    CATALOG_VERSION,
                    object_name,
                    calculation_version,
                    "completed",
                    created_at,
                    telegram_user_id,
                    parent_id,
                    NORMS_VERSION,
                    request_id,
                ),
            )
            if cursor.rowcount == 0 and request_id:
                existing = connection.execute(
                    "SELECT id FROM calculations WHERE telegram_user_id=? AND request_id=?",
                    (telegram_user_id, request_id),
                ).fetchone()
                if existing is not None:
                    return int(existing["id"])
            if cursor.rowcount == 0:
                raise sqlite3.IntegrityError("Не удалось сохранить расчёт")
            return int(cursor.lastrowid)

    def recent(self, telegram_user_id: int, limit: int = 5) -> list[SavedCalculation]:
        if not 1 <= limit <= 50:
            raise ValueError("Лимит истории должен быть от 1 до 50")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, total_kw, recommended_kw,
                       climate_key, building_type, report,
                       engine_version, catalog_version, answers_json,
                       object_name, calculation_version, status, updated_at,
                       parent_id, norms_version
                FROM calculations
                WHERE telegram_user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (telegram_user_id, limit),
            ).fetchall()
        return [self._saved_calculation(row) for row in rows]

    def get_for_user(self, telegram_user_id: int, calculation_id: int) -> SavedCalculation | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, created_at, total_kw, recommended_kw,
                       climate_key, building_type, report,
                       engine_version, catalog_version, answers_json,
                       object_name, calculation_version, status, updated_at,
                       parent_id, norms_version
                FROM calculations
                WHERE telegram_user_id = ? AND id = ?
                """,
                (telegram_user_id, calculation_id),
            ).fetchone()
        return self._saved_calculation(row) if row else None

    def copy_answers_for_user(
        self, telegram_user_id: int, calculation_id: int
    ) -> dict[str, Any] | None:
        record = self.get_for_user(telegram_user_id, calculation_id)
        if record is None:
            return None
        copied = dict(record.answers)
        copied.pop("calculation_request_id", None)
        copied["parent_calculation_id"] = record.id
        return copied

    def compare_for_user(
        self, telegram_user_id: int, first_id: int, second_id: int
    ) -> dict[str, tuple[Any, Any]] | None:
        first = self.get_for_user(telegram_user_id, first_id)
        second = self.get_for_user(telegram_user_id, second_id)
        if first is None or second is None:
            return None
        keys = set(first.answers) | set(second.answers)
        return {
            key: (first.answers.get(key), second.answers.get(key))
            for key in sorted(keys)
            if first.answers.get(key) != second.answers.get(key)
        }

    def save_draft(
        self,
        telegram_user_id: int,
        current_step: str,
        data: dict[str, Any],
        *,
        ttl_days: int = 30,
    ) -> None:
        if not 1 <= ttl_days <= 365:
            raise ValueError("Срок хранения черновика должен быть от 1 до 365 дней")
        now = datetime.now(UTC)
        updated_at = now.isoformat(timespec="seconds")
        expires_at = (now + timedelta(days=ttl_days)).isoformat(timespec="seconds")
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO calculation_drafts (
                    telegram_user_id, current_step, data_json, created_at,
                    updated_at, format_version, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    current_step=excluded.current_step,
                    data_json=excluded.data_json,
                    updated_at=excluded.updated_at,
                    format_version=excluded.format_version,
                    expires_at=excluded.expires_at
                """,
                (
                    telegram_user_id,
                    current_step,
                    payload,
                    updated_at,
                    updated_at,
                    DRAFT_FORMAT_VERSION,
                    expires_at,
                ),
            )

    def load_draft(self, telegram_user_id: int) -> CalculationDraft | None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute("DELETE FROM calculation_drafts WHERE expires_at <= ?", (now,))
            row = connection.execute(
                "SELECT * FROM calculation_drafts WHERE telegram_user_id=?",
                (telegram_user_id,),
            ).fetchone()
        if row is None:
            return None
        if int(row["format_version"]) > DRAFT_FORMAT_VERSION:
            return None
        return CalculationDraft(
            telegram_user_id=int(row["telegram_user_id"]),
            current_step=str(row["current_step"]),
            data=json.loads(row["data_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            format_version=int(row["format_version"]),
            expires_at=str(row["expires_at"]),
        )

    def delete_draft(self, telegram_user_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM calculation_drafts WHERE telegram_user_id=?",
                (telegram_user_id,),
            )
        return cursor.rowcount > 0

    def delete_for_user(self, telegram_user_id: int) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM calculations WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            return cursor.rowcount

    def prune(self, retention_days: int) -> int:
        if not 1 <= retention_days <= 3650:
            raise ValueError("Срок хранения истории должен быть от 1 до 3650 дней")
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM calculations WHERE created_at < ?",
                (cutoff,),
            )
            connection.execute(
                "DELETE FROM calculation_drafts WHERE expires_at <= ?",
                (datetime.now(UTC).isoformat(timespec="seconds"),),
            )
        return cursor.rowcount

    def schema_version(self) -> int:
        with self._connect() as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _saved_calculation(row: sqlite3.Row) -> SavedCalculation:
        values = dict(row)
        values["answers"] = json.loads(values.pop("answers_json"))
        return SavedCalculation(**values)

    @staticmethod
    def _profile(row: sqlite3.Row) -> CalculationProfile:
        values = dict(row)
        values["settings"] = json.loads(values.pop("settings_json"))
        values["is_default"] = bool(values["is_default"])
        return CalculationProfile(**values)
