"""Shared Telegram input helpers for survey feature routers."""

import math
import unicodedata

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..catalog import CATALOG_VERSION, ENGINE_VERSION
from ..i18n import translate as tr
from ..storage import NORMS_VERSION


def product_identity(locale: str) -> str:
    """Render support-visible version identifiers for the running product."""
    return tr(
        "help.version",
        locale,
        engine=ENGINE_VERSION,
        catalog=CATALOG_VERSION,
        norms=NORMS_VERSION,
    )


async def state_locale(state: FSMContext) -> str:
    return str((await state.get_data()).get("locale") or "ru")


async def input_error(
    message: Message,
    exc: ValueError,
    state: FSMContext | None = None,
) -> None:
    locale = await state_locale(state) if state is not None else "ru"
    detail = str(exc) if locale == "ru" else tr("common.invalid_input", locale)
    await message.answer(tr("common.retry", locale, message=detail))


def nonnegative(text: str | None) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите число, например 12,5") from exc
    if not math.isfinite(value):
        raise ValueError("Значение должно быть конечным числом")
    if not 0 <= value <= 100_000:
        raise ValueError("Значение должно быть от 0 до 100 000")
    return value


def conductivity(text: str) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите λ числом, например 0,041") from exc
    if not math.isfinite(value) or not 0.005 <= value <= 5:
        raise ValueError("λ должна быть от 0,005 до 5 Вт/(м·К)")
    return value


def parse_count(text: str) -> int:
    try:
        value = int(text.strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите целое количество, например 3") from exc
    if value < 0 or value > 500:
        raise ValueError("Количество должно быть от 0 до 500")
    return value


def material_name(key: str, locale: str) -> str:
    return tr(f"material.{key}", locale)


def bounded_text(
    text: str | None,
    *,
    minimum: int,
    maximum: int,
    label: str = "Текст",
) -> str:
    value = (text or "").strip()
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} должен содержать от {minimum} до {maximum} символов")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError(f"{label} содержит недопустимые управляющие символы")
    return value
