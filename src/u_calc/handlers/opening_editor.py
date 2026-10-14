"""Button-driven editor for window and door groups.

The legacy pipe-separated import remains in ``survey`` as an expert shortcut.
"""

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..i18n import translate as tr
from ..keyboards import keyboard
from ..parsing import parse_dimensions, parse_number
from ..states import Survey
from .common import bounded_text

router = Router(name=__name__)


async def _locale(state: FSMContext) -> str:
    return str((await state.get_data()).get("locale") or "ru")


def _kind_label(data: dict[str, Any], locale: str) -> str:
    return tr(
        "opening.windows" if data.get("opening_editor_kind") == "window" else "opening.doors",
        locale,
    )


async def _error(message: Message, state: FSMContext, key: str, **values: object) -> None:
    locale = await _locale(state)
    await message.answer(tr("opening.editor.retry", locale, message=tr(key, locale, **values)))


def _kind_data(data: dict[str, Any]) -> tuple[str, str, int]:
    kind = data.get("opening_editor_kind")
    if kind == "window":
        return "window_groups", "окон", int(data.get("window_count", 0))
    if kind == "door":
        return "door_groups", "дверей", int(data.get("door_count", 0))
    raise ValueError("Редактор проёмов не инициализирован")


async def start_editor(message: Message, state: FSMContext, kind: str) -> None:
    if kind not in {"window", "door"}:
        raise ValueError("Неизвестный тип проёма")
    key = "window_groups" if kind == "window" else "door_groups"
    await state.update_data(opening_editor_kind=kind, opening_editor_edit_index=None, **{key: []})
    await _ask_name(message, state)


async def _ask_name(message: Message, state: FSMContext) -> None:
    await state.update_data(
        opening_editor_name=None,
        opening_editor_count=None,
        opening_editor_width=None,
        opening_editor_height=None,
        opening_editor_u_value=None,
    )
    data = await state.get_data()
    _, _, expected = _kind_data(data)
    locale = str(data.get("locale") or "ru")
    await state.set_state(Survey.opening_editor_name)
    await message.answer(
        tr(
            "opening.editor.name",
            locale,
            kind=_kind_label(data, locale),
            expected=expected,
        )
    )


@router.message(Survey.opening_editor_name)
async def opening_name(message: Message, state: FSMContext) -> None:
    try:
        name = bounded_text(message.text, minimum=1, maximum=60, label="Название проёма")
    except ValueError:
        await _error(message, state, "opening.editor.error.name_length")
        return
    data = await state.get_data()
    key, _, _ = _kind_data(data)
    edit_index = data.get("opening_editor_edit_index")
    groups = data.get(key, [])
    if edit_index is not None and (
        type(edit_index) is not int or not 0 <= edit_index < len(groups)
    ):
        await _error(message, state, "opening.editor.error.stale_group")
        return
    if any(
        index != edit_index and item["name"].casefold() == name.casefold()
        for index, item in enumerate(groups)
    ):
        await _error(message, state, "opening.editor.error.duplicate", name=name)
        return
    await state.update_data(opening_editor_name=name)
    await state.set_state(Survey.opening_editor_count)
    await message.answer(tr("opening.editor.count", await _locale(state)))


