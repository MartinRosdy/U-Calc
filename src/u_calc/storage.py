import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .catalog import CATALOG_VERSION, ENGINE_VERSION

SCHEMA_VERSION = 5
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
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

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
