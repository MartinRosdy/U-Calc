import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, TelegramObject

from .config import Settings
from .storage import CalculationRepository


class AccessMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is not None and not self.settings.is_user_allowed(user.id):
            text = "Доступ к U-Calc ограничен владельцем бота."
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            else:
                answer = getattr(event, "answer", None)
                if answer is not None:
                    await answer(text)
            return None
        return await handler(event, data)


class PublicSafetyMiddleware(BaseMiddleware):
    """Bound input size and per-user update rate for public deployments."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.events: dict[int, deque[float]] = defaultdict(deque)
        self.audit = logging.getLogger("u_calc.audit")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)
        if not isinstance(event, CallbackQuery) and len(getattr(event, "text", "") or "") > (
            self.settings.max_message_length
        ):
            await event.answer(
                f"Сообщение слишком длинное. Максимум {self.settings.max_message_length} символов."
            )
            self.audit.warning("oversized_input user_id=%s", user.id)
            return None
        now = time.monotonic()
        events = self.events[user.id]
        while events and events[0] <= now - 60:
            events.popleft()
        if len(events) >= self.settings.rate_limit_per_minute:
            text = "Слишком много действий. Подождите минуту и продолжите."
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            else:
                await event.answer(text)
            self.audit.warning("rate_limited user_id=%s", user.id)
            return None
        events.append(now)
        self.audit.info(
            "telegram_action user_id=%s kind=%s",
            user.id,
            type(event).__name__,
        )
        return await handler(event, data)


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
        else:
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
