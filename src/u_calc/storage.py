import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .catalog import CATALOG_VERSION, ENGINE_VERSION

SCHEMA_VERSION = 2


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
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def save(
        self,
        telegram_user_id: int,
        answers: dict[str, Any],
        total_kw: float,
        recommended_kw: float,
        report: str,
    ) -> int:
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO calculations (
                    telegram_user_id, created_at, building_type, climate_key,
                    total_kw, recommended_kw, answers_json, report,
                    engine_version, catalog_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            return int(cursor.lastrowid)

    def recent(self, telegram_user_id: int, limit: int = 5) -> list[SavedCalculation]:
        if not 1 <= limit <= 50:
            raise ValueError("Лимит истории должен быть от 1 до 50")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, total_kw, recommended_kw,
                       climate_key, building_type, report,
                       engine_version, catalog_version
                FROM calculations
                WHERE telegram_user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (telegram_user_id, limit),
            ).fetchall()
        return [SavedCalculation(**dict(row)) for row in rows]

    def get_for_user(self, telegram_user_id: int, calculation_id: int) -> SavedCalculation | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, created_at, total_kw, recommended_kw,
                       climate_key, building_type, report,
                       engine_version, catalog_version
                FROM calculations
                WHERE telegram_user_id = ? AND id = ?
                """,
                (telegram_user_id, calculation_id),
            ).fetchone()
        return SavedCalculation(**dict(row)) if row else None

    def delete_for_user(self, telegram_user_id: int) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM calculations WHERE telegram_user_id = ?",
                (telegram_user_id,),
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
