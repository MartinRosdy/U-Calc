"""Application bootstrap: dependencies, middleware and polling lifecycle."""

import asyncio
import fcntl
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from .config import Settings
from .handlers.bridge_editor import router as bridge_editor_router
from .handlers.history import router as history_router
from .handlers.menu import router as menu_router
from .handlers.opening_editor import router as opening_editor_router
from .handlers.survey import router as survey_router
from .handlers.wall_editor import router as wall_editor_router
from .middleware import (
    AccessMiddleware,
    DraftPersistenceMiddleware,
    NavigationMiddleware,
    PublicSafetyMiddleware,
    UserMutationLockMiddleware,
)
from .storage import CalculationRepository


async def run(settings: Settings | None = None) -> None:
    settings = settings or Settings.from_env()
    repository = CalculationRepository(settings.database_path)
    await asyncio.to_thread(repository.initialize)
    await asyncio.to_thread(repository.prune, settings.history_retention_days)
    dispatcher = Dispatcher(repository=repository, settings=settings)
    access = AccessMiddleware(settings, repository)
    public_safety = PublicSafetyMiddleware(settings, repository)
    mutations = UserMutationLockMiddleware()
    navigation = NavigationMiddleware()
    drafts = DraftPersistenceMiddleware(repository, settings.draft_ttl_days)
    dispatcher.message.outer_middleware(access)
    dispatcher.callback_query.outer_middleware(access)
    dispatcher.message.outer_middleware(public_safety)
    dispatcher.callback_query.outer_middleware(public_safety)
    dispatcher.message.outer_middleware(mutations)
    dispatcher.callback_query.outer_middleware(mutations)
    dispatcher.message.middleware(navigation)
    dispatcher.callback_query.middleware(navigation)
    dispatcher.message.middleware(drafts)
    dispatcher.callback_query.middleware(drafts)
    dispatcher.include_router(menu_router)
    dispatcher.include_router(history_router)
    dispatcher.include_router(opening_editor_router)
    dispatcher.include_router(bridge_editor_router)
    dispatcher.include_router(wall_editor_router)
    dispatcher.include_router(survey_router)
    logger = logging.getLogger(__name__)
    with single_instance_lock(settings.database_path):
        logger.info("U-Calc starting long polling database=%s", settings.database_path)
        bot = Bot(settings.bot_token)
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="new", description="Новый расчёт"),
                BotCommand(command="profiles", description="Профили расчёта"),
                BotCommand(command="history", description="История расчётов"),
                BotCommand(command="resume", description="Продолжить черновик"),
                BotCommand(command="cancel", description="Отменить расчёт"),
                BotCommand(command="help", description="Помощь и методика"),
            ]
        )
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Asosiy menyu"),
                BotCommand(command="new", description="Yangi hisob"),
                BotCommand(command="profiles", description="Hisob profillari"),
                BotCommand(command="history", description="Hisoblar tarixi"),
                BotCommand(command="resume", description="Qoralamani davom ettirish"),
                BotCommand(command="cancel", description="Hisobni bekor qilish"),
                BotCommand(command="help", description="Yordam va metodika"),
            ],
            language_code="uz",
        )
        try:
            await dispatcher.start_polling(
                bot,
                allowed_updates=dispatcher.resolve_used_update_types(),
            )
        finally:
            await bot.session.close()
        logger.info("U-Calc polling stopped")


@contextmanager
def single_instance_lock(database_path: Path) -> Iterator[IO[str]]:
    lock_path = database_path.with_suffix(database_path.suffix + ".polling.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stream = lock_path.open("w", encoding="utf-8")
    try:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Другой экземпляр U-Calc уже использует эту базу") from exc
        stream.write(str(os.getpid()))
        stream.flush()
        yield stream
    finally:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        settings = Settings.from_env()
    except RuntimeError as exc:
        logging.getLogger(__name__).critical("Ошибка конфигурации: %s", exc)
        raise SystemExit(2) from None
    logging.getLogger().setLevel(settings.logging_level)
    asyncio.run(run(settings))
