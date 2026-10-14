import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib.metadata import version
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from u_calc.config import Settings
from u_calc.doctor import check_installation, main
from u_calc.locking import single_instance_lock
from u_calc.storage import SCHEMA_VERSION


class DoctorTests(unittest.TestCase):
    TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghi"

    def test_check_initializes_and_verifies_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "nested" / "u_calc.db"
            result = check_installation(
                Settings(
                    bot_token=self.TOKEN,
                    database_path=database,
                    allowed_user_ids=frozenset({10, 20}),
                )
            )

            self.assertTrue(database.is_file())
            self.assertEqual(result.application_version, version("u-calc"))
            self.assertEqual(result.engine_version, result.application_version)
            self.assertTrue(result.catalog_version)
            self.assertIn("ШНҚ", result.norms_version)
            self.assertEqual(result.schema_version, SCHEMA_VERSION)
            self.assertEqual(result.integrity, "ok")
            self.assertEqual(result.allowlist_size, 2)

    def test_cli_reports_safe_summary_without_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "u_calc.db"
            stdout = StringIO()
            with (
                patch.dict(
                    os.environ,
                    {
                        "BOT_TOKEN": self.TOKEN,
                        "DATABASE_PATH": str(database),
                        "ALLOWED_USER_IDS": "10,20",
                    },
                    clear=True,
                ),
                redirect_stdout(stdout),
            ):
                main()

            rendered = stdout.getvalue()
            self.assertIn("U-Calc doctor: OK", rendered)
            self.assertIn(f"schema v{SCHEMA_VERSION}", rendered)
            self.assertIn("allowlist (2 users)", rendered)
            self.assertIn(f"Version: app {version('u-calc')}", rendered)
            self.assertIn(
                "Limits: 30 actions/min; 600 global actions/min; 6 calculations/min",
                rendered,
            )
            self.assertIn("Retention: calculations 730 days; drafts 30 days", rendered)
            self.assertNotIn(self.TOKEN, rendered)

    def test_cli_fails_cleanly_for_invalid_config_and_active_bot(self) -> None:
        stderr = StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            redirect_stderr(stderr),
            self.assertRaisesRegex(SystemExit, "2"),
        ):
            main()
        self.assertIn("U-Calc doctor: ERROR", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "u_calc.db"
            settings = Settings(bot_token=self.TOKEN, database_path=database)
            with (
                single_instance_lock(database),
                self.assertRaisesRegex(RuntimeError, "Другой экземпляр"),
            ):
                check_installation(settings)

    def test_doctor_rejects_package_and_engine_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                bot_token=self.TOKEN,
                database_path=Path(directory) / "must-not-be-created.db",
            )
            with (
                patch("u_calc.doctor.version", return_value="9.9.9"),
                self.assertRaisesRegex(RuntimeError, "не совпадает.*app=9.9.9"),
            ):
                check_installation(settings)

            self.assertFalse(settings.database_path.exists())


if __name__ == "__main__":
    unittest.main()
