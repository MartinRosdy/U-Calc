import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from u_calc.backup import create_backup, main, restore_backup, restore_main
from u_calc.locking import single_instance_lock
from u_calc.storage import SCHEMA_VERSION, CalculationRepository


class BackupTests(unittest.TestCase):
    def test_backup_cli_creates_verified_file_and_reports_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "u_calc.db"
            output = root / "cli-backup.db"
            CalculationRepository(database).initialize()
            stdout = StringIO()
            with (
                patch.object(
                    sys,
                    "argv",
                    ["u-calc-backup", "--database", str(database), "--output", str(output)],
                ),
                redirect_stdout(stdout),
            ):
                main()
            self.assertIn("schema v8", stdout.getvalue())
            with sqlite3.connect(output) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )

            with (
                patch.object(
                    sys,
                    "argv",
                    ["u-calc-backup", "--database", str(root / "missing.db")],
                ),
                self.assertRaisesRegex(SystemExit, "2"),
            ):
                main()

    def test_restore_cli_requires_confirmation_and_restores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "u_calc.db"
            backup = root / "known-good.db"
            repository = CalculationRepository(database)
            repository.initialize()
            repository.save(100, {"object_name": "Дом"}, 5, 5.5, "first")
            create_backup(database, backup)
            repository.save(100, {"object_name": "Дом"}, 6, 6.6, "second")

            with (
                patch.object(
                    sys,
                    "argv",
                    ["u-calc-restore", "--backup", str(backup), "--database", str(database)],
                ),
                self.assertRaisesRegex(SystemExit, "2"),
            ):
                restore_main()

            stdout = StringIO()
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "u-calc-restore",
                        "--backup",
                        str(backup),
                        "--database",
                        str(database),
                        "--yes",
                    ],
                ),
                redirect_stdout(stdout),
            ):
                restore_main()
            self.assertIn("schema v8", stdout.getvalue())
            self.assertIn("Аварийная копия", stdout.getvalue())
            self.assertEqual(len(CalculationRepository(database).recent(100)), 1)

    def test_online_backup_is_complete_verified_and_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "u_calc.db"
            output = root / "u_calc-backup.db"
            repository = CalculationRepository(source)
            repository.initialize()
            calculation_id = repository.save(
                100,
                {"object_name": "Дом"},
                5,
                5.5,
                "report",
            )

            with patch("u_calc.backup.os.fsync", wraps=os.fsync) as fsync:
                version, integrity = create_backup(source, output)
            self.assertEqual(version, SCHEMA_VERSION)
            self.assertEqual(integrity, "ok")
            self.assertGreaterEqual(fsync.call_count, 2)
            self.assertGreater(output.stat().st_size, 0)
            with sqlite3.connect(output) as connection:
                self.assertEqual(
                    connection.execute("SELECT id FROM calculations").fetchone()[0],
                    calculation_id,
                )
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

            original = output.read_bytes()
            with self.assertRaisesRegex(ValueError, "не будет перезаписан"):
                create_backup(source, output)
            self.assertEqual(output.read_bytes(), original)

    def test_backup_rejects_source_destination_alias_and_missing_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "u_calc.db"
            CalculationRepository(source).initialize()
            with self.assertRaisesRegex(ValueError, "должен отличаться"):
                create_backup(source, source)
            with self.assertRaisesRegex(ValueError, "Каталог backup не найден"):
                create_backup(source, root / "missing" / "backup.db")

    def test_restore_is_atomic_keeps_emergency_copy_and_requires_stopped_bot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "u_calc.db"
            backup = root / "known-good.db"
            repository = CalculationRepository(database)
            repository.initialize()
            first = repository.save(100, {"object_name": "Дом"}, 5, 5.5, "first")
            create_backup(database, backup)
            repository.save(100, {"object_name": "Дом"}, 6, 6.6, "second")

            with (
                single_instance_lock(database),
                self.assertRaisesRegex(RuntimeError, "Другой экземпляр"),
            ):
                restore_backup(backup, database)
            self.assertEqual(len(repository.recent(100)), 2)

            # Maintenance commands must stay usable without importing Telegram/aiogram.
            with patch.dict(sys.modules, {"u_calc.app": None}):
                version, emergency = restore_backup(backup, database)
            self.assertEqual(version, SCHEMA_VERSION)
            self.assertIsNotNone(emergency)
            self.assertTrue(emergency.is_file())
            self.assertFalse(database.with_name(database.name + "-wal").exists())
            self.assertFalse(database.with_name(database.name + "-shm").exists())
            restored = CalculationRepository(database)
            self.assertEqual([item.id for item in restored.recent(100)], [first])
            previous = CalculationRepository(emergency)
            self.assertEqual(len(previous.recent(100)), 2)

    def test_restore_rejects_database_from_newer_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "future.db"
            with sqlite3.connect(backup) as connection:
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
            with self.assertRaisesRegex(ValueError, "поддерживает"):
                restore_backup(backup, root / "u_calc.db")

    def test_restore_rejects_backup_changed_after_initial_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "changing.db"
            destination = root / "u_calc.db"
            CalculationRepository(backup).initialize()
            original_create_backup = create_backup

            def change_before_copy(source: Path, output: Path) -> tuple[int, str]:
                if source.resolve() == backup.resolve():
                    with sqlite3.connect(backup) as connection:
                        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
                return original_create_backup(source, output)

            with (
                patch("u_calc.backup.create_backup", side_effect=change_before_copy),
                self.assertRaisesRegex(ValueError, "изменился во время восстановления"),
            ):
                restore_backup(backup, destination)

            self.assertFalse(destination.exists())
            self.assertEqual(list(root.glob(".*.restore-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
