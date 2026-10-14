import json
import math
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .catalog import CATALOG_VERSION, ENGINE_VERSION

SCHEMA_VERSION = 8
DRAFT_FORMAT_VERSION = 1
_COMPARISON_METADATA_KEYS = frozenset(
    {
        "_back_stack",
        "active_boundary",
        "active_surface",
        "calculation_id",
        "calculation_request_id",
        "locale",
        "parent_calculation_id",
        "profile_defaults",
        "state",
    }
)
_COMPARISON_METADATA_PREFIXES = (
    "bridge_editor_",
    "opening_editor_",
    "surface_pending_",
    "wall_editor_",
)
NORMS_VERSION = "ШНҚ 2.04.05-22 (ред. 07.07.2026)"


def _json_payload(value: Any) -> str:
    """Serialize persisted user data as strict RFC-compatible JSON."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )


def _validated_text(
    value: Any,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} должно быть текстом")
    value = value.strip()
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} должно содержать от {minimum} до {maximum} символов")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError(f"{label} содержит недопустимые управляющие символы")
    return value


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
    author_user_id: int


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


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Privacy-safe action metadata; never contains messages or calculation inputs."""

    id: int
    telegram_user_id: int
    action: str
    entity_type: str
    entity_id: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class DeletedUserData:
    calculations: int
    drafts: int
    profiles: int
    settings: int
    audit_events: int


