import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from u_calc.app import main, run, single_instance_lock
from u_calc.config import Settings


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

    def test_missing_token_exits_cleanly_without_runtime_traceback(self) -> None:
        with (
            patch(
                "u_calc.app.Settings.from_env",
                side_effect=RuntimeError("Не задан BOT_TOKEN. Передайте токен через env."),
            ),
            self.assertRaises(SystemExit) as raised,
        ):
            main()
        self.assertEqual(raised.exception.code, 2)

    def test_main_runs_with_valid_settings(self) -> None:
        settings = Settings(bot_token="123:secret")
        with (
            patch("u_calc.app.Settings.from_env", return_value=settings),
            patch("u_calc.app.run", new_callable=AsyncMock) as mocked_run,
        ):
            main()
        mocked_run.assert_awaited_once_with(settings)


class AppRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_wires_middlewares_commands_polling_and_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                bot_token="123:secret",
                database_path=Path(directory) / "data" / "u_calc.db",
            )

            class Target:
                def __init__(self) -> None:
                    self.outer = []
                    self.inner = []

                def outer_middleware(self, value) -> None:
                    self.outer.append(value)

                def middleware(self, value) -> None:
                    self.inner.append(value)

            class Dispatcher:
                def __init__(self) -> None:
                    self.message = Target()
                    self.callback_query = Target()
                    self.routers = []
                    self.started = False

                def include_router(self, router) -> None:
                    self.routers.append(router)

                def resolve_used_update_types(self):
                    return ["message", "callback_query"]

                async def start_polling(self, bot, **kwargs) -> None:
                    self.started = True
                    self.polling_bot = bot
                    self.polling_kwargs = kwargs

            dispatcher = Dispatcher()
            bot = SimpleNamespace(
                set_my_commands=AsyncMock(),
                session=SimpleNamespace(close=AsyncMock()),
            )
            with (
                patch("u_calc.app.Dispatcher", return_value=dispatcher),
                patch("u_calc.app.Bot", return_value=bot),
                patch("u_calc.app.single_instance_lock", return_value=nullcontext()),
            ):
                await run(settings)

            self.assertTrue(settings.database_path.exists())
            self.assertEqual(len(dispatcher.message.outer), 3)
            self.assertEqual(len(dispatcher.callback_query.outer), 3)
            self.assertEqual(len(dispatcher.message.inner), 2)
            self.assertEqual(len(dispatcher.routers), 6)
            self.assertTrue(dispatcher.started)
            self.assertEqual(bot.set_my_commands.await_count, 2)
            self.assertEqual(
                bot.set_my_commands.await_args_list[1].kwargs,
                {"language_code": "uz"},
            )
            bot.session.close.assert_awaited_once()
