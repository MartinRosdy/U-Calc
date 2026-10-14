import asyncio
import io
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError

from u_calc.app import (
    SecretRedactingFormatter,
    main,
    periodic_retention,
    run,
    single_instance_lock,
)
from u_calc.config import Settings


class AppTests(unittest.TestCase):
    def test_log_formatter_redacts_plain_encoded_and_traceback_tokens(self) -> None:
        token = "123456:secret/value"
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(
            SecretRedactingFormatter(
                logging.Formatter("%(levelname)s %(message)s"),
                (token,),
            )
        )
        logger = logging.getLogger("u_calc.test.redaction")
        logger.propagate = False
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            try:
                raise RuntimeError(f"plain={token} encoded=123456%3Asecret%2Fvalue")
            except RuntimeError:
                logger.exception("request failed token=%s", token)
        finally:
            logger.removeHandler(handler)
            logger.propagate = True

        rendered = stream.getvalue()
        self.assertNotIn(token, rendered)
        self.assertNotIn("123456%3Asecret%2Fvalue", rendered)
        self.assertGreaterEqual(rendered.count("[REDACTED]"), 3)

    def test_second_polling_instance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "u_calc.db"
            with (
                single_instance_lock(database),
                self.assertRaisesRegex(RuntimeError, "Другой экземпляр"),
                single_instance_lock(database),
            ):
                self.fail("second lock must not be acquired")

            lock_path = database.with_suffix(database.suffix + ".polling.lock")
            self.assertEqual(lock_path.read_text(encoding="utf-8"), str(os.getpid()))

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

    def test_polling_startup_error_exits_cleanly(self) -> None:
        settings = Settings(bot_token="123:secret")
        with (
            patch("u_calc.app.Settings.from_env", return_value=settings),
            patch(
                "u_calc.app.run",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Другой экземпляр U-Calc уже использует эту базу"),
            ),
            self.assertRaises(SystemExit) as raised,
        ):
            main()
        self.assertEqual(raised.exception.code, 2)

    def test_telegram_startup_error_exits_cleanly_and_redacts_token(self) -> None:
        token = "123456:secret-value-that-must-not-leak"
        settings = Settings(bot_token=token)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            with (
                patch("u_calc.app.Settings.from_env", return_value=settings),
                patch(
                    "u_calc.app.run",
                    new_callable=AsyncMock,
                    side_effect=TelegramUnauthorizedError(
                        method=Mock(), message=f"invalid token {token}"
                    ),
                ),
                self.assertRaises(SystemExit) as raised,
            ):
                main()
        finally:
            root.removeHandler(handler)

        rendered = stream.getvalue()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("Ошибка запуска Telegram", rendered)
        self.assertIn("[REDACTED]", rendered)
        self.assertNotIn(token, rendered)
        self.assertNotIn("Traceback", rendered)


class AppRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_periodic_retention_repeats_and_stops_on_cancellation(self) -> None:
        completed = threading.Event()
        repository = SimpleNamespace(
            prune=Mock(side_effect=lambda _days: completed.set() or 2)
        )
        task = asyncio.create_task(
            periodic_retention(repository, 730, interval_seconds=0),
        )
        self.assertTrue(await asyncio.to_thread(completed.wait, 1))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        repository.prune.assert_called_with(730)

    async def test_periodic_retention_logs_transient_database_error_and_retries(self) -> None:
        completed = threading.Event()
        attempts = 0

        def prune(_days: int) -> int:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise sqlite3.OperationalError("temporarily locked")
            completed.set()
            return 0

        repository = SimpleNamespace(prune=Mock(side_effect=prune))
        with self.assertLogs("u_calc.app", level="ERROR") as captured:
            task = asyncio.create_task(
                periodic_retention(repository, 730, interval_seconds=0),
            )
            self.assertTrue(await asyncio.to_thread(completed.wait, 1))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertGreaterEqual(attempts, 2)
        self.assertIn("next run will retry", "\n".join(captured.output))

    async def test_periodic_retention_finishes_inflight_sqlite_work_before_shutdown(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def prune(_days: int) -> int:
            started.set()
            release.wait(timeout=2)
            return 1

        repository = SimpleNamespace(prune=Mock(side_effect=prune))
        task = asyncio.create_task(
            periodic_retention(repository, 730, interval_seconds=0),
        )
        self.assertTrue(await asyncio.to_thread(started.wait, 1))
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())

        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)

        repository.prune.assert_called_once_with(730)

    async def test_periodic_retention_preserves_cancellation_if_inflight_work_fails(
        self,
    ) -> None:
        started = threading.Event()
        release = threading.Event()

        def prune(_days: int) -> int:
            started.set()
            release.wait(timeout=2)
            raise sqlite3.OperationalError("failed during shutdown")

        repository = SimpleNamespace(prune=Mock(side_effect=prune))
        with self.assertLogs("u_calc.app", level="ERROR") as captured:
            task = asyncio.create_task(
                periodic_retention(repository, 730, interval_seconds=0),
            )
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)

        self.assertIn("failed during shutdown", "\n".join(captured.output))

    async def test_real_dispatcher_polls_transport_and_handles_start(self) -> None:
        """Exercise a clean-process lifecycle, matching one BotHost service process."""
        root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (str(root / "src"), environment.get("PYTHONPATH", "")))
        )
        completed = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(root / "tests" / "startup_contract.py")],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("startup-contract-ok", completed.stdout)

    async def test_invalid_database_path_fails_before_telegram_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_directory = Path(directory) / "database-is-a-directory"
            database_directory.mkdir()
            settings = Settings(
                bot_token="123:secret",
                database_path=database_directory,
            )

            with (
                patch("u_calc.app.Bot") as bot,
                self.assertRaisesRegex(RuntimeError, "Не удалось подготовить SQLite"),
            ):
                await run(settings)

            bot.assert_not_called()

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

                def register(self, value) -> None:
                    self.inner.append(value)

            class Dispatcher:
                def __init__(self) -> None:
                    self.message = Target()
                    self.callback_query = Target()
                    self.errors = Target()
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
            self.assertEqual(len(dispatcher.message.outer), 4)
            self.assertEqual(len(dispatcher.callback_query.outer), 4)
            self.assertEqual(
                [type(item).__name__ for item in dispatcher.message.outer],
                [
                    "PublicSafetyMiddleware",
                    "PrivateChatMiddleware",
                    "AccessMiddleware",
                    "UserMutationLockMiddleware",
                ],
            )
            self.assertEqual(
                [type(item).__name__ for item in dispatcher.callback_query.outer],
                [
                    "PublicSafetyMiddleware",
                    "PrivateChatMiddleware",
                    "AccessMiddleware",
                    "UserMutationLockMiddleware",
                ],
            )
            self.assertEqual(len(dispatcher.message.inner), 2)
            self.assertEqual(len(dispatcher.callback_query.inner), 3)
            self.assertEqual(len(dispatcher.errors.inner), 1)
            self.assertEqual(len(dispatcher.routers), 12)
            router_names = {router.name for router in dispatcher.routers}
            self.assertIn("u_calc.handlers.airflow", router_names)
            self.assertIn("u_calc.handlers.boundaries", router_names)
            self.assertIn("u_calc.handlers.climate", router_names)
            self.assertIn("u_calc.handlers.openings", router_names)
            self.assertIn("u_calc.handlers.result", router_names)
            self.assertIn("u_calc.handlers.walls", router_names)
            self.assertTrue(dispatcher.started)
            self.assertTrue(dispatcher.polling_kwargs["handle_signals"])
            self.assertEqual(bot.set_my_commands.await_count, 2)
            self.assertEqual(
                bot.set_my_commands.await_args_list[1].kwargs,
                {
                    "scope": bot.set_my_commands.await_args_list[0].kwargs["scope"],
                    "language_code": "uz",
                },
            )
            self.assertEqual(
                bot.set_my_commands.await_args_list[0].kwargs["scope"].type,
                "all_private_chats",
            )
            bot.session.close.assert_awaited_once()

    async def test_polling_cancellation_closes_bot_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                bot_token="123:secret",
                database_path=Path(directory) / "data" / "u_calc.db",
            )
            target = SimpleNamespace(
                outer_middleware=lambda value: None,
                middleware=lambda value: None,
                register=lambda value: None,
            )
            start_polling = AsyncMock(side_effect=asyncio.CancelledError)
            dispatcher = SimpleNamespace(
                message=target,
                callback_query=target,
                errors=target,
                include_router=lambda router: None,
                resolve_used_update_types=lambda: ["message", "callback_query"],
                start_polling=start_polling,
            )
            bot = SimpleNamespace(
                set_my_commands=AsyncMock(),
                session=SimpleNamespace(close=AsyncMock()),
            )

            with (
                patch("u_calc.app.Dispatcher", return_value=dispatcher),
                patch("u_calc.app.Bot", return_value=bot),
                patch("u_calc.app.single_instance_lock", return_value=nullcontext()),
                self.assertRaises(asyncio.CancelledError),
            ):
                await run(settings)

            self.assertTrue(start_polling.await_args.kwargs["handle_signals"])
            bot.session.close.assert_awaited_once()

    async def test_bot_session_closes_when_command_registration_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                bot_token="123:secret",
                database_path=Path(directory) / "data" / "u_calc.db",
            )
            bot = SimpleNamespace(
                set_my_commands=AsyncMock(side_effect=RuntimeError("telegram unavailable")),
                session=SimpleNamespace(close=AsyncMock()),
            )
            with (
                patch("u_calc.app.Bot", return_value=bot),
                patch("u_calc.app.single_instance_lock", return_value=nullcontext()),
                self.assertRaisesRegex(RuntimeError, "telegram unavailable"),
            ):
                await run(settings)

            bot.session.close.assert_awaited_once()

    async def test_transient_command_menu_network_error_does_not_block_polling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                bot_token="123:secret",
                database_path=Path(directory) / "data" / "u_calc.db",
            )
            target = SimpleNamespace(
                outer_middleware=lambda value: None,
                middleware=lambda value: None,
                register=lambda value: None,
            )
            start_polling = AsyncMock()
            dispatcher = SimpleNamespace(
                message=target,
                callback_query=target,
                errors=target,
                include_router=lambda router: None,
                resolve_used_update_types=lambda: ["message", "callback_query"],
                start_polling=start_polling,
            )
            bot = SimpleNamespace(
                set_my_commands=AsyncMock(
                    side_effect=TelegramNetworkError(
                        method=Mock(), message="temporary transport failure"
                    )
                ),
                session=SimpleNamespace(close=AsyncMock()),
            )

            with (
                patch("u_calc.app.Dispatcher", return_value=dispatcher),
                patch("u_calc.app.Bot", return_value=bot),
                patch("u_calc.app.single_instance_lock", return_value=nullcontext()),
                self.assertLogs("u_calc.app", level="WARNING") as logs,
            ):
                await run(settings)

            start_polling.assert_awaited_once()
            bot.session.close.assert_awaited_once()
            self.assertIn("polling will retry network", "\n".join(logs.output))
