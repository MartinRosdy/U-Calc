import math
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

from u_calc.storage import SCHEMA_VERSION, CalculationRepository


class StorageTests(unittest.TestCase):
    def test_initialize_tightens_existing_database_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-permissions.db"
            with sqlite3.connect(path):
                pass
            path.chmod(0o644)

            CalculationRepository(path).initialize()

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_initialize_rejects_corrupt_database_before_modifying_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corrupt.db"
            original = b"this is not a sqlite database"
            path.write_bytes(original)

            with self.assertRaisesRegex(RuntimeError, "до миграции"):
                CalculationRepository(path).initialize()

            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(path.with_name(path.name + "-wal").exists())

    def test_initialize_refuses_database_from_newer_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future.db"
            with sqlite3.connect(path) as connection:
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")

            with self.assertRaisesRegex(RuntimeError, "поддерживает"):
                CalculationRepository(path).initialize()

            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0],
                    SCHEMA_VERSION + 1,
                )

    def test_repository_rejects_non_finite_results_and_json_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "strict-json.db")
            repository.initialize()
            with self.assertRaisesRegex(ValueError, "конечным"):
                repository.save(100, {"object_name": "Дом"}, math.nan, 5, "report")
            with self.assertRaisesRegex(ValueError, "ниже расчётной"):
                repository.save(100, {"object_name": "Дом"}, 5, 4, "report")
            with self.assertRaisesRegex(ValueError, "JSON compliant"):
                repository.save(
                    100,
                    {"object_name": "Дом", "corrupted": math.inf},
                    5,
                    5.5,
                    "report",
                )
            with self.assertRaisesRegex(ValueError, "JSON compliant"):
                repository.save_draft(100, "Survey:test", {"corrupted": math.nan})
            with self.assertRaisesRegex(ValueError, "JSON compliant"):
                repository.create_profile(100, "Плохой", {"corrupted": math.nan})

    def test_repository_rejects_ambiguous_or_control_character_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "strict-names.db")
            repository.initialize()
            with self.assertRaisesRegex(ValueError, "от 1 до 120"):
                repository.save(100, {"object_name": "Д" * 121}, 5, 5.5, "report")
            with self.assertRaisesRegex(ValueError, "управляющие"):
                repository.save(100, {"object_name": "Дом\u200b"}, 5, 5.5, "report")
            with self.assertRaisesRegex(ValueError, "управляющие"):
                repository.create_profile(100, "Про\nфиль")
            with self.assertRaisesRegex(ValueError, "управляющие"):
                repository.set_prepared_by(100, "Инженер\u200b")
            self.assertEqual(repository.recent(100), [])

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
            self.assertEqual(records[0].author_user_id, 100)
            self.assertNotEqual(records[0].engine_version, "legacy")
            self.assertEqual(repository.recent(999), [])
            self.assertEqual(repository.get_for_user(100, first_id).report, "first")
            self.assertIsNone(repository.get_for_user(200, first_id))
            self.assertFalse(repository.delete_calculation_for_user(200, first_id))
            self.assertTrue(repository.delete_calculation_for_user(100, first_id))
            self.assertIsNone(repository.get_for_user(100, first_id))
            self.assertEqual(repository.delete_for_user(100), 1)
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
                audit_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(audit_events)")
                }
                journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertIn("engine_version", columns)
            self.assertIn("catalog_version", columns)
            self.assertIn("calculation_version", columns)
            self.assertIn("norms_version", columns)
            self.assertIn("pdf_report", columns)
            self.assertEqual(
                audit_columns,
                {"id", "telegram_user_id", "action", "entity_type", "entity_id", "created_at"},
            )
            self.assertEqual(journal_mode, "wal")

    def test_audit_events_are_private_minimal_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "audit.db")
            repository.initialize()
            calculation_id = repository.save(
                100,
                {"object_name": "Секретный объект", "private_note": "не журналировать"},
                5,
                5.5,
                "private report",
                request_id="request-1",
            )
            self.assertEqual(
                repository.save(
                    100,
                    {"object_name": "Секретный объект"},
                    5,
                    5.5,
                    "private report",
                    request_id="request-1",
                ),
                calculation_id,
            )
            repository.store_pdf_for_user(100, calculation_id, b"%PDF-1.4\nfirst")
            repository.store_pdf_for_user(100, calculation_id, b"%PDF-1.4\nsecond")
            repository.save(200, {"object_name": "Другой"}, 2, 2.2, "other")

            events = repository.recent_audit_events(100)
            self.assertEqual(
                [event.action for event in events],
                ["pdf_stored", "calculation_completed"],
            )
            self.assertTrue(all(event.telegram_user_id == 100 for event in events))
            self.assertTrue(all(event.entity_id == str(calculation_id) for event in events))
            self.assertEqual(len(repository.recent_audit_events(200)), 1)
            with sqlite3.connect(repository.path) as connection:
                serialized = " ".join(
                    str(value)
                    for row in connection.execute("SELECT * FROM audit_events")
                    for value in row
                )
            self.assertNotIn("Секретный объект", serialized)
            self.assertNotIn("private report", serialized)
            self.assertNotIn("не журналировать", serialized)

            self.assertTrue(repository.delete_calculation_for_user(100, calculation_id))
            self.assertEqual(
                repository.recent_audit_events(100)[0].action,
                "calculation_deleted",
            )
            with self.assertRaises(ValueError):
                repository.recent_audit_events(100, limit=101)

    def test_full_user_erasure_removes_every_owned_sqlite_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "erase.db")
            repository.initialize()
            calculation_id = repository.save(100, {"object_name": "Дом"}, 5, 5.5, "report")
            repository.store_pdf_for_user(100, calculation_id, b"%PDF-1.4\nprivate")
            repository.save_draft(100, "Survey:wall_material", {"secret": "draft"})
            repository.create_profile(100, "Рабочий", make_default=True)
            repository.set_locale(100, "uz")
            other_id = repository.save(200, {"object_name": "Other"}, 2, 2.2, "other")

            deleted = repository.delete_all_user_data(100)
            self.assertEqual(deleted.calculations, 1)
            self.assertEqual(deleted.drafts, 1)
            self.assertEqual(deleted.profiles, 1)
            self.assertEqual(deleted.settings, 1)
            self.assertGreaterEqual(deleted.audit_events, 3)
            self.assertEqual(repository.recent(100), [])
            self.assertIsNone(repository.load_draft(100))
            self.assertEqual(repository.list_profiles(100), [])
            self.assertEqual(repository.recent_audit_events(100), [])
            self.assertIsNotNone(repository.get_for_user(200, other_id))
            with sqlite3.connect(repository.path) as connection:
                for table in (
                    "calculations",
                    "calculation_drafts",
                    "calculation_profiles",
                    "user_settings",
                    "audit_events",
                ):
                    count = connection.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE telegram_user_id=100"
                    ).fetchone()[0]
                    self.assertEqual(count, 0, table)

    def test_pdf_artifact_is_private_validated_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "pdf.db")
            repository.initialize()
            calculation_id = repository.save(100, {"object_name": "Дом"}, 5, 5.5, "report")
            first_pdf = b"%PDF-1.4\nfirst"
            second_pdf = b"%PDF-1.4\nsecond"

            self.assertTrue(repository.store_pdf_for_user(100, calculation_id, first_pdf))
            self.assertTrue(repository.store_pdf_for_user(100, calculation_id, second_pdf))
            self.assertEqual(repository.get_pdf_for_user(100, calculation_id), first_pdf)
            self.assertIsNone(repository.get_pdf_for_user(200, calculation_id))
            self.assertFalse(repository.store_pdf_for_user(200, calculation_id, first_pdf))
            with self.assertRaisesRegex(ValueError, "не является PDF"):
                repository.store_pdf_for_user(100, calculation_id, b"not a pdf")

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
                {
                    "object_name": "Склад",
                    "indoor": 20,
                    "calculation_request_id": "first-request",
                    "wall_editor_index": 0,
                },
                5,
                5.5,
                "first",
            )
            second_id = repository.save(
                100,
                {
                    "object_name": "Склад",
                    "indoor": 22,
                    "calculation_request_id": "second-request",
                    "wall_editor_index": 1,
                },
                6,
                6.6,
                "second",
                parent_id=first_id,
            )
            records = repository.recent(100)
            self.assertEqual([record.calculation_version for record in records], [2, 1])
            self.assertEqual(repository.previous_version_for_user(100, second_id).id, first_id)
            self.assertIsNone(repository.previous_version_for_user(100, first_id))
            self.assertIsNone(repository.previous_version_for_user(200, second_id))
            self.assertEqual(records[0].parent_id, first_id)
            copied = repository.copy_answers_for_user(100, first_id)
            self.assertEqual(copied["parent_calculation_id"], first_id)
            self.assertEqual(
                repository.compare_for_user(100, first_id, second_id)["indoor"],
                (20, 22),
            )
            self.assertEqual(
                repository.compare_for_user(100, first_id, second_id),
                {"indoor": (20, 22)},
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

    def test_retention_prunes_old_private_data_and_uses_incremental_vacuum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "retention.db")
            repository.initialize()
            old_id = repository.save(
                100,
                {"object_name": "Старый"},
                5,
                5.5,
                "old report",
            )
            current_id = repository.save(
                100,
                {"object_name": "Текущий"},
                6,
                6.6,
                "current report",
            )
            repository.save_draft(100, "Survey:indoor", {"indoor": 24})
            with sqlite3.connect(repository.path) as connection:
                connection.execute(
                    "UPDATE calculations SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?",
                    (old_id,),
                )
                connection.execute(
                    "UPDATE audit_events SET created_at='2000-01-01T00:00:00+00:00' "
                    "WHERE entity_id=?",
                    (str(old_id),),
                )
                connection.execute(
                    "UPDATE calculation_drafts SET expires_at='2000-01-01T00:00:00+00:00' "
                    "WHERE telegram_user_id=100"
                )
                self.assertEqual(connection.execute("PRAGMA auto_vacuum").fetchone()[0], 2)

            self.assertEqual(repository.prune(365), 1)
            self.assertIsNone(repository.get_for_user(100, old_id))
            self.assertIsNotNone(repository.get_for_user(100, current_id))
            self.assertIsNone(repository.load_draft(100))
            self.assertTrue(
                all(event.entity_id != str(old_id) for event in repository.recent_audit_events(100))
            )
            with self.assertRaisesRegex(ValueError, "от 1 до 3650"):
                repository.prune(0)

    def test_user_locale_and_profile_crud_are_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "profiles.db")
            repository.initialize()
            self.assertEqual(repository.get_saved_locale(999), "ru")
            with sqlite3.connect(repository.path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM user_settings WHERE telegram_user_id=999"
                    ).fetchone()[0],
                    0,
                )
            self.assertEqual(repository.get_user_settings(100).locale, "ru")
            repository.set_locale(100, "uz")
            self.assertEqual(repository.get_saved_locale(100), "uz")
            self.assertEqual(repository.get_user_settings(100).locale, "uz")
            repository.set_prepared_by(100, "ООО Тепло")
            self.assertEqual(repository.get_user_settings(100).prepared_by, "ООО Тепло")
            with self.assertRaises(ValueError):
                repository.set_prepared_by(100, "x" * 121)

            first = repository.create_profile(
                100,
                "Uy",
                {"indoor": 24, "safety_factor": 1.1},
                make_default=True,
            )
            self.assertTrue(first.is_default)
            self.assertTrue(
                repository.update_profile_settings(
                    100,
                    first.id,
                    {"indoor": 22, "air_changes": 0.8, "safety_factor": 1.15},
                )
            )
            updated = repository.get_profile(100, first.id)
            self.assertEqual(updated.settings["indoor"], 22.0)
            self.assertEqual(updated.version, first.version + 1)
            self.assertFalse(
                repository.update_profile_settings(
                    200,
                    first.id,
                    {"indoor": 22, "air_changes": 0.8, "safety_factor": 1.15},
                )
            )
            with self.assertRaises(ValueError):
                repository.update_profile_settings(
                    100,
                    first.id,
                    {"indoor": float("nan"), "air_changes": 0.8, "safety_factor": 1.15},
                )
            self.assertEqual(repository.get_user_settings(100).default_profile_id, first.id)
            self.assertIsNone(repository.get_profile(200, first.id))

            copied = repository.duplicate_profile(100, first.id, "Uy nusxasi")
            self.assertEqual(copied.settings, updated.settings)
            self.assertTrue(repository.rename_profile(100, copied.id, "Kvartira"))
            self.assertTrue(repository.set_default_profile(100, copied.id))
            profiles = repository.list_profiles(100)
            self.assertEqual(sum(profile.is_default for profile in profiles), 1)
            self.assertEqual(profiles[0].name, "Kvartira")
            self.assertFalse(repository.delete_profile(200, copied.id))
            self.assertTrue(repository.delete_profile(100, copied.id))
            self.assertIsNone(repository.get_user_settings(100).default_profile_id)

    def test_profile_names_are_unique_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "profiles.db")
            repository.initialize()
            repository.create_profile(100, "Дом")
            with self.assertRaisesRegex(ValueError, "уже существует"):
                repository.create_profile(100, "дом")
