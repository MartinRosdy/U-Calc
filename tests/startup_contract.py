"""Clean-process aiogram startup contract invoked by ``test_app.py``."""

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetMe, GetUpdates, SendMessage, SetMyCommands
from aiogram.types import Message, Update, User

from u_calc.app import run
from u_calc.config import Settings


class MemoryTelegramSession(BaseSession):
    """Deterministic implementation of aiogram's transport boundary."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = []
        self.menu_sent = asyncio.Event()
        self.update_delivered = False
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def stream_content(self, *args, **kwargs):
        if False:  # pragma: no cover - makes this an async generator
            yield b""
        raise AssertionError("file streaming is not expected")

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SetMyCommands):
            return True
        if isinstance(method, GetMe):
            return User(
                id=123456789,
                is_bot=True,
                first_name="U-Calc Test",
                username="u_calc_test_bot",
            )
        if isinstance(method, GetUpdates):
            if self.update_delivered:
                await asyncio.Event().wait()
            self.update_delivered = True
            return [
                Update.model_validate(
                    {
                        "update_id": 7001,
                        "message": {
                            "message_id": 41,
                            "date": int(datetime.now(UTC).timestamp()),
                            "chat": {"id": 42, "type": "private"},
                            "from": {
                                "id": 42,
                                "is_bot": False,
                                "first_name": "Master",
                            },
                            "text": "/start",
                            "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
                        },
                    },
                    context={"bot": bot},
                )
            ]
        if isinstance(method, SendMessage):
            self.menu_sent.set()
            return Message.model_validate(
                {
                    "message_id": 42,
                    "date": int(datetime.now(UTC).timestamp()),
                    "chat": {"id": 42, "type": "private"},
                    "from": {
                        "id": 123456789,
                        "is_bot": True,
                        "first_name": "U-Calc Test",
                        "username": "u_calc_test_bot",
                    },
                    "text": method.text,
                },
                context={"bot": bot},
            )
        raise AssertionError(f"Unexpected Telegram method: {type(method).__name__}")


async def verify_startup() -> None:
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghi"
    session = MemoryTelegramSession()
    bot = Bot(token, session=session)
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "data" / "u_calc.db"
        settings = Settings(bot_token=token, database_path=database)
        with patch("u_calc.app.Bot", return_value=bot):
            polling = asyncio.create_task(run(settings))
            menu_waiter = asyncio.create_task(session.menu_sent.wait())
            done, _ = await asyncio.wait(
                {polling, menu_waiter},
                timeout=15,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if polling in done:
                await polling
                raise AssertionError("polling stopped before the /start menu was sent")
            if menu_waiter not in done:
                polling.cancel()
                raise AssertionError("timed out waiting for the /start menu")
            polling.cancel()
            try:
                await polling
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("polling cancellation did not propagate")

        assert database.exists()

    assert session.closed
    command_calls = [call for call in session.calls if isinstance(call, SetMyCommands)]
    assert len(command_calls) == 2
    assert all(call.scope.type == "all_private_chats" for call in command_calls)
    assert any(isinstance(call, GetMe) for call in session.calls)
    assert any(isinstance(call, GetUpdates) for call in session.calls)
    sent = next(call for call in session.calls if isinstance(call, SendMessage))
    assert sent.chat_id == 42
    assert "U-Calc" in sent.text
    assert sent.reply_markup is not None


if __name__ == "__main__":
    asyncio.run(verify_startup())
    print("startup-contract-ok")
