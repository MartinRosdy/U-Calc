import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from u_calc.locking import single_instance_lock


class PollingLockTests(unittest.TestCase):
    def test_lock_errors_are_normalized_and_holder_pid_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "u_calc.db"
            lock_path = database.with_suffix(".db.polling.lock")
            lock_path.write_text("stale", encoding="utf-8")
            lock_path.chmod(0o644)
            with (
                single_instance_lock(database),
                self.assertRaisesRegex(RuntimeError, rf"PID {os.getpid()}"),
                single_instance_lock(database),
            ):
                self.fail("second lock must not be acquired")

            self.assertEqual(lock_path.read_text(encoding="utf-8"), str(os.getpid()))
            self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("u_calc.locking.Path.open", side_effect=PermissionError("denied")),
            self.assertRaisesRegex(RuntimeError, "Не удалось открыть polling-lock"),
            single_instance_lock(Path(directory) / "u_calc.db"),
        ):
            self.fail("unwritable lock must not be acquired")

    def test_os_releases_lock_after_process_is_terminated(self) -> None:
        root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (str(root / "src"), environment.get("PYTHONPATH", "")))
        )
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "u_calc.db"
            code = (
                "import sys,time; from pathlib import Path; "
                "from u_calc.locking import single_instance_lock; "
                "p=Path(sys.argv[1]); "
                "ctx=single_instance_lock(p); ctx.__enter__(); "
                "print('locked', flush=True); time.sleep(60)"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", code, str(database)],
                cwd=root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(process.stdout.readline().strip(), "locked")
                with (
                    self.assertRaisesRegex(RuntimeError, "Другой экземпляр"),
                    single_instance_lock(database),
                ):
                    self.fail("live child lock must not be acquired")
            finally:
                process.kill()
                process.wait(timeout=5)

            with single_instance_lock(database):
                self.assertEqual(
                    database.with_suffix(".db.polling.lock").read_text(encoding="utf-8"),
                    str(os.getpid()),
                )


if __name__ == "__main__":
    unittest.main()