@router.message(Survey.opening_editor_count)
async def opening_count(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    key, label, expected = _kind_data(data)
    groups = data.get(key, [])
    edit_index = data.get("opening_editor_edit_index")
    if edit_index is not None and (
        type(edit_index) is not int or not 0 <= edit_index < len(groups)
    ):
        await _error(message, state, "opening.editor.error.stale_group")
        return
    used = sum(
        int(item["count"]) for index, item in enumerate(groups) if index != edit_index
    )
    try:
        value = int((message.text or "").strip())
    except ValueError:
        await _error(message, state, "opening.editor.error.integer")
        return
    remaining = expected - used
    if not 1 <= value <= remaining:
        locale = await _locale(state)
        await _error(
            message,
            state,
            "opening.editor.error.count_range",
            remaining=remaining,
            kind=_kind_label(data, locale),
        )
        return
    await state.update_data(opening_editor_count=value)
    await state.set_state(Survey.opening_editor_dimensions)
    await message.answer(tr("opening.editor.dimensions", await _locale(state)))


@router.message(Survey.opening_editor_dimensions)
async def opening_dimensions(message: Message, state: FSMContext) -> None:
    try:
        values = parse_dimensions(message.text)
        if len(values) != 1:
            raise ValueError("Укажите одну пару размеров")
    except ValueError:
        await _error(message, state, "opening.editor.error.dimensions")
        return
    width, height = values[0]
    await state.update_data(opening_editor_width=width, opening_editor_height=height)
    await state.set_state(Survey.opening_editor_u_value)
    await message.answer(tr("opening.editor.u_value", await _locale(state)))


@router.message(Survey.opening_editor_u_value)
async def opening_u_value(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(
            message.text,
            minimum=0.1,
            maximum=8,
            label="U-value",
        )
    except ValueError:
        await _error(message, state, "opening.editor.error.u_value")
        return
    await state.update_data(opening_editor_u_value=value)
    data = await state.get_data()
    walls = data.get("wall_groups") or []
    if not walls:
        try:
            await _save_group(message, state, None)
        except ValueError as exc:
            await message.answer(
                tr(
                    "opening.editor.retry",
                    await _locale(state),
                    message=str(exc),
                )
            )
        return
    await _ask_wall_selection(message, state, walls)


async def _ask_wall_selection(
    message: Message,
    state: FSMContext,
    walls: list[dict[str, Any]],
) -> None:
    await state.set_state(Survey.opening_editor_wall)
    locale = await _locale(state)
    rows = [
        [InlineKeyboardButton(text=item["name"], callback_data=f"oewall:{index}")]
        for index, item in enumerate(walls)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=tr("opening.editor.no_wall", locale), callback_data="oewall:none"
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text=tr("common.back", locale), callback_data="nav:back"),
            InlineKeyboardButton(text=tr("common.cancel", locale), callback_data="nav:cancel"),
        ]
    )
    await message.answer(
        tr("opening.editor.wall", locale),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(Survey.opening_editor_wall, F.data.startswith("oewall:"))
async def opening_wall(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    data = await state.get_data()
    walls = data.get("wall_groups") or []
    if value == "none":
        wall_name = None
    else:
        try:
            wall_name = walls[int(value)]["name"]
        except (ValueError, IndexError, KeyError):
            await callback.answer(
                tr("opening.editor.error.stale_wall", await _locale(state)), show_alert=True
            )
            return
    try:
        await _save_group(callback.message, state, wall_name)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


async def _save_group(message: Message, state: FSMContext, wall_name: str | None) -> None:
    data = await state.get_data()
    key, _, _ = _kind_data(data)
    count = int(data["opening_editor_count"])
    width = float(data["opening_editor_width"])
    height = float(data["opening_editor_height"])
    area = count * width * height
    groups = list(data.get(key, []))
    edit_index = data.get("opening_editor_edit_index")
    if edit_index is not None and (
        type(edit_index) is not int or not 0 <= edit_index < len(groups)
    ):
        raise ValueError(tr("opening.editor.error.stale_group", str(data.get("locale") or "ru")))
    unchanged_groups = [
        item for index, item in enumerate(groups) if index != edit_index
    ]
    other_key = "door_groups" if key == "window_groups" else "window_groups"
    other_groups = data.get(other_key) or []
    total_area = (
        sum(float(item["area_m2"]) for item in [*unchanged_groups, *other_groups]) + area
    )
    if total_area > float(data["wall_gross_area"]):
        raise ValueError(tr("opening.editor.error.total_area", str(data.get("locale") or "ru")))
    if wall_name:
        walls = {item["name"]: float(item["gross_area_m2"]) for item in data["wall_groups"]}
        assigned = sum(
            float(item["area_m2"])
            for item in [*unchanged_groups, *other_groups]
            if item.get("wall_name") == wall_name
        )
        if assigned + area > walls[wall_name]:
            raise ValueError(
                tr(
                    "opening.editor.error.wall_area",
                    str(data.get("locale") or "ru"),
                    wall=wall_name,
                )
            )
    group = {
        "name": data["opening_editor_name"],
        "count": count,
        "width_m": width,
        "height_m": height,
        "area_m2": area,
        "u_value": float(data["opening_editor_u_value"]),
        "wall_name": wall_name,
    }
    if edit_index is not None:
        groups[edit_index] = group
    else:
        groups.append(group)
    await state.update_data(opening_editor_edit_index=None, **{key: groups})
    await _show_actions(message, state)


async def _show_actions(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    key, _, expected = _kind_data(data)
    locale = str(data.get("locale") or "ru")
    label = _kind_label(data, locale)
    groups = data.get(key, [])
    used = sum(int(item["count"]) for item in groups)
    summary = "\n".join(
        tr(
            "opening.editor.summary",
            locale,
            name=item["name"],
            count=item["count"],
            area=f"{item['area_m2']:g}",
            u_value=f"{item['u_value']:g}",
        )
        for item in groups
    )
    await state.set_state(Survey.opening_editor_action)
    await message.answer(
        tr(
            "opening.editor.saved",
            locale,
            kind=label,
            used=used,
            expected=expected,
            summary=summary,
        ),
        reply_markup=keyboard(
            [
                (tr("opening.editor.add", locale), "oedit:add"),
                *[
                    (
                        tr("opening.editor.edit", locale, name=item["name"]),
                        f"oedit:edit:{index}",
                    )
                    for index, item in enumerate(groups)
                ],
                *[
                    (
                        tr("opening.editor.delete_named", locale, name=item["name"]),
                        f"oedit:delete:{index}",
                    )
                    for index, item in enumerate(groups)
                ],
                (tr("opening.editor.finish", locale), "oedit:finish"),
            ],
            1,
            locale=locale,
        ),
    )


@router.callback_query(Survey.opening_editor_action, F.data.startswith("oedit:"))
async def opening_action(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    action = parts[1]
    data = await state.get_data()
    key, _, expected = _kind_data(data)
    groups = list(data.get(key, []))
    used = sum(int(item["count"]) for item in groups)
    if action == "add":
        if used >= expected:
            await callback.answer(
                tr("opening.editor.error.distributed", await _locale(state)), show_alert=True
            )
            return
        await _ask_name(callback.message, state)
    elif action == "edit":
        try:
            index = int(parts[2])
        except (IndexError, ValueError):
            await callback.answer(
                tr("opening.editor.error.stale_group", await _locale(state)),
                show_alert=True,
            )
            return
        if not 0 <= index < len(groups):
            await callback.answer(
                tr("opening.editor.error.stale_group", await _locale(state)),
                show_alert=True,
            )
            return
        await state.update_data(opening_editor_edit_index=index)
        await _ask_name(callback.message, state)
    elif action == "delete":
        if not groups:
            await callback.answer(
                tr("opening.editor.error.empty", await _locale(state)), show_alert=True
            )
            return
        try:
            index = int(parts[2]) if len(parts) > 2 else len(groups) - 1
        except (IndexError, ValueError):
            await callback.answer(
                tr("opening.editor.error.stale_group", await _locale(state)),
                show_alert=True,
            )
            return
        if not 0 <= index < len(groups):
            await callback.answer(
                tr("opening.editor.error.stale_group", await _locale(state)),
                show_alert=True,
            )
            return
        groups.pop(index)
        await state.update_data(**{key: groups})
        if groups:
            await _show_actions(callback.message, state)
        else:
            await _ask_name(callback.message, state)
    elif action == "finish":
        if used != expected:
            await callback.answer(
                tr(
                    "opening.editor.error.incomplete",
                    await _locale(state),
                    used=used,
                    expected=expected,
                ),
                show_alert=True,
            )
            return
        area = sum(float(item["area_m2"]) for item in groups)
        if key == "window_groups":
            await state.update_data(window_area=area, window_type=None)
            from .openings import _ask_doors

            await _ask_doors(callback.message, state)
        else:
            await state.update_data(door_area=area, door_u_value=None)
            from .survey import _advance_after_openings

            await _advance_after_openings(callback.message, state)
    else:
        await callback.answer(
            tr("opening.editor.error.unknown_action", await _locale(state)), show_alert=True
        )
        return
    await callback.answer()


async def render_editor_step(message: Message, state: FSMContext) -> bool:
    """Re-render editor screens after draft restore/back."""
    getter = getattr(state, "get_state", None)
    if getter is not None:
        current = await getter()
    else:
        value = getattr(state, "state", None)
        current = getattr(value, "state", value)
    if current == Survey.opening_editor_action.state:
        await _show_actions(message, state)
        return True
    if current == Survey.opening_editor_name.state:
        data = await state.get_data()
        _, _, expected = _kind_data(data)
        locale = str(data.get("locale") or "ru")
        await message.answer(
            tr(
                "opening.editor.name_resume",
                locale,
                kind=_kind_label(data, locale),
                expected=expected,
            )
        )
        return True
    if current == Survey.opening_editor_count.state:
        await message.answer(tr("opening.editor.count", await _locale(state)))
        return True
    if current == Survey.opening_editor_dimensions.state:
        await message.answer(tr("opening.editor.dimensions", await _locale(state)))
        return True
    if current == Survey.opening_editor_u_value.state:
        await message.answer(tr("opening.editor.u_value", await _locale(state)))
        return True
    if current == Survey.opening_editor_wall.state:
        data = await state.get_data()
        await _ask_wall_selection(message, state, data.get("wall_groups") or [])
        return True
    return False