class CalculationRepository:
    """Small SQLite repository suitable for a single-process bot deployment."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as connection:
                self._tighten_sqlite_permissions()
                existing_database = self.path.stat().st_size > 0
                if existing_database:
                    self._require_integrity(connection, "до миграции")
                current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if current_version > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"База использует schema v{current_version}, а этот U-Calc поддерживает "
                        f"не выше v{SCHEMA_VERSION}"
                    )
                if not existing_database:
                    connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
                connection.execute("PRAGMA journal_mode=WAL")
                self._initialize_schema(connection)
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                self._require_integrity(connection, "после миграции")
        finally:
            self._tighten_sqlite_permissions()

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        """Create and migrate schema while ``initialize`` owns the connection."""
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
            "pdf_report": "BLOB",
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS audit_events_owner_created
            ON audit_events (telegram_user_id, created_at DESC, id DESC)
            """
        )

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

    def get_saved_locale(self, telegram_user_id: int) -> str:
        """Return a saved locale without creating data for an unknown Telegram user."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT locale FROM user_settings WHERE telegram_user_id=?",
                (telegram_user_id,),
            ).fetchone()
        return str(row["locale"]) if row is not None else "ru"

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
        prepared_by = _validated_text(
            prepared_by,
            "Имя автора",
            minimum=0,
            maximum=120,
        )
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
        name = _validated_text(name, "Название профиля", minimum=1, maximum=60)
        profiles = self.list_profiles(telegram_user_id)
        if len(profiles) >= 20:
            raise ValueError("Можно создать не больше 20 профилей")
        if any(profile.name.casefold() == name.casefold() for profile in profiles):
            raise ValueError("Профиль с таким названием уже существует")
        payload = _json_payload(settings or {})
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
            self._record_audit(
                connection, telegram_user_id, "profile_created", "profile", profile_id, now
            )
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
        name = _validated_text(name, "Название профиля", minimum=1, maximum=60)
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
                if cursor.rowcount:
                    self._record_audit(
                        connection,
                        telegram_user_id,
                        "profile_renamed",
                        "profile",
                        profile_id,
                        now,
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
        payload = _json_payload(
            {
                "air_changes": air_changes,
                "indoor": indoor,
                "safety_factor": safety_factor,
            }
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
            if cursor.rowcount:
                self._record_audit(
                    connection,
                    telegram_user_id,
                    "profile_updated",
                    "profile",
                    profile_id,
                    now,
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
            self._record_audit(
                connection,
                telegram_user_id,
                "profile_defaulted",
                "profile",
                profile_id,
                now,
            )
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
                self._record_audit(
                    connection,
                    telegram_user_id,
                    "profile_deleted",
                    "profile",
                    profile_id,
                    now,
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
        for value, label in (
            (total_kw, "Расчётная нагрузка"),
            (recommended_kw, "Рекомендуемая мощность"),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{label} должна быть конечным неотрицательным числом")
        if recommended_kw + 1e-9 < total_kw:
            raise ValueError("Рекомендуемая мощность не может быть ниже расчётной")
        answers_payload = _json_payload(answers)
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as connection:
            raw_object_name = answers.get("object_name")
            object_name = (
                "Без названия"
                if raw_object_name is None or raw_object_name == ""
                else _validated_text(
                    raw_object_name,
                    "Название объекта",
                    minimum=1,
                    maximum=120,
                )
            )
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
                    answers_payload,
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
            calculation_id = int(cursor.lastrowid)
            self._record_audit(
                connection,
                telegram_user_id,
                "calculation_completed",
                "calculation",
                calculation_id,
                created_at,
            )
            return calculation_id

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
                       parent_id, norms_version, author_user_id
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
                       parent_id, norms_version, author_user_id
                FROM calculations
                WHERE telegram_user_id = ? AND id = ?
                """,
                (telegram_user_id, calculation_id),
            ).fetchone()
        return self._saved_calculation(row) if row else None

    def store_pdf_for_user(
        self,
        telegram_user_id: int,
        calculation_id: int,
        pdf: bytes,
    ) -> bool:
        """Persist the immutable PDF artifact for an owned calculation.

        The first successfully stored document wins. This keeps an already issued
        calculation version reproducible if report rendering changes later.
        """
        if not pdf.startswith(b"%PDF-"):
            raise ValueError("Артефакт отчёта не является PDF")
        if len(pdf) > 10 * 1024 * 1024:
            raise ValueError("PDF-отчёт превышает допустимый размер 10 МБ")
        with self._connect() as connection:
            owned = connection.execute(
                "SELECT pdf_report IS NOT NULL FROM calculations WHERE telegram_user_id=? AND id=?",
                (telegram_user_id, calculation_id),
            ).fetchone()
            if owned is None:
                return False
            if bool(owned[0]):
                return True
            cursor = connection.execute(
                "UPDATE calculations SET pdf_report=? "
                "WHERE telegram_user_id=? AND id=? AND pdf_report IS NULL",
                (sqlite3.Binary(pdf), telegram_user_id, calculation_id),
            )
            if cursor.rowcount:
                self._record_audit(
                    connection,
                    telegram_user_id,
                    "pdf_stored",
                    "calculation",
                    calculation_id,
                )
        return cursor.rowcount > 0

    def get_pdf_for_user(self, telegram_user_id: int, calculation_id: int) -> bytes | None:
        """Return a stored PDF only to the owner of its calculation."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT pdf_report FROM calculations WHERE telegram_user_id=? AND id=?",
                (telegram_user_id, calculation_id),
            ).fetchone()
        if row is None or row["pdf_report"] is None:
            return None
        return bytes(row["pdf_report"])

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
        keys = {
            key
            for key in set(first.answers) | set(second.answers)
            if key not in _COMPARISON_METADATA_KEYS
            and not key.startswith(_COMPARISON_METADATA_PREFIXES)
        }
        return {
            key: (first.answers.get(key), second.answers.get(key))
            for key in sorted(keys)
            if first.answers.get(key) != second.answers.get(key)
        }

    def previous_version_for_user(
        self, telegram_user_id: int, calculation_id: int
    ) -> SavedCalculation | None:
        """Return the immediately preceding version of the same named object."""
        current = self.get_for_user(telegram_user_id, calculation_id)
        if current is None:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, created_at, total_kw, recommended_kw,
                       climate_key, building_type, report,
                       engine_version, catalog_version, answers_json,
                       object_name, calculation_version, status, updated_at,
                       parent_id, norms_version, author_user_id
                FROM calculations
                WHERE telegram_user_id=? AND object_name=?
                  AND calculation_version < ?
                ORDER BY calculation_version DESC, id DESC
                LIMIT 1
                """,
                (
                    telegram_user_id,
                    current.object_name,
                    current.calculation_version,
                ),
            ).fetchone()
        return self._saved_calculation(row) if row else None

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
        payload = _json_payload(data)
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
            deleted = cursor.rowcount
            if deleted:
                self._record_audit(
                    connection,
                    telegram_user_id,
                    "history_cleared",
                    "calculation_history",
                    str(deleted),
                )
            return deleted

    def delete_calculation_for_user(self, telegram_user_id: int, calculation_id: int) -> bool:
        """Delete exactly one owned calculation without exposing cross-user records."""
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM calculations WHERE telegram_user_id=? AND id=?",
                (telegram_user_id, calculation_id),
            )
            if cursor.rowcount:
                self._record_audit(
                    connection,
                    telegram_user_id,
                    "calculation_deleted",
                    "calculation",
                    calculation_id,
                )
        return cursor.rowcount > 0

    def delete_all_user_data(self, telegram_user_id: int) -> DeletedUserData:
        """Irreversibly erase all SQLite data owned by one Telegram user.

        No audit event is retained: keeping the identifier after an explicit full-erasure
        request would contradict the operation's contract.
        """
        with self._connect() as connection:
            calculations = connection.execute(
                "DELETE FROM calculations WHERE telegram_user_id=?", (telegram_user_id,)
            ).rowcount
            drafts = connection.execute(
                "DELETE FROM calculation_drafts WHERE telegram_user_id=?", (telegram_user_id,)
            ).rowcount
            profiles = connection.execute(
                "DELETE FROM calculation_profiles WHERE telegram_user_id=?", (telegram_user_id,)
            ).rowcount
            settings = connection.execute(
                "DELETE FROM user_settings WHERE telegram_user_id=?", (telegram_user_id,)
            ).rowcount
            audit_events = connection.execute(
                "DELETE FROM audit_events WHERE telegram_user_id=?", (telegram_user_id,)
            ).rowcount
        return DeletedUserData(
            calculations=calculations,
            drafts=drafts,
            profiles=profiles,
            settings=settings,
            audit_events=audit_events,
        )

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
            connection.execute("DELETE FROM audit_events WHERE created_at < ?", (cutoff,))
            deleted_calculations = cursor.rowcount
        with self._connect() as connection:
            auto_vacuum = int(connection.execute("PRAGMA auto_vacuum").fetchone()[0])
            if auto_vacuum == 2:
                # Keep startup maintenance bounded while returning free tail pages.
                connection.execute("PRAGMA incremental_vacuum(256)")
        return deleted_calculations

    def recent_audit_events(self, telegram_user_id: int, limit: int = 50) -> list[AuditEvent]:
        """Return only the caller's metadata events for support and verification."""
        if not 1 <= limit <= 100:
            raise ValueError("Лимит аудита должен быть от 1 до 100")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, telegram_user_id, action, entity_type, entity_id, created_at
                FROM audit_events
                WHERE telegram_user_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (telegram_user_id, limit),
            ).fetchall()
        return [AuditEvent(**dict(row)) for row in rows]

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

    def _tighten_sqlite_permissions(self) -> None:
        """Keep existing and newly created SQLite files private on POSIX hosts."""
        for path in (
            self.path,
            self.path.with_name(self.path.name + "-wal"),
            self.path.with_name(self.path.name + "-shm"),
        ):
            try:
                path.chmod(0o600)
            except FileNotFoundError:
                continue

    @staticmethod
    def _require_integrity(connection: sqlite3.Connection, stage: str) -> None:
        """Fail closed before polling if SQLite reports structural corruption."""
        try:
            findings = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(
                f"SQLite не прошла проверку целостности ({stage}): {exc}"
            ) from exc
        if findings != ["ok"]:
            details = "; ".join(findings[:3]) or "неизвестная ошибка"
            raise RuntimeError(
                f"SQLite не прошла проверку целостности ({stage}): {details}"
            )

    @staticmethod
    def _record_audit(
        connection: sqlite3.Connection,
        telegram_user_id: int,
        action: str,
        entity_type: str,
        entity_id: int | str | None,
        created_at: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events (
                telegram_user_id, action, entity_type, entity_id, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                telegram_user_id,
                action,
                entity_type,
                None if entity_id is None else str(entity_id),
                created_at or datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )

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
