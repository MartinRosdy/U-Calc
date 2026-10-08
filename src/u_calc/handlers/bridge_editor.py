"""Button-driven editor for exact linear thermal bridges (ψ × length)."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..i18n import translate as tr
from ..keyboards import keyboard
from ..parsing import parse_number
from ..states import Survey

router = Router(name=__name__)


async def _locale(state: FSMContext) -> str:
    return str((await state.get_data()).get("locale") or "ru")


async def _error(message: Message, state: FSMContext, key: str) -> None:
    locale = await _locale(state)
    await message.answer(tr("bridge.editor.retry", locale, message=tr(key, locale)))


async def start_editor(message: Message, state: FSMContext) -> None:
    await state.update_data(linear_thermal_bridges=[], bridge_editor_edit_index=None)
    await ask_name(message, state)


async def ask_name(message: Message, state: FSMContext) -> None:
    await state.update_data(
        bridge_editor_name=None,
        bridge_editor_length=None,
        bridge_editor_psi=None,
    )
    await state.set_state(Survey.bridge_editor_name)
    await message.answer(tr("bridge.editor.name", await _locale(state)))


@router.message(Survey.bridge_editor_name)
async def bridge_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not 1 <= len(name) <= 60:
        await _error(message, state, "bridge.editor.error.name")
        return
    await state.update_data(bridge_editor_name=name)
    await state.set_state(Survey.bridge_editor_length)
    await message.answer(tr("bridge.editor.length", await _locale(state)))


@router.message(Survey.bridge_editor_length)
async def bridge_length(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text, minimum=0.01, maximum=10_000, label="length")
    except ValueError:
        await _error(message, state, "bridge.editor.error.length")
        return
    await state.update_data(bridge_editor_length=value)
    await state.set_state(Survey.bridge_editor_psi)
    await message.answer(tr("bridge.editor.psi", await _locale(state)))


@router.message(Survey.bridge_editor_psi)
async def bridge_psi(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text, minimum=0, maximum=5, label="psi")
    except ValueError:
        await _error(message, state, "bridge.editor.error.psi")
        return
    data = await state.get_data()
    bridges = list(data.get("linear_thermal_bridges", []))
    if len(bridges) >= 30:
        await _error(message, state, "bridge.editor.error.limit")
        return
    bridge = {
        "name": data["bridge_editor_name"],
        "length_m": data["bridge_editor_length"],
        "psi_w_mk": value,
    }
    edit_index = data.get("bridge_editor_edit_index")
    if isinstance(edit_index, int) and 0 <= edit_index <= len(bridges):
        bridges.insert(edit_index, bridge)
    else:
        bridges.append(bridge)
    await state.update_data(
        linear_thermal_bridges=bridges, bridge_editor_edit_index=None
    )
    await show_actions(message, state)


async def show_actions(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    locale = str(data.get("locale") or "ru")
    bridges = data.get("linear_thermal_bridges", [])
    summary = "\n".join(
        tr(
            "bridge.editor.summary",
            locale,
            name=item["name"],
            length=f"{item['length_m']:g}",
            psi=f"{item['psi_w_mk']:g}",
        )
        for item in bridges
    )
    await state.set_state(Survey.bridge_editor_action)
    await message.answer(
        tr("bridge.editor.saved", locale, count=len(bridges), summary=summary),
        reply_markup=keyboard(
            [
                (tr("bridge.editor.add", locale), "bedit:add"),
                *[
                    (
                        tr("bridge.editor.edit", locale, name=item["name"]),
                        f"bedit:edit:{index}",
                    )
                    for index, item in enumerate(bridges)
                ],
                *[
                    (
                        tr("bridge.editor.delete_named", locale, name=item["name"]),
                        f"bedit:delete:{index}",
                    )
                    for index, item in enumerate(bridges)
                ],
                (tr("bridge.editor.finish", locale), "bedit:finish"),
            ],
            1,
            locale=locale,
        ),
    )


@router.callback_query(Survey.bridge_editor_action, F.data.startswith("bedit:"))
async def bridge_action(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    action = parts[1]
    data = await state.get_data()
    locale = str(data.get("locale") or "ru")
    bridges = list(data.get("linear_thermal_bridges", []))
    if action == "add":
        if len(bridges) >= 30:
            await callback.answer(tr("bridge.editor.error.limit_alert", locale), show_alert=True)
            return
        await ask_name(callback.message, state)
    elif action == "edit":
        try:
            index = int(parts[2])
            bridges.pop(index)
        except (IndexError, ValueError):
            await callback.answer(tr("bridge.editor.error.stale", locale), show_alert=True)
            return
        await state.update_data(
            linear_thermal_bridges=bridges, bridge_editor_edit_index=index
        )
        await ask_name(callback.message, state)
    elif action == "delete":
        if not bridges:
            await callback.answer(tr("bridge.editor.error.empty", locale), show_alert=True)
            return
        try:
            index = int(parts[2]) if len(parts) > 2 else len(bridges) - 1
            bridges.pop(index)
        except (IndexError, ValueError):
            await callback.answer(tr("bridge.editor.error.stale", locale), show_alert=True)
            return
        await state.update_data(linear_thermal_bridges=bridges)
        if bridges:
            await show_actions(callback.message, state)
        else:
            await ask_name(callback.message, state)
    elif action == "finish":
        if not bridges:
            await callback.answer(tr("bridge.editor.error.required", locale), show_alert=True)
            return
        await state.update_data(thermal_bridge_factor=0.0)
        from .survey import _ask_safety_factor

        await _ask_safety_factor(callback.message, state)
    else:
        await callback.answer(tr("bridge.editor.error.action", locale), show_alert=True)
        return
    await callback.answer()


async def render_editor_step(message: Message, state: FSMContext) -> bool:
    getter = getattr(state, "get_state", None)
    if getter is not None:
        current = await getter()
    else:
        value = getattr(state, "state", None)
        current = getattr(value, "state", value)
    if current == Survey.bridge_editor_action.state:
        await show_actions(message, state)
        return True
    prompts = {
        Survey.bridge_editor_name.state: "bridge.editor.name",
        Survey.bridge_editor_length.state: "bridge.editor.length",
        Survey.bridge_editor_psi.state: "bridge.editor.psi",
    }
    if current in prompts:
        await message.answer(tr(prompts[current], await _locale(state)))
        return True
    return False
