"""Button-driven editor for exact linear thermal bridges (ψ × length)."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..i18n import translate as tr
from ..keyboards import keyboard
from ..parsing import parse_number
from ..states import Survey
from .common import bounded_text

router = Router(name=__name__)

MAX_BRIDGES = 30


async def _locale(state: FSMContext) -> str:
    return str((await state.get_data()).get("locale") or "ru")


async def _error(message: Message, state: FSMContext, key: str) -> None:
    locale = await _locale(state)
    await message.answer(tr("bridge.editor.retry", locale, message=tr(key, locale)))


def _validated_bridges(value: object) -> list[dict[str, object]]:
    """Return a safe copy of bridge rows stored in a resumable FSM draft."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_BRIDGES:
        raise ValueError("invalid bridge collection")
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("invalid bridge row")
        raw_name = item.get("name")
        if not isinstance(raw_name, str):
            raise ValueError("invalid bridge name")
        name = bounded_text(raw_name, minimum=1, maximum=60, label="Название мостика")
        length = parse_number(
            str(item.get("length_m", "")), minimum=0.01, maximum=10_000, label="length"
        )
        psi = parse_number(str(item.get("psi_w_mk", "")), minimum=0, maximum=5, label="psi")
        result.append({"name": name, "length_m": length, "psi_w_mk": psi})
    return result


async def _recover_corrupt_draft(message: Message, state: FSMContext) -> None:
    await message.answer(tr("bridge.editor.error.corrupt", await _locale(state)))
    await start_editor(message, state)


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
    try:
        name = bounded_text(message.text, minimum=1, maximum=60, label="Название мостика")
    except ValueError:
        await _error(message, state, "bridge.editor.error.name")
        return
    data = await state.get_data()
    try:
        bridges = _validated_bridges(data.get("linear_thermal_bridges"))
    except ValueError:
        await _recover_corrupt_draft(message, state)
        return
    edit_index = data.get("bridge_editor_edit_index")
    if edit_index is not None and (
        type(edit_index) is not int or not 0 <= edit_index < len(bridges)
    ):
        await _recover_corrupt_draft(message, state)
        return
    if any(
        index != edit_index and str(item["name"]).casefold() == name.casefold()
        for index, item in enumerate(bridges)
    ):
        await _error(message, state, "bridge.editor.error.duplicate")
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
    try:
        bridges = _validated_bridges(data.get("linear_thermal_bridges"))
        raw_name = data.get("bridge_editor_name")
        if not isinstance(raw_name, str):
            raise ValueError("invalid pending bridge name")
        name = bounded_text(
            raw_name,
            minimum=1,
            maximum=60,
            label="Название мостика",
        )
        length = parse_number(
            str(data.get("bridge_editor_length", "")),
            minimum=0.01,
            maximum=10_000,
            label="length",
        )
    except ValueError:
        await _recover_corrupt_draft(message, state)
        return
    edit_index = data.get("bridge_editor_edit_index")
    if edit_index is not None and (
        type(edit_index) is not int or not 0 <= edit_index < len(bridges)
    ):
        await _recover_corrupt_draft(message, state)
        return
    if edit_index is None and len(bridges) >= MAX_BRIDGES:
        await _error(message, state, "bridge.editor.error.limit")
        return
    bridge = {
        "name": name,
        "length_m": length,
        "psi_w_mk": value,
    }
    if edit_index is not None:
        bridges[edit_index] = bridge
    else:
        bridges.append(bridge)
    await state.update_data(linear_thermal_bridges=bridges, bridge_editor_edit_index=None)
    await show_actions(message, state)


async def show_actions(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    locale = str(data.get("locale") or "ru")
    try:
        bridges = _validated_bridges(data.get("linear_thermal_bridges"))
    except ValueError:
        await _recover_corrupt_draft(message, state)
        return
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
    try:
        bridges = _validated_bridges(data.get("linear_thermal_bridges"))
    except ValueError:
        await callback.answer(tr("bridge.editor.error.corrupt", locale), show_alert=True)
        await start_editor(callback.message, state)
        return
    if action == "add":
        if len(bridges) >= MAX_BRIDGES:
            await callback.answer(tr("bridge.editor.error.limit_alert", locale), show_alert=True)
            return
        await ask_name(callback.message, state)
    elif action == "edit":
        try:
            index = int(parts[2])
        except (IndexError, ValueError):
            await callback.answer(tr("bridge.editor.error.stale", locale), show_alert=True)
            return
        if not 0 <= index < len(bridges):
            await callback.answer(tr("bridge.editor.error.stale", locale), show_alert=True)
            return
        await state.update_data(bridge_editor_edit_index=index)
        await ask_name(callback.message, state)
    elif action == "delete":
        if not bridges:
            await callback.answer(tr("bridge.editor.error.empty", locale), show_alert=True)
            return
        try:
            index = int(parts[2]) if len(parts) > 2 else len(bridges) - 1
        except (IndexError, ValueError):
            await callback.answer(tr("bridge.editor.error.stale", locale), show_alert=True)
            return
        if not 0 <= index < len(bridges):
            await callback.answer(tr("bridge.editor.error.stale", locale), show_alert=True)
            return
        bridges.pop(index)
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
        from .result import _ask_safety_factor

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
