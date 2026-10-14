import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, TelegramObject

from .config import Settings
from .i18n import translate as tr
from .storage import CalculationRepository


class AccessMiddleware(BaseMiddleware):
    def __init__(
        self,
        settings: Settings,
        repository: CalculationRepository | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository

    async def _locale(self, user_id: int) -> str:
        if self.repository is None:
            return "ru"
        return await asyncio.to_thread(self.repository.get_saved_locale, user_id)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is not None and not self.settings.is_user_allowed(user.id):
            text = tr("safety.access_denied", await self._locale(user.id))
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            else:
                answer = getattr(event, "answer", None)
                if answer is not None:
                    await answer(text)
            return None
        return await handler(event, data)


class PrivateChatMiddleware(BaseMiddleware):
    """Keep customer calculations and reports out of group and channel chats."""

    def __init__(self, repository: CalculationRepository | None = None) -> None:
        self.repository = repository

    async def _locale(self, user_id: int) -> str:
        if self.repository is None:
            return "ru"
        return await asyncio.to_thread(self.repository.get_saved_locale, user_id)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        message = event.message if isinstance(event, CallbackQuery) else event
        chat = getattr(message, "chat", None)
        chat_type = getattr(chat, "type", None)
        chat_type = getattr(chat_type, "value", chat_type)
        if chat_type is None or chat_type == "private":
            return await handler(event, data)

        user = getattr(event, "from_user", None)
        locale = await self._locale(user.id) if user is not None else "ru"
        text = tr("safety.private_chat_only", locale)
        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
        else:
            answer = getattr(event, "answer", None)
            if answer is not None:
                await answer(text)
        return None


class PublicSafetyMiddleware(BaseMiddleware):
    """Bound input size and per-user update rate for public deployments."""

    def __init__(
        self,
        settings: Settings,
        repository: CalculationRepository | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.events: dict[int, deque[float]] = {}
        self.global_events: deque[float] = deque()
        self.calculations: dict[int, deque[float]] = {}
        self._last_cleanup = 0.0
        self._last_overload_notice = 0.0
        self.audit = logging.getLogger("u_calc.audit")

    async def _locale(self, user_id: int) -> str:
        if self.repository is None:
            return "ru"
        return await asyncio.to_thread(self.repository.get_saved_locale, user_id)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)
        now = time.monotonic()
        if now - self._last_cleanup >= 60:
            self._prune_inactive_users(now)
            self._last_cleanup = now
        while self.global_events and self.global_events[0] <= now - 60:
            self.global_events.popleft()
        if len(self.global_events) >= self.settings.global_rate_limit_per_minute:
            # Under overload, even rejection replies, locale lookups and log writes must
            # remain bounded. Notify at most once per second for the whole process.
            if now - self._last_overload_notice >= 1.0:
                self._last_overload_notice = now
                text = tr("safety.system_busy", await self._locale(user.id))
                if isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
                else:
                    await event.answer(text)
                self.audit.warning("global_rate_limited user_id=%s", user.id)
            return None
        # Count every attempt that reaches this process, including malformed input and
        # per-user rejections, so abusive traffic cannot evade the global budget.
        self.global_events.append(now)
        events = self.events.setdefault(user.id, deque())
        while events and events[0] <= now - 60:
            events.popleft()
        if len(events) >= self.settings.rate_limit_per_minute:
            text = tr("safety.rate_limited", await self._locale(user.id))
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            else:
                await event.answer(text)
            self.audit.warning("rate_limited user_id=%s", user.id)
            return None
        events.append(now)
        if not isinstance(event, CallbackQuery) and len(getattr(event, "text", "") or "") > (
            self.settings.max_message_length
        ):
            await event.answer(
                tr(
                    "safety.message_too_long",
                    await self._locale(user.id),
                    limit=self.settings.max_message_length,
                )
            )
            self.audit.warning("oversized_input user_id=%s", user.id)
            return None
        if isinstance(event, CallbackQuery) and getattr(event, "data", None) == "confirm:calculate":
            calculations = self.calculations.setdefault(user.id, deque())
            while calculations and calculations[0] <= now - 60:
                calculations.popleft()
            if len(calculations) >= self.settings.calculation_rate_limit_per_minute:
                await event.answer(
                    tr(
                        "safety.calculation_rate_limited",
                        await self._locale(user.id),
                    ),
                    show_alert=True,
                )
                self.audit.warning("calculation_rate_limited user_id=%s", user.id)
                return None
            calculations.append(now)
        self.audit.info(
            "telegram_action user_id=%s kind=%s",
            user.id,
            type(event).__name__,
        )
        return await handler(event, data)

    def _prune_inactive_users(self, now: float) -> None:
        """Discard expired rate-limit buckets so one-time users do not leak memory."""
        cutoff = now - 60
        for user_id, events in list(self.events.items()):
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                del self.events[user_id]
        for user_id, calculations in list(self.calculations.items()):
            while calculations and calculations[0] <= cutoff:
                calculations.popleft()
            if not calculations:
                del self.calculations[user_id]


class UserMutationLockMiddleware(BaseMiddleware):
    """Serialize state-changing updates for each user without blocking other users."""

    def __init__(self) -> None:
        self._locks: dict[int, tuple[asyncio.Lock, int]] = {}
        self._registry_lock = asyncio.Lock()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)
        async with self._registry_lock:
            lock, users = self._locks.get(user.id, (asyncio.Lock(), 0))
            self._locks[user.id] = (lock, users + 1)
        try:
            async with lock:
                return await handler(event, data)
        finally:
            async with self._registry_lock:
                _, users = self._locks[user.id]
                if users == 1:
                    self._locks.pop(user.id, None)
                else:
                    self._locks[user.id] = (lock, users - 1)


