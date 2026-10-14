"""Application bootstrap: dependencies, middleware and polling lifecycle."""

import asyncio
import logging
import sqlite3
from contextlib import suppress
from urllib.parse import quote

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats
from aiogram.utils.token import TokenValidationError

from .config import Settings
from .handlers.airflow import router as airflow_router
from .handlers.boundaries import router as boundaries_router
from .handlers.bridge_editor import router as bridge_editor_router
from .handlers.climate import router as climate_router
from .handlers.history import router as history_router
from .handlers.menu import router as menu_router
from .handlers.opening_editor import router as opening_editor_router
from .handlers.openings import router as openings_router
from .handlers.result import router as result_router
from .handlers.survey import global_error_handler
from .handlers.survey import router as survey_router
from .handlers.wall_editor import router as wall_editor_router
from .handlers.walls import router as walls_router
from .locking import single_instance_lock
from .middleware import (
    AccessMiddleware,
    CallbackKeyboardCleanupMiddleware,
    DraftPersistenceMiddleware,
    NavigationMiddleware,
    PrivateChatMiddleware,
    PublicSafetyMiddleware,
    UserMutationLockMiddleware,
)
from .storage import CalculationRepository

RETENTION_INTERVAL_SECONDS = 24 * 60 * 60


class SecretRedactingFormatter(logging.Formatter):
    """Wrap a formatter and redact secrets from messages and exception tracebacks."""

    def __init__(self, delegate: logging.Formatter, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self.delegate = delegate
        variants = {
            variant
            for secret in secrets
            if secret
            for variant in (secret, quote(secret, safe=""))
            if variant
        }
        self.secrets = tuple(sorted(variants, key=len, reverse=True))

    def format(self, record: logging.LogRecord) -> str:
        rendered = self.delegate.format(record)
        for secret in self.secrets:
            rendered = rendered.replace(secret, "[REDACTED]")
        return rendered


def install_secret_redaction(secret: str) -> None:
    """Protect every configured root handler before Telegram networking starts."""
    root = logging.getLogger()
    for handler in root.handlers:
        formatter = handler.formatter or logging.Formatter()
        if isinstance(formatter, SecretRedactingFormatter):
            continue
        handler.setFormatter(SecretRedactingFormatter(formatter, (secret,)))


async def periodic_retention(
    repository: CalculationRepository,
    retention_days: int,
    *,
    interval_seconds: float = RETENTION_INTERVAL_SECONDS,
) -> None:
    """Enforce retention while a long-polling process remains alive for months."""
    logger = logging.getLogger(__name__)
    while True:
        await asyncio.sleep(interval_seconds)
        work = asyncio.create_task(
            asyncio.to_thread(repository.prune, retention_days),
            name="u-calc-retention-sqlite",
        )
        try:
            # asyncio cannot stop a function that is already running in a worker
            # thread. Shield it and finish the SQLite transaction before releasing
            # the process lock during shutdown.
            deleted = await asyncio.shield(work)
        except asyncio.CancelledError:
            try:
                await work
            except (OSError, sqlite3.Error, RuntimeError):
                logger.exception("Inflight SQLite retention failed during shutdown")
            raise
        except (OSError, sqlite3.Error, RuntimeError):
            logger.exception("Periodic SQLite retention failed; the next run will retry")
        else:
            logger.info("Periodic SQLite retention completed deleted_calculations=%s", deleted)


async def run(settings: Settings | None = None) -> None:
    settings = settings or Settings.from_env()
    install_secret_redaction(settings.bot_token)
    logger = logging.getLogger(__name__)
    with single_instance_lock(settings.database_path):
        repository = CalculationRepository(settings.database_path)
        try:
            await asyncio.to_thread(repository.initialize)
            await asyncio.to_thread(repository.prune, settings.history_retention_days)
        except (OSError, sqlite3.Error) as exc:
            raise RuntimeError(
                f"Не удалось подготовить SQLite {settings.database_path}: {exc}"
            ) from exc
        dispatcher = Dispatcher(repository=repository, settings=settings)
        dispatcher.errors.register(global_error_handler)
        private_chats = PrivateChatMiddleware(repository)
        access = AccessMiddleware(settings, repository)
        public_safety = PublicSafetyMiddleware(settings, repository)
        mutations = UserMutationLockMiddleware()
        navigation = NavigationMiddleware()
        drafts = DraftPersistenceMiddleware(repository, settings.draft_ttl_days)
        callback_cleanup = CallbackKeyboardCleanupMiddleware()
        dispatcher.message.outer_middleware(public_safety)
        dispatcher.callback_query.outer_middleware(public_safety)
        dispatcher.message.outer_middleware(private_chats)
        dispatcher.callback_query.outer_middleware(private_chats)
        dispatcher.message.outer_middleware(access)
        dispatcher.callback_query.outer_middleware(access)
        dispatcher.message.outer_middleware(mutations)
        dispatcher.callback_query.outer_middleware(mutations)
        dispatcher.message.middleware(navigation)
        dispatcher.callback_query.middleware(navigation)
        dispatcher.message.middleware(drafts)
        dispatcher.callback_query.middleware(drafts)
        dispatcher.callback_query.middleware(callback_cleanup)
        dispatcher.include_router(menu_router)
        dispatcher.include_router(history_router)
        dispatcher.include_router(climate_router)
        dispatcher.include_router(opening_editor_router)
        dispatcher.include_router(openings_router)
        dispatcher.include_router(bridge_editor_router)
        dispatcher.include_router(wall_editor_router)
        dispatcher.include_router(walls_router)
        dispatcher.include_router(airflow_router)
        dispatcher.include_router(boundaries_router)
        dispatcher.include_router(result_router)
        dispatcher.include_router(survey_router)
        logger.info("U-Calc starting long polling database=%s", settings.database_path)
        bot = Bot(settings.bot_token)
        retention_task = asyncio.create_task(
            periodic_retention(repository, settings.history_retention_days),
            name="u-calc-retention",
        )
        private_scope = BotCommandScopeAllPrivateChats()
        try:
            try:
                await bot.set_my_commands(
                    [
                        BotCommand(command="start", description="Главное меню"),
                        BotCommand(command="new", description="Новый расчёт"),
                        BotCommand(command="profiles", description="Профили расчёта"),
                        BotCommand(command="history", description="История расчётов"),
                        BotCommand(command="resume", description="Продолжить черновик"),
                        BotCommand(command="cancel", description="Отменить расчёт"),
                        BotCommand(command="help", description="Помощь и методика"),
                        BotCommand(
                            command="delete_my_data", description="Удалить все мои данные"
                        ),
                    ],
                    scope=private_scope,
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
                        BotCommand(
                            command="delete_my_data",
                            description="Barcha ma’lumotlarni o‘chirish",
                        ),
                    ],
                    scope=private_scope,
                    language_code="uz",
                )
            except TelegramNetworkError as exc:
                logger.warning(
                    "Telegram command menu was not updated; polling will retry network: %s",
                    exc,
                )
            await dispatcher.start_polling(
                bot,
                allowed_updates=dispatcher.resolve_used_update_types(),
                handle_signals=True,
            )
        finally:
            retention_task.cancel()
            with suppress(asyncio.CancelledError):
                await retention_task
            await bot.session.close()
        logger.info("U-Calc polling stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        settings = Settings.from_env()
    except RuntimeError as exc:
        logging.getLogger(__name__).critical("Ошибка конфигурации: %s", exc)
        raise SystemExit(2) from None
    install_secret_redaction(settings.bot_token)
    logging.getLogger().setLevel(settings.logging_level)
    try:
        asyncio.run(run(settings))
    except (TelegramAPIError, TokenValidationError) as exc:
        logging.getLogger(__name__).critical(
            "Ошибка запуска Telegram: %s: %s",
            type(exc).__name__,
            exc,
        )
        raise SystemExit(2) from None
    except RuntimeError as exc:
        logging.getLogger(__name__).critical("U-Calc не запущен: %s", exc)
        raise SystemExit(2) from None
