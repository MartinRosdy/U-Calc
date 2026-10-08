"""Commands for viewing, comparing and deleting saved calculations."""

import asyncio
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..keyboards import keyboard
from ..storage import CalculationRepository

router = Router(name=__name__)


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
async def help_command(message: Message) -> None:
    await message.answer(
        "Команды:\n/new — новый расчёт\n/history — последние расчёты\n"
        "/report N — открыть сохранённый расчёт №N\n"
        "/delete_history — удалить свою историю\n/resume — продолжить черновик\n"
        "/discard_draft — удалить черновик\n/copy N — копировать расчёт\n"
        "/compare N M — сравнить две версии\n"
        "/back — предыдущий шаг\n/cancel — отменить\n/help — справка\n\n"
        "Бот считает Q = U × A × ΔT для ограждений и раздельные воздушные потери. "
        "Результат — требуемая мощность в расчётный мороз, а не месячное потребление."
    )


@router.message(Command("history"))
async def history(message: Message, repository: CalculationRepository, settings: Settings) -> None:
    records = await asyncio.to_thread(repository.recent, message.from_user.id, 5)
    if not records:
        await message.answer("История пока пуста. Начните расчёт командой /new")
        return
    lines = ["🗂 Последние расчёты:"]
    for record in records:
        created = (
            datetime.fromisoformat(record.created_at)
            .astimezone(settings.timezone)
            .strftime("%d.%m.%Y %H:%M")
        )
        kind = "квартира" if record.building_type == "apartment" else "дом"
        lines.append(
            f"• №{record.id} · {created} · {kind} · {record.object_name} "
            f"v{record.calculation_version} · {record.recommended_kw:.2f} кВт с запасом"
        )
    await message.answer("\n".join(lines))


@router.message(Command("compare"))
async def compare_calculations(message: Message, repository: CalculationRepository) -> None:
    parts = (message.text or "").split()
    if len(parts) != 3 or not all(item.isdigit() for item in parts[1:]):
        await message.answer("Укажите два номера: /compare 12 15")
        return
    differences = await asyncio.to_thread(
        repository.compare_for_user,
        message.from_user.id,
        int(parts[1]),
        int(parts[2]),
    )
    if differences is None:
        await message.answer("Один из расчётов не найден в вашей истории.")
        return
    if not differences:
        await message.answer("Исходные данные этих версий совпадают.")
        return
    lines = ["Изменённые исходные данные:"]
    for key, (before, after) in list(differences.items())[:40]:
        lines.append(f"• {key}: {before!s:.80} → {after!s:.80}")
    await _send_long_message(message, "\n".join(lines))


@router.message(Command("copy"))
async def copy_calculation(
    message: Message,
    state: FSMContext,
    repository: CalculationRepository,
) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Укажите номер: /copy 12")
        return
    data = await asyncio.to_thread(
        repository.copy_answers_for_user,
        message.from_user.id,
        int(parts[1]),
    )
    if data is None:
        await message.answer("Расчёт не найден в вашей истории.")
        return
    await state.set_data(data)
    from .survey import _ask_confirmation

    await _ask_confirmation(message, state)


@router.message(Command("report"))
async def saved_report(message: Message, repository: CalculationRepository) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip().isdigit():
        await message.answer("Укажите номер: /report 12")
        return
    calculation_id = int(parts[1].strip())
    record = await asyncio.to_thread(repository.get_for_user, message.from_user.id, calculation_id)
    if record is None:
        await message.answer("Расчёт с таким номером не найден в вашей истории.")
        return
    await _send_long_message(message, f"Расчёт №{record.id}\n\n{record.report}")


@router.message(Command("delete_history"))
async def delete_history_prompt(message: Message) -> None:
    await message.answer(
        "Удалить все ваши сохранённые расчёты? Это действие нельзя отменить.",
        reply_markup=keyboard(
            [
                ("Да, удалить", "delete_history:confirm"),
                ("Отмена", "delete_history:cancel"),
            ],
            1,
        ),
    )


@router.callback_query(F.data.startswith("delete_history:"))
async def delete_history(callback: CallbackQuery, repository: CalculationRepository) -> None:
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await callback.message.answer("Удаление отменено.")
    elif action == "confirm":
        deleted = await asyncio.to_thread(repository.delete_for_user, callback.from_user.id)
        await callback.message.answer(f"Удалено расчётов: {deleted}.")
    else:
        await callback.answer("Неизвестное действие", show_alert=True)
        return
    await callback.answer()
