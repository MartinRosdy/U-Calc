"""Commands for viewing, comparing and deleting saved calculations."""

import asyncio
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ..config import Settings
from ..i18n import translate as tr
from ..keyboards import keyboard
from ..storage import CalculationRepository
from .common import product_identity

router = Router(name=__name__)

_COMPARISON_FIELDS = frozenset(
    {
        "air_changes",
        "building_type",
        "ceiling_boundary",
        "climate_key",
        "confirmed_design_c",
        "door_area",
        "door_groups",
        "floor_boundary",
        "height",
        "indoor",
        "infiltration_m3_h",
        "length",
        "linear_thermal_bridges",
        "mechanical_ventilation_m3_h",
        "natural_ventilation_m3_h",
        "object_name",
        "prepared_by",
        "safety_factor",
        "scenario",
        "wall_gross_area",
        "wall_groups",
        "width",
        "window_area",
        "window_groups",
    }
)


async def _locale(repository: CalculationRepository, user_id: int) -> str:
    settings = await asyncio.to_thread(repository.get_user_settings, user_id)
    return settings.locale


def _callback_calculation_id(callback: CallbackQuery) -> int | None:
    try:
        value = int(callback.data.rsplit(":", 1)[1])
    except (AttributeError, ValueError):
        return None
    return value if value > 0 else None


def _history_card_keyboard(calculation_id: int, locale: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr("history.report", locale),
                    callback_data=f"h:report:{calculation_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr("history.pdf", locale),
                    callback_data=f"h:pdf:{calculation_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr("history.copy", locale),
                    callback_data=f"h:copy:{calculation_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr("history.compare", locale),
                    callback_data=f"h:compare:{calculation_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr("history.delete", locale),
                    callback_data=f"h:delete:{calculation_id}",
                )
            ],
            [InlineKeyboardButton(text=tr("history.back", locale), callback_data="h:back")],
        ]
    )


def _comparison_label(key: str, locale: str) -> str:
    if key in _COMPARISON_FIELDS:
        return tr(f"history.field.{key}", locale)
    return tr("history.field.other", locale, name=key.replace("_", " "))


def _comparison_value(key: str, value: object, locale: str) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return tr("common.yes" if value else "common.no", locale)
    if isinstance(value, (dict, list, tuple)):
        count = len(value)
        return tr("history.value.collection", locale, count=count)
    if key == "building_type" and value in {"apartment", "house"}:
        return tr(f"survey.object.{value}", locale)
    if key == "scenario" and value in {"economy", "design", "extreme", "future"}:
        return tr(f"survey.scenario.{value}", locale)
    if key == "climate_key" and isinstance(value, str) and value in {
        "tashkent",
        "samarkand",
        "nukus",
    }:
        return tr(f"climate.{value}", locale)
    if isinstance(value, float):
        return f"{value:g}"
    rendered = str(value)
    return rendered if len(rendered) <= 80 else f"{rendered[:77]}…"


