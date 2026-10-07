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

from .config import Settings
from .handlers.survey import router as survey_router
from .middleware import (
    AccessMiddleware,
    DraftPersistenceMiddleware,
    NavigationMiddleware,
    PublicSafetyMiddleware,
)
from .storage import CalculationRepository


async def run(settings: Settings | None = None) -> None:
    settings = settings or Settings.from_env()
    repository = CalculationRepository(settings.database_path)
    await asyncio.to_thread(repository.initialize)
    repository.prune(settings.history_retention_days)
    dispatcher = Dispatcher(repository=repository, settings=settings)
    access = AccessMiddleware(settings)
    public_safety = PublicSafetyMiddleware(settings)
    navigation = NavigationMiddleware()
    drafts = DraftPersistenceMiddleware(repository, settings.draft_ttl_days)
    dispatcher.message.outer_middleware(access)
    dispatcher.callback_query.outer_middleware(access)
    dispatcher.message.outer_middleware(public_safety)
    dispatcher.callback_query.outer_middleware(public_safety)
    dispatcher.message.middleware(navigation)
    dispatcher.callback_query.middleware(navigation)
    dispatcher.message.middleware(drafts)
    dispatcher.callback_query.middleware(drafts)
    dispatcher.include_router(survey_router)
    logger = logging.getLogger(__name__)
    with single_instance_lock(settings.database_path):
        logger.info("U-Calc starting long polling database=%s", settings.database_path)
        await dispatcher.start_polling(
            Bot(settings.bot_token),
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
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
    settings = Settings.from_env()
    logging.basicConfig(level=settings.logging_level)
    asyncio.run(run(settings))
