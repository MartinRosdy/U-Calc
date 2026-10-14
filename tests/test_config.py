import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from u_calc.config import Settings


class SettingsTests(unittest.TestCase):
    TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghi"

    def test_defaults_and_allowed_users(self) -> None:
        with patch.dict(
            os.environ,
            {"BOT_TOKEN": self.TOKEN, "ALLOWED_USER_IDS": "10, 20,10"},
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
                {"BOT_TOKEN": self.TOKEN, "ALLOWED_USER_IDS": "10,nope"},
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

    def test_placeholder_malformed_token_and_empty_database_path_are_rejected(self) -> None:
        for token in ("123:secret", "123456789:replace-with-token-from-BotFather"):
            with (
                self.subTest(token=token),
                patch.dict(os.environ, {"BOT_TOKEN": token}, clear=True),
                self.assertRaisesRegex(RuntimeError, "BOT_TOKEN"),
            ):
                Settings.from_env()
        with (
            patch.dict(
                os.environ,
                {"BOT_TOKEN": self.TOKEN, "DATABASE_PATH": "   "},
                clear=True,
            ),
            self.assertRaisesRegex(RuntimeError, "DATABASE_PATH"),
        ):
            Settings.from_env()

    def test_public_safety_and_retention_settings_are_bounded(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BOT_TOKEN": self.TOKEN,
                "RATE_LIMIT_PER_MINUTE": "12",
                "GLOBAL_RATE_LIMIT_PER_MINUTE": "240",
                "CALCULATION_RATE_LIMIT_PER_MINUTE": "3",
                "MAX_MESSAGE_LENGTH": "2000",
                "HISTORY_RETENTION_DAYS": "365",
                "DRAFT_TTL_DAYS": "14",
            },
            clear=True,
        ):
            settings = Settings.from_env()
        self.assertEqual(settings.rate_limit_per_minute, 12)
        self.assertEqual(settings.global_rate_limit_per_minute, 240)
        self.assertEqual(settings.calculation_rate_limit_per_minute, 3)
        self.assertEqual(settings.max_message_length, 2000)
        self.assertEqual(settings.history_retention_days, 365)
        self.assertEqual(settings.draft_ttl_days, 14)

        with (
            patch.dict(
                os.environ,
                {"BOT_TOKEN": self.TOKEN, "RATE_LIMIT_PER_MINUTE": "0"},
                clear=True,
            ),
            self.assertRaisesRegex(RuntimeError, "RATE_LIMIT_PER_MINUTE"),
        ):
            Settings.from_env()

        with (
            patch.dict(
                os.environ,
                {"BOT_TOKEN": self.TOKEN, "GLOBAL_RATE_LIMIT_PER_MINUTE": "29"},
                clear=True,
            ),
            self.assertRaisesRegex(RuntimeError, "GLOBAL_RATE_LIMIT_PER_MINUTE"),
        ):
            Settings.from_env()

        with (
            patch.dict(
                os.environ,
                {
                    "BOT_TOKEN": self.TOKEN,
                    "CALCULATION_RATE_LIMIT_PER_MINUTE": "61",
                },
                clear=True,
            ),
            self.assertRaisesRegex(RuntimeError, "CALCULATION_RATE_LIMIT_PER_MINUTE"),
        ):
            Settings.from_env()

    def test_environment_contract_is_synchronized_across_distribution_surfaces(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        expected = {
            "BOT_TOKEN",
            "DATABASE_PATH",
            "LOG_LEVEL",
            "APP_TIMEZONE",
            "ALLOWED_USER_IDS",
            "RATE_LIMIT_PER_MINUTE",
            "GLOBAL_RATE_LIMIT_PER_MINUTE",
            "CALCULATION_RATE_LIMIT_PER_MINUTE",
            "MAX_MESSAGE_LENGTH",
            "HISTORY_RETENTION_DAYS",
            "DRAFT_TTL_DAYS",
        }
        env_example = (project_root / ".env.example").read_text(encoding="utf-8")
        env_keys = {
            line.partition("=")[0]
            for line in env_example.splitlines()
            if line and not line.startswith("#") and "=" in line
        }
        self.assertEqual(env_keys, expected)

        config_source = (project_root / "src" / "u_calc" / "config.py").read_text(
            encoding="utf-8"
        )
        configured_keys = set(
            re.findall(
                r'(?:os\.getenv|_bounded_int)\("([A-Z][A-Z0-9_]+)"',
                config_source,
            )
        )
        self.assertEqual(configured_keys, expected)

        compose = (project_root / "compose.yaml").read_text(encoding="utf-8")
        readme = (project_root / "README.md").read_text(encoding="utf-8")
        bothost = (project_root / "docs" / "BOTHOST_DEPLOY.md").read_text(encoding="utf-8")
        for key in sorted(expected):
            with self.subTest(key=key):
                self.assertIn(f"{key}:", compose)
                self.assertIn(f"`{key}`", readme)
                self.assertIn(f"`{key}", bothost)


if __name__ == "__main__":
    unittest.main()