@router.callback_query(F.data.startswith("h:view:"))
async def calculation_card(
    callback: CallbackQuery,
    repository: CalculationRepository,
    settings: Settings,
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    calculation_id = _callback_calculation_id(callback)
    record = (
        await asyncio.to_thread(repository.get_for_user, callback.from_user.id, calculation_id)
        if calculation_id is not None
        else None
    )
    if record is None:
        await callback.answer(tr("history.not_found", locale), show_alert=True)
        return
    created = (
        datetime.fromisoformat(record.created_at)
        .astimezone(settings.timezone)
        .strftime("%d.%m.%Y %H:%M")
    )
    kind_key = (
        record.building_type if record.building_type in {"apartment", "house"} else "unknown"
    )
    author = str(record.answers.get("prepared_by") or tr("history.author_owner", locale))
    await callback.message.answer(
        tr(
            "history.card",
            locale,
            id=record.id,
            name=record.object_name,
            version=record.calculation_version,
            kind=tr(f"history.kind.{kind_key}", locale),
            total=f"{record.total_kw:.2f}",
            recommended=f"{record.recommended_kw:.2f}",
            created=created,
            author=author,
            engine=record.engine_version,
            catalog=record.catalog_version,
            norms=record.norms_version,
        ),
        reply_markup=_history_card_keyboard(record.id, locale),
    )
    await callback.answer()


@router.callback_query(F.data == "h:back")
async def history_back(callback: CallbackQuery, repository: CalculationRepository) -> None:
    from .menu import history_menu

    await history_menu(callback, repository)


@router.callback_query(F.data.startswith("h:report:"))
async def calculation_report_callback(
    callback: CallbackQuery, repository: CalculationRepository
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    calculation_id = _callback_calculation_id(callback)
    record = (
        await asyncio.to_thread(repository.get_for_user, callback.from_user.id, calculation_id)
        if calculation_id is not None
        else None
    )
    if record is None:
        await callback.answer(tr("history.not_found", locale), show_alert=True)
        return
    await _send_long_message(
        callback.message,
        f"№{record.id} · {record.object_name}\n\n{record.report}",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("h:copy:"))
async def calculation_copy_callback(
    callback: CallbackQuery,
    state: FSMContext,
    repository: CalculationRepository,
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    calculation_id = _callback_calculation_id(callback)
    data = (
        await asyncio.to_thread(
            repository.copy_answers_for_user,
            callback.from_user.id,
            calculation_id,
        )
        if calculation_id is not None
        else None
    )
    if data is None:
        await callback.answer(tr("history.not_found", locale), show_alert=True)
        return
    await state.set_data(data)
    await callback.message.answer(tr("history.copy_ready", locale))
    from .result import _ask_confirmation

    await _ask_confirmation(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("h:pdf:"))
async def calculation_pdf_callback(
    callback: CallbackQuery, repository: CalculationRepository
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    calculation_id = _callback_calculation_id(callback)
    record = (
        await asyncio.to_thread(repository.get_for_user, callback.from_user.id, calculation_id)
        if calculation_id is not None
        else None
    )
    if record is None:
        await callback.answer(tr("history.not_found", locale), show_alert=True)
        return
    pdf = await asyncio.to_thread(
        repository.get_pdf_for_user,
        callback.from_user.id,
        calculation_id,
    )
    if pdf is None:
        await callback.answer(tr("history.pdf_unavailable", locale), show_alert=True)
        return
    await callback.message.answer_document(
        BufferedInputFile(pdf, filename=f"u-calc-{record.id}-v{record.calculation_version}.pdf"),
        caption=tr(
            "history.pdf_caption",
            locale,
            id=record.id,
            version=record.calculation_version,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("h:compare:"))
async def calculation_compare_callback(
    callback: CallbackQuery, repository: CalculationRepository
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    calculation_id = _callback_calculation_id(callback)
    if calculation_id is None:
        await callback.answer(tr("history.not_found", locale), show_alert=True)
        return
    record = await asyncio.to_thread(
        repository.get_for_user, callback.from_user.id, calculation_id
    )
    if record is None:
        await callback.answer(tr("history.not_found", locale), show_alert=True)
        return
    previous = await asyncio.to_thread(
        repository.previous_version_for_user,
        callback.from_user.id,
        calculation_id,
    )
    if previous is None:
        await callback.answer(tr("history.no_previous", locale), show_alert=True)
        return
    differences = await asyncio.to_thread(
        repository.compare_for_user,
        callback.from_user.id,
        previous.id,
        record.id,
    )
    if not differences:
        await callback.message.answer(tr("history.same", locale))
    else:
        lines = [tr("history.diff_title", locale, version=previous.calculation_version)]
        for key, (before, after) in list(differences.items())[:40]:
            lines.append(
                f"• {_comparison_label(key, locale)}: "
                f"{_comparison_value(key, before, locale)} → "
                f"{_comparison_value(key, after, locale)}"
            )
        await _send_long_message(callback.message, "\n".join(lines))
    await callback.answer()


@router.callback_query(F.data.startswith("h:delete:"))
async def calculation_delete_prompt(
    callback: CallbackQuery, repository: CalculationRepository
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    calculation_id = _callback_calculation_id(callback)
    record = (
        await asyncio.to_thread(repository.get_for_user, callback.from_user.id, calculation_id)
        if calculation_id is not None
        else None
    )
    if record is None:
        await callback.answer(tr("history.not_found", locale), show_alert=True)
        return
    await callback.message.answer(
        tr("history.delete_confirm", locale, id=record.id, name=record.object_name),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=tr("common.confirm_delete", locale),
                        callback_data=f"h:delete_confirm:{record.id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=tr("common.cancel", locale),
                        callback_data=f"h:delete_cancel:{record.id}",
                    )
                ],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("h:delete_confirm:"))
async def calculation_delete_confirm(
    callback: CallbackQuery, repository: CalculationRepository
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    calculation_id = _callback_calculation_id(callback)
    deleted = (
        await asyncio.to_thread(
            repository.delete_calculation_for_user,
            callback.from_user.id,
            calculation_id,
        )
        if calculation_id is not None
        else False
    )
    if not deleted:
        await callback.answer(tr("history.not_found", locale), show_alert=True)
        return
    await callback.message.answer(tr("history.deleted", locale))
    await callback.answer()


@router.callback_query(F.data.startswith("h:delete_cancel:"))
async def calculation_delete_cancel(
    callback: CallbackQuery, repository: CalculationRepository
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    await callback.message.answer(tr("history.delete_cancelled", locale))
    await callback.answer()


async def _send_long_message(message: Message, text: str, limit: int = 3900) -> None:
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            await message.answer(remaining)
            return
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        await message.answer(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")


@router.message(Command("help"))
async def help_command(message: Message, repository: CalculationRepository) -> None:
    locale = await _locale(repository, message.from_user.id)
    await message.answer(
        f"{tr('help.commands', locale)}\n\n{tr('help.text', locale)}"
        f"\n\n{product_identity(locale)}"
    )


@router.message(Command("history"))
async def history(message: Message, repository: CalculationRepository, settings: Settings) -> None:
    locale = await _locale(repository, message.from_user.id)
    records = await asyncio.to_thread(repository.recent, message.from_user.id, 5)
    if not records:
        await message.answer(tr("history.command_empty", locale))
        return
    lines = [tr("history.command_title", locale)]
    for record in records:
        created = (
            datetime.fromisoformat(record.created_at)
            .astimezone(settings.timezone)
            .strftime("%d.%m.%Y %H:%M")
        )
        kind_key = (
            record.building_type if record.building_type in {"apartment", "house"} else "unknown"
        )
        lines.append(
            tr(
                "history.command_item",
                locale,
                id=record.id,
                created=created,
                kind=tr(f"history.kind.{kind_key}", locale),
                name=record.object_name,
                version=record.calculation_version,
                recommended=f"{record.recommended_kw:.2f}",
            )
        )
    await message.answer("\n".join(lines))


@router.message(Command("compare"))
async def compare_calculations(message: Message, repository: CalculationRepository) -> None:
    locale = await _locale(repository, message.from_user.id)
    parts = (message.text or "").split()
    if len(parts) != 3 or not all(item.isdigit() for item in parts[1:]):
        await message.answer(tr("history.compare_usage", locale))
        return
    differences = await asyncio.to_thread(
        repository.compare_for_user,
        message.from_user.id,
        int(parts[1]),
        int(parts[2]),
    )
    if differences is None:
        await message.answer(tr("history.compare_not_found", locale))
        return
    if not differences:
        await message.answer(tr("history.same", locale))
        return
    lines = [tr("history.diff_command_title", locale)]
    for key, (before, after) in list(differences.items())[:40]:
        lines.append(
            f"• {_comparison_label(key, locale)}: "
            f"{_comparison_value(key, before, locale)} → "
            f"{_comparison_value(key, after, locale)}"
        )
    await _send_long_message(message, "\n".join(lines))


@router.message(Command("copy"))
async def copy_calculation(
    message: Message,
    state: FSMContext,
    repository: CalculationRepository,
) -> None:
    locale = await _locale(repository, message.from_user.id)
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(tr("history.copy_usage", locale))
        return
    data = await asyncio.to_thread(
        repository.copy_answers_for_user,
        message.from_user.id,
        int(parts[1]),
    )
    if data is None:
        await message.answer(tr("history.not_found", locale))
        return
    await state.set_data(data)
    from .result import _ask_confirmation

    await _ask_confirmation(message, state)


@router.message(Command("report"))
async def saved_report(message: Message, repository: CalculationRepository) -> None:
    locale = await _locale(repository, message.from_user.id)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip().isdigit():
        await message.answer(tr("history.report_usage", locale))
        return
    calculation_id = int(parts[1].strip())
    record = await asyncio.to_thread(repository.get_for_user, message.from_user.id, calculation_id)
    if record is None:
        await message.answer(tr("history.not_found", locale))
        return
    await _send_long_message(
        message,
        f"{tr('history.report_title', locale, id=record.id)}\n\n{record.report}",
    )


@router.message(Command("delete_history"))
async def delete_history_prompt(
    message: Message, repository: CalculationRepository
) -> None:
    locale = await _locale(repository, message.from_user.id)
    await message.answer(
        tr("history.delete_all_prompt", locale),
        reply_markup=keyboard(
            [
                (tr("history.delete_all_confirm", locale), "delete_history:confirm"),
                (tr("common.cancel", locale), "delete_history:cancel"),
            ],
            1,
        ),
    )


@router.callback_query(F.data.startswith("delete_history:"))
async def delete_history(callback: CallbackQuery, repository: CalculationRepository) -> None:
    locale = await _locale(repository, callback.from_user.id)
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await callback.message.answer(tr("history.delete_cancelled", locale))
    elif action == "confirm":
        deleted = await asyncio.to_thread(repository.delete_for_user, callback.from_user.id)
        await callback.message.answer(tr("history.delete_all_done", locale, count=deleted))
    else:
        await callback.answer(tr("common.stale", locale), show_alert=True)
        return
    await callback.answer()
