import os
import unittest
from unittest.mock import patch

from u_calc.config import Settings


class SettingsTests(unittest.TestCase):
    def test_defaults_and_allowed_users(self) -> None:
        with patch.dict(
            os.environ,
            {"BOT_TOKEN": "123:secret", "ALLOWED_USER_IDS": "10, 20,10"},
            clear=True,
        ):
            settings = Settings.from_env()
        self.assertEqual(settings.app_timezone, "Asia/Tashkent")
        self.assertTrue(settings.is_user_allowed(10))
        self.assertFalse(settings.is_user_allowed(30))
        self.assertNotIn(settings.bot_token, repr(settings))

    def test_empty_allowlist_allows_everyone(self) -> None:
        settings = Settings(bot_token="123:secret")
        self.assertTrue(settings.is_user_allowed(999))

    def test_invalid_allowlist_is_rejected(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"BOT_TOKEN": "123:secret", "ALLOWED_USER_IDS": "10,nope"},
                clear=True,
            ),
            self.assertRaisesRegex(RuntimeError, "ALLOWED_USER_IDS"),
        ):
            Settings.from_env()

    def test_missing_token_is_rejected_without_echoing_a_secret(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(RuntimeError, "BOT_TOKEN"),
        ):
            Settings.from_env()


if __name__ == "__main__":
    unittest.main()
