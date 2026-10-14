import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery

from u_calc.config import Settings
from u_calc.middleware import (
    AccessMiddleware,
    CallbackKeyboardCleanupMiddleware,
    DraftPersistenceMiddleware,
    NavigationMiddleware,
    PrivateChatMiddleware,
    PublicSafetyMiddleware,
    UserMutationLockMiddleware,
    _is_navigation_event,
)
from u_calc.states import Survey
from u_calc.storage import CalculationRepository


class FakeEvent:
    def __init__(self, text: str, user_id: int = 1) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append((text, kwargs))


class PublicSafetyMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_message_is_rejected_before_handler(self) -> None:
        middleware = PublicSafetyMiddleware(Settings(bot_token="secret", max_message_length=100))
        event = FakeEvent("x" * 101)
        called = False

        async def handler(_event, _data):
            nonlocal called
            called = True

        await middleware(handler, event, {})
        self.assertFalse(called)
        self.assertIn("слишком длинное", event.answers[0][0])

    async def test_rate_limit_is_per_user(self) -> None:
        middleware = PublicSafetyMiddleware(Settings(bot_token="secret", rate_limit_per_minute=5))
        calls = 0

        async def handler(_event, _data):
            nonlocal calls
            calls += 1

        for _ in range(6):
            event = FakeEvent("ok", user_id=10)
            await middleware(handler, event, {})
        await middleware(handler, FakeEvent("ok", user_id=20), {})
        self.assertEqual(calls, 6)
        self.assertIn("Слишком много", event.answers[0][0])

    async def test_global_rate_limit_bounds_many_distinct_users(self) -> None:
        middleware = PublicSafetyMiddleware(
            Settings(
                bot_token="secret",
                rate_limit_per_minute=30,
                global_rate_limit_per_minute=2,
            )
        )
        handler = AsyncMock(return_value="ok")

        first = FakeEvent("ok", user_id=10)
        second = FakeEvent("ok", user_id=20)
        blocked = FakeEvent("ok", user_id=30)
        self.assertEqual(await middleware(handler, first, {}), "ok")
        self.assertEqual(await middleware(handler, second, {}), "ok")
        self.assertIsNone(await middleware(handler, blocked, {}))

        self.assertEqual(handler.await_count, 2)
        self.assertEqual(len(middleware.global_events), 2)
        self.assertEqual(set(middleware.events), {10, 20})
        self.assertIn("временно занят", blocked.answers[-1][0])

    async def test_global_limit_does_not_allocate_buckets_or_rows_for_blocked_users(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "rate-limit.db"
            repository = CalculationRepository(database)
            repository.initialize()
            middleware = PublicSafetyMiddleware(
                Settings(
                    bot_token="secret",
                    rate_limit_per_minute=30,
                    global_rate_limit_per_minute=2,
                ),
                repository,
            )
            handler = AsyncMock(return_value="ok")

            for user_id in range(100, 200):
                await middleware(handler, FakeEvent("ok", user_id=user_id), {})

            self.assertEqual(handler.await_count, 2)
            self.assertEqual(len(middleware.global_events), 2)
            self.assertEqual(set(middleware.events), {100, 101})
            with sqlite3.connect(database) as connection:
                saved_users = connection.execute(
                    "SELECT COUNT(*) FROM user_settings"
                ).fetchone()[0]
            self.assertEqual(saved_users, 0)

    async def test_rejected_attempts_consume_global_budget_and_overload_replies_are_bounded(
        self,
    ) -> None:
        middleware = PublicSafetyMiddleware(
            Settings(
                bot_token="secret",
                rate_limit_per_minute=1,
                global_rate_limit_per_minute=3,
            )
        )
        handler = AsyncMock(return_value="ok")
        accepted = FakeEvent("ok", user_id=10)
        per_user_blocked = FakeEvent("ok", user_id=10)
        fills_budget = FakeEvent("ok", user_id=20)
        overload_notice = FakeEvent("ok", user_id=30)
        silently_dropped = FakeEvent("ok", user_id=40)

        with patch("u_calc.middleware.time.monotonic", return_value=100.0):
            await middleware(handler, accepted, {})
            await middleware(handler, per_user_blocked, {})
            await middleware(handler, fills_budget, {})
            await middleware(handler, overload_notice, {})
            await middleware(handler, silently_dropped, {})

        self.assertEqual(handler.await_count, 2)
        self.assertEqual(len(middleware.global_events), 3)
        self.assertIn("Слишком много", per_user_blocked.answers[-1][0])
        self.assertIn("временно занят", overload_notice.answers[-1][0])
        self.assertEqual(silently_dropped.answers, [])
        self.assertNotIn(30, middleware.events)
        self.assertNotIn(40, middleware.events)

    async def test_inactive_user_buckets_are_removed(self) -> None:
        middleware = PublicSafetyMiddleware(Settings(bot_token="secret"))

        async def handler(_event, _data):
            return None

        with patch("u_calc.middleware.time.monotonic", side_effect=[1.0, 62.0]):
            await middleware(handler, FakeEvent("ok", user_id=10), {})
            await middleware(handler, FakeEvent("ok", user_id=20), {})

        self.assertNotIn(10, middleware.events)
        self.assertIn(20, middleware.events)

    async def test_event_without_user_and_callback_rate_limit_paths(self) -> None:
        middleware = PublicSafetyMiddleware(Settings(bot_token="secret", rate_limit_per_minute=1))
        calls = 0

        async def handler(_event, _data):
            nonlocal calls
            calls += 1
            return "ok"

        self.assertEqual(await middleware(handler, SimpleNamespace(), {}), "ok")
        callback = Mock(spec=CallbackQuery)
        callback.from_user = SimpleNamespace(id=50)
        callback.answer = AsyncMock()
        await middleware(handler, callback, {})
        await middleware(handler, callback, {})
        callback.answer.assert_awaited_with(
            "Слишком много действий. Подождите минуту и продолжите.", show_alert=True
        )
        self.assertEqual(calls, 2)

    async def test_expensive_calculations_have_a_separate_limit(self) -> None:
        middleware = PublicSafetyMiddleware(
            Settings(
                bot_token="secret",
                rate_limit_per_minute=30,
                calculation_rate_limit_per_minute=2,
            )
        )
        calls = 0

        async def handler(_event, _data):
            nonlocal calls
            calls += 1

        callbacks = []
        for _ in range(3):
            callback = Mock(spec=CallbackQuery)
            callback.from_user = SimpleNamespace(id=70)
            callback.data = "confirm:calculate"
            callback.answer = AsyncMock()
            callbacks.append(callback)
            await middleware(handler, callback, {})

        self.assertEqual(calls, 2)
        callbacks[-1].answer.assert_awaited_with(
            "Слишком много расчётов. Подождите минуту перед повторным запуском.",
            show_alert=True,
        )
        self.assertEqual(len(middleware.calculations[70]), 2)


class AccessAndStateMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.storage = MemoryStorage()
        self.state = FSMContext(
            storage=self.storage,
            key=StorageKey(bot_id=1, chat_id=10, user_id=10),
        )

    async def asyncTearDown(self) -> None:
        await self.storage.close()

    async def test_access_rejects_message_and_callback_but_allows_owner(self) -> None:
        middleware = AccessMiddleware(
            Settings(bot_token="secret", allowed_user_ids=frozenset({10}))
        )
        calls = 0

        async def handler(_event, _data):
            nonlocal calls
            calls += 1
            return "allowed"

        blocked = FakeEvent("x", user_id=11)
        self.assertIsNone(await middleware(handler, blocked, {}))
        self.assertIn("ограничен", blocked.answers[-1][0])

        callback = Mock(spec=CallbackQuery)
        callback.from_user = SimpleNamespace(id=11)
        callback.answer = AsyncMock()
        self.assertIsNone(await middleware(handler, callback, {}))
        callback.answer.assert_awaited_with(
            "Доступ к U-Calc ограничен владельцем бота.", show_alert=True
        )
        self.assertEqual(await middleware(handler, FakeEvent("x", user_id=10), {}), "allowed")
        self.assertEqual(calls, 1)

    async def test_private_chat_gate_blocks_groups_for_messages_and_callbacks(self) -> None:
        middleware = PrivateChatMiddleware()
        handler = AsyncMock(return_value="allowed")

        group_message = FakeEvent("/start", user_id=10)
        group_message.chat = SimpleNamespace(type="group")
        self.assertIsNone(await middleware(handler, group_message, {}))
        self.assertIn("только в личном чате", group_message.answers[-1][0])

        callback = Mock(spec=CallbackQuery)
        callback.from_user = SimpleNamespace(id=10)
        callback.message = SimpleNamespace(chat=SimpleNamespace(type="supergroup"))
        callback.answer = AsyncMock()
        self.assertIsNone(await middleware(handler, callback, {}))
        callback.answer.assert_awaited_once_with(
            "U-Calc работает только в личном чате. Откройте диалог с ботом, чтобы данные "
            "объекта и PDF не попали в общий чат.",
            show_alert=True,
        )

        private_message = FakeEvent("/start", user_id=10)
        private_message.chat = SimpleNamespace(type="private")
        self.assertEqual(await middleware(handler, private_message, {}), "allowed")
        handler.assert_awaited_once()

    async def test_private_chat_gate_uses_saved_uzbek_locale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "locale.db")
            repository.initialize()
            repository.set_locale(10, "uz")
            middleware = PrivateChatMiddleware(repository)
            group_message = FakeEvent("/start", user_id=10)
            group_message.chat = SimpleNamespace(type="group")

            await middleware(AsyncMock(), group_message, {})

            self.assertIn("faqat shaxsiy chatda", group_message.answers[-1][0])

    async def test_access_and_public_limits_use_saved_uzbek_locale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "locale.db")
            repository.initialize()
            repository.set_locale(11, "uz")

            access = AccessMiddleware(
                Settings(bot_token="secret", allowed_user_ids=frozenset({10})),
                repository,
            )
            blocked = FakeEvent("x", user_id=11)
            await access(AsyncMock(), blocked, {})
            self.assertIn("cheklangan", blocked.answers[-1][0])

            safety = PublicSafetyMiddleware(
                Settings(bot_token="secret", max_message_length=3), repository
            )
            oversized = FakeEvent("uzun", user_id=11)
            await safety(AsyncMock(), oversized, {})
            self.assertIn("Xabar juda uzun", oversized.answers[-1][0])

    async def test_navigation_records_only_real_state_transitions(self) -> None:
        middleware = NavigationMiddleware()
        await self.state.set_state(Survey.indoor)
        await self.state.update_data(outdoor=-14)

        async def transition(_event, _data):
            await self.state.update_data(indoor=24)
            await self.state.set_state(Survey.dimensions)
            return "moved"

        event = FakeEvent("24", user_id=10)
        result = await middleware(transition, event, {"state": self.state})
        self.assertEqual(result, "moved")
        stack = (await self.state.get_data())["_back_stack"]
        self.assertEqual(stack[-1]["state"], Survey.indoor.state)
        self.assertEqual(stack[-1]["data"], {"outdoor": -14})

        async def validation_error(_event, _data):
            return "retry"

        before = list(stack)
        await middleware(validation_error, event, {"state": self.state})
        self.assertEqual((await self.state.get_data())["_back_stack"], before)

        await middleware(transition, FakeEvent("/back", user_id=10), {"state": self.state})
        self.assertTrue(_is_navigation_event(FakeEvent("/cancel@u_calc", user_id=10)))
        self.assertFalse(_is_navigation_event(FakeEvent("answer", user_id=10)))

    async def test_draft_persistence_saves_and_deletes_after_clear(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "draft.db")
            repository.initialize()
            middleware = DraftPersistenceMiddleware(repository, ttl_days=7)
            await self.state.set_state(Survey.indoor)
            await self.state.update_data(outdoor=-14)
            event = FakeEvent("24", user_id=10)

            async def keep_state(_event, _data):
                await self.state.update_data(indoor=24)
                return "saved"

            result = await middleware(keep_state, event, {"state": self.state})
            self.assertEqual(result, "saved")
            draft = repository.load_draft(10)
            self.assertEqual(draft.current_step, Survey.indoor.state)
            self.assertEqual(draft.data["indoor"], 24)

            async def clear_state(_event, _data):
                await self.state.clear()

            await middleware(clear_state, event, {"state": self.state})
            self.assertIsNone(repository.load_draft(10))
            self.assertEqual(await middleware(keep_state, SimpleNamespace(), {}), "saved")

    async def test_profile_state_is_not_mistaken_for_calculation_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "draft.db")
            repository.initialize()
            middleware = DraftPersistenceMiddleware(repository)
            event = FakeEvent("Профиль", user_id=10)

            async def profile_flow(_event, _data):
                await self.state.set_state("ProfileFlow:create_name")

            await middleware(profile_flow, event, {"state": self.state})
            self.assertIsNone(repository.load_draft(10))


class CallbackKeyboardCleanupMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _callback(*, has_markup: bool = True) -> Mock:
        callback = Mock(spec=CallbackQuery)
        callback.message = SimpleNamespace(
            reply_markup=object() if has_markup else None,
            edit_reply_markup=AsyncMock(),
        )
        return callback

    async def test_successful_callback_closes_the_used_keyboard(self) -> None:
        middleware = CallbackKeyboardCleanupMiddleware()
        callback = self._callback()

        async def handler(_event, _data):
            return "done"

        result = await middleware(handler, callback, {})

        self.assertEqual(result, "done")
        callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)

    async def test_failed_action_keeps_keyboard_available_for_retry(self) -> None:
        middleware = CallbackKeyboardCleanupMiddleware()
        callback = self._callback()

        async def handler(_event, _data):
            raise RuntimeError("failed")

        with self.assertRaisesRegex(RuntimeError, "failed"):
            await middleware(handler, callback, {})
        callback.message.edit_reply_markup.assert_not_awaited()

    async def test_missing_keyboard_is_not_edited_and_telegram_rejection_is_nonfatal(self) -> None:
        middleware = CallbackKeyboardCleanupMiddleware()

        async def handler(_event, _data):
            return "done"

        without_markup = self._callback(has_markup=False)
        await middleware(handler, without_markup, {})
        without_markup.message.edit_reply_markup.assert_not_awaited()

        rejected = self._callback()
        rejected.message.edit_reply_markup.side_effect = TelegramBadRequest(
            method=Mock(), message="message is not modified"
        )
        self.assertEqual(await middleware(handler, rejected, {}), "done")


class UserMutationLockMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_user_updates_are_serialized_and_lock_is_cleaned(self) -> None:
        middleware = UserMutationLockMiddleware()
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        order: list[str] = []

        async def first_handler(_event, _data):
            order.append("first:start")
            first_entered.set()
            await release_first.wait()
            order.append("first:end")

        async def second_handler(_event, _data):
            order.append("second")

        first = asyncio.create_task(middleware(first_handler, FakeEvent("one", 10), {}))
        await first_entered.wait()
        second = asyncio.create_task(middleware(second_handler, FakeEvent("two", 10), {}))
        await asyncio.sleep(0)
        self.assertEqual(order, ["first:start"])
        release_first.set()
        await asyncio.gather(first, second)
        self.assertEqual(order, ["first:start", "first:end", "second"])
        self.assertEqual(middleware._locks, {})

    async def test_different_users_do_not_block_each_other(self) -> None:
        middleware = UserMutationLockMiddleware()
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        second_entered = asyncio.Event()

        async def first_handler(_event, _data):
            first_entered.set()
            await release_first.wait()

        async def second_handler(_event, _data):
            second_entered.set()

        first = asyncio.create_task(middleware(first_handler, FakeEvent("one", 10), {}))
        await first_entered.wait()
        await middleware(second_handler, FakeEvent("two", 20), {})
        self.assertTrue(second_entered.is_set())
        release_first.set()
        await first
