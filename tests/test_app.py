import tempfile
import unittest
from pathlib import Path

from u_calc.app import single_instance_lock


class AppTests(unittest.TestCase):
    def test_second_polling_instance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "u_calc.db"
            with (
                single_instance_lock(database),
                self.assertRaisesRegex(RuntimeError, "Другой экземпляр"),
                single_instance_lock(database),
            ):
                self.fail("second lock must not be acquired")
