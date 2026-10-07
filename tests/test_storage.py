import sqlite3
import tempfile
import unittest
from pathlib import Path

from u_calc.storage import SCHEMA_VERSION, CalculationRepository


class StorageTests(unittest.TestCase):
    def test_history_is_private_and_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "test.db")
            repository.initialize()
            self.assertEqual(repository.schema_version(), SCHEMA_VERSION)
            first_id = repository.save(
                100,
                {"building_type": "house", "climate_key": "tashkent"},
                5.0,
                5.5,
                "first",
            )
            second_id = repository.save(
                100,
                {"building_type": "apartment", "climate_key": "manual"},
                3.0,
                3.3,
                "second",
            )
            repository.save(
                200,
                {"building_type": "house", "climate_key": "nukus"},
                7.0,
                7.7,
                "other user",
            )

            records = repository.recent(100)
            self.assertEqual([item.id for item in records], [second_id, first_id])
            self.assertEqual(records[0].report, "second")
            self.assertNotEqual(records[0].engine_version, "legacy")
            self.assertEqual(repository.recent(999), [])
            self.assertEqual(repository.get_for_user(100, first_id).report, "first")
            self.assertIsNone(repository.get_for_user(200, first_id))
            self.assertEqual(repository.delete_for_user(100), 2)
            self.assertEqual(repository.recent(100), [])

    def test_v1_database_is_migrated_and_wal_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    CREATE TABLE calculations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_user_id INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        building_type TEXT NOT NULL,
                        climate_key TEXT NOT NULL,
                        total_kw REAL NOT NULL,
                        recommended_kw REAL NOT NULL,
                        answers_json TEXT NOT NULL,
                        report TEXT NOT NULL
                    )
                    """
                )
                connection.execute("PRAGMA user_version=1")

            repository = CalculationRepository(path)
            repository.initialize()

            self.assertEqual(repository.schema_version(), SCHEMA_VERSION)
            with sqlite3.connect(path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(calculations)")}
                journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertIn("engine_version", columns)
            self.assertIn("catalog_version", columns)
            self.assertIn("calculation_version", columns)
            self.assertIn("norms_version", columns)
            self.assertEqual(journal_mode, "wal")

    def test_draft_survives_repository_restart_and_can_be_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "draft.db"
            repository = CalculationRepository(path)
            repository.initialize()
            repository.save_draft(
                100,
                "Survey:wall_thickness",
                {"object_name": "Дом", "wall_material": "brick_solid"},
            )

            restarted = CalculationRepository(path)
            restarted.initialize()
            draft = restarted.load_draft(100)
            self.assertIsNotNone(draft)
            self.assertEqual(draft.current_step, "Survey:wall_thickness")
            self.assertEqual(draft.data["object_name"], "Дом")
            self.assertIsNone(restarted.load_draft(200))
            self.assertTrue(restarted.delete_draft(100))
            self.assertIsNone(restarted.load_draft(100))

    def test_versions_copy_and_comparison_remain_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "versions.db")
            repository.initialize()
            first_id = repository.save(
                100,
                {"object_name": "Склад", "indoor": 20},
                5,
                5.5,
                "first",
            )
            second_id = repository.save(
                100,
                {"object_name": "Склад", "indoor": 22},
                6,
                6.6,
                "second",
                parent_id=first_id,
            )
            records = repository.recent(100)
            self.assertEqual([record.calculation_version for record in records], [2, 1])
            self.assertEqual(records[0].parent_id, first_id)
            copied = repository.copy_answers_for_user(100, first_id)
            self.assertEqual(copied["parent_calculation_id"], first_id)
            self.assertEqual(
                repository.compare_for_user(100, first_id, second_id)["indoor"],
                (20, 22),
            )
            self.assertIsNone(repository.copy_answers_for_user(200, first_id))
            self.assertIsNone(repository.compare_for_user(200, first_id, second_id))

    def test_repeated_final_request_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "idempotent.db")
            repository.initialize()
            first = repository.save(
                100,
                {"object_name": "Дом"},
                5,
                5.5,
                "report",
                request_id="same-final-callback",
            )
            repeated = repository.save(
                100,
                {"object_name": "Дом"},
                5,
                5.5,
                "report",
                request_id="same-final-callback",
            )
            other_user = repository.save(
                200,
                {"object_name": "Дом"},
                5,
                5.5,
                "report",
                request_id="same-final-callback",
            )
            self.assertEqual(first, repeated)
            self.assertNotEqual(first, other_user)
            self.assertEqual(len(repository.recent(100)), 1)
