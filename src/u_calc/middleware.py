from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, TelegramObject

from .config import Settings


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


def _is_navigation_event(event: TelegramObject) -> bool:
    if isinstance(event, CallbackQuery):
        return bool(event.data and event.data.startswith("nav:"))
    text = getattr(event, "text", None) or ""
    command = text.split(maxsplit=1)[0].split("@", 1)[0].casefold()
    return command in {"/start", "/new", "/back", "/cancel"}