class CallbackKeyboardCleanupMiddleware(BaseMiddleware):
    """Remove a successfully used inline keyboard so old prompts stop looking active."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)
        if not isinstance(event, CallbackQuery):
            return result
        message = event.message
        edit_reply_markup = getattr(message, "edit_reply_markup", None)
        if message is None or getattr(message, "reply_markup", None) is None:
            return result
        if edit_reply_markup is None:
            return result
        try:
            await edit_reply_markup(reply_markup=None)
        except TelegramAPIError as exc:
            # The action itself already succeeded. Cleanup is best-effort because
            # Telegram can reject edits of old or concurrently changed messages.
            self.logger.debug("Could not close callback keyboard: %s", exc)
        return result


class NavigationMiddleware(BaseMiddleware):
    """Keep compact FSM snapshots so /back can restore the previous survey step."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state = data.get("state")
        if not isinstance(state, FSMContext) or _is_navigation_event(event):
            return await handler(event, data)

        previous_state = await state.get_state()
        previous_data = await state.get_data()
        result = await handler(event, data)
        current_state = await state.get_state()
        if previous_state and current_state and previous_state != current_state:
            current_data = await state.get_data()
            stack = list(current_data.get("_back_stack", previous_data.get("_back_stack", [])))
            snapshot_data = {
                key: value for key, value in previous_data.items() if key != "_back_stack"
            }
            stack.append({"state": previous_state, "data": snapshot_data})
            await state.update_data(_back_stack=stack[-50:])
        return result


class DraftPersistenceMiddleware(BaseMiddleware):
    """Persist the current FSM snapshot after every successful user action."""

    def __init__(self, repository: CalculationRepository, ttl_days: int = 30) -> None:
        self.repository = repository
        self.ttl_days = ttl_days

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)
        state = data.get("state")
        user = getattr(event, "from_user", None)
        if not isinstance(state, FSMContext) or user is None:
            return result
        current_state = await state.get_state()
        if current_state is None:
            await asyncio.to_thread(self.repository.delete_draft, user.id)
        elif current_state.startswith("Survey:"):
            state_data = await state.get_data()
            await asyncio.to_thread(
                self.repository.save_draft,
                user.id,
                current_state,
                state_data,
                ttl_days=self.ttl_days,
            )
        return result


def _is_navigation_event(event: TelegramObject) -> bool:
    if isinstance(event, CallbackQuery):
        return bool(event.data and event.data.startswith("nav:"))
    text = getattr(event, "text", None) or ""
    command = text.split(maxsplit=1)[0].split("@", 1)[0].casefold()
    return command in {"/start", "/new", "/back", "/cancel"}
