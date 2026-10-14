"""Quick and expert-import Telegram flows for windows and doors."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..catalog import DOORS, WINDOWS
from ..i18n import translate as tr
from ..keyboards import keyboard
from ..parsing import parse_dimensions, parse_door_groups, parse_window_groups
from ..states import Survey
from .boundaries import _advance_after_openings
from .common import input_error as _error
from .common import nonnegative as _nonnegative
from .common import parse_count as _parse_count
from .common import state_locale as _state_locale

router = Router(name=__name__)


async def _ask_windows(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.window_count)
    await message.answer(tr("survey.window.count", await _state_locale(state)))


async def _ask_doors(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.door_count)
    await message.answer(tr("survey.door.count", await _state_locale(state)))


async def _ask_window_method(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.window_method)
    locale = await _state_locale(state)
    await message.answer(
        tr("survey.window.method", locale),
        reply_markup=keyboard(
            [
                (tr("survey.opening.area_method", locale), "window_method:area"),
                (tr("survey.opening.dimensions_method", locale), "window_method:dimensions"),
                (tr("survey.opening.editor_method", locale), "window_method:editor"),
                (tr("survey.opening.import_method", locale), "window_method:groups"),
            ],
            1,
            locale=locale,
        ),
    )


async def _ask_window_type(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.window_type)
    locale = await _state_locale(state)
    await message.answer(
        tr("survey.window.type", locale),
        reply_markup=keyboard(
            [(tr(f"window.{key}", locale), f"window:{key}") for key in WINDOWS],
            1,
            locale=locale,
        ),
    )


async def _ask_door_method(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.door_method)
    locale = await _state_locale(state)
    await message.answer(
        tr("survey.door.method", locale),
        reply_markup=keyboard(
            [
                (tr("survey.opening.area_method", locale), "door_method:area"),
                (tr("survey.opening.dimensions_method", locale), "door_method:dimensions"),
                (tr("survey.opening.editor_method", locale), "door_method:editor"),
                (tr("survey.opening.import_method", locale), "door_method:groups"),
            ],
            1,
            locale=locale,
        ),
    )


async def _ask_door_type(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.door_type)
    locale = await _state_locale(state)
    items = [(tr(f"door.{key}", locale), f"door_type:{key}") for key in DOORS]
    await message.answer(
        tr("survey.door.type", locale),
        reply_markup=keyboard(items, 1, locale=locale),
    )


@router.message(Survey.window_count)
async def window_count(message: Message, state: FSMContext) -> None:
    try:
        count = _parse_count(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(window_count=count)
    if count == 0:
        await state.update_data(window_area=0.0, window_type="double")
        await _ask_doors(message, state)
        return
    await _ask_window_method(message, state)


@router.callback_query(Survey.window_method, F.data.startswith("window_method:"))
async def window_method(callback: CallbackQuery, state: FSMContext) -> None:
    method = callback.data.split(":", 1)[1]
    locale = await _state_locale(state)
    if method not in {"area", "dimensions", "editor", "groups"}:
        await callback.answer(tr("common.invalid_option", locale), show_alert=True)
        return
    if method == "area":
        await state.set_state(Survey.window_area)
        await callback.message.answer(tr("survey.window.area", locale))
    elif method == "dimensions":
        await state.set_state(Survey.window_dimensions)
        await callback.message.answer(tr("survey.window.dimensions", locale))
    elif method == "editor":
        from .opening_editor import start_editor

        await start_editor(callback.message, state, "window")
    else:
        await state.set_state(Survey.window_groups)
        await callback.message.answer(tr("expert.window_prompt", locale))
    await callback.answer()


async def _accept_window_area(message: Message, state: FSMContext, area: float) -> None:
    data = await state.get_data()
    if area <= 0:
        raise ValueError("площадь окон должна быть больше нуля")
    if area > data["wall_gross_area"]:
        raise ValueError("площадь окон больше площади стен")
    await state.update_data(window_area=area)
    await _ask_window_type(message, state)


@router.message(Survey.window_area)
async def window_area(message: Message, state: FSMContext) -> None:
    try:
        await _accept_window_area(message, state, _nonnegative(message.text))
    except ValueError as exc:
        await _error(message, exc, state)


@router.message(Survey.window_dimensions)
async def window_dimensions(message: Message, state: FSMContext) -> None:
    try:
        dimensions = parse_dimensions(message.text)
        if len(dimensions) != 1:
            raise ValueError("укажите размер одного типового окна")
        data = await state.get_data()
        area = dimensions[0][0] * dimensions[0][1] * data["window_count"]
        await _accept_window_area(message, state, area)
    except ValueError as exc:
        await _error(message, exc, state)


@router.message(Survey.window_groups)
async def window_groups(message: Message, state: FSMContext) -> None:
    try:
        groups = parse_window_groups(message.text)
        data = await state.get_data()
        if sum(group["count"] for group in groups) != data["window_count"]:
            raise ValueError("сумма количества в группах не совпадает с указанным числом окон")
        area = sum(group["area_m2"] for group in groups)
        if area > data["wall_gross_area"]:
            raise ValueError("площадь окон больше площади стен")
        wall_groups_data = data.get("wall_groups") or []
        known_walls = {group["name"].casefold(): group["name"] for group in wall_groups_data}
        gross_by_wall = {group["name"]: group["gross_area_m2"] for group in wall_groups_data}
        assigned_by_wall: dict[str, float] = {}
        for group in groups:
            if group["wall_name"]:
                canonical = known_walls.get(group["wall_name"].casefold())
                if canonical is None:
                    raise ValueError(
                        f"для группы «{group['name']}» не найдена стена «{group['wall_name']}»"
                    )
                group["wall_name"] = canonical
                assigned_by_wall[canonical] = (
                    assigned_by_wall.get(canonical, 0.0) + group["area_m2"]
                )
        for wall_name, assigned_area in assigned_by_wall.items():
            if assigned_area > gross_by_wall[wall_name]:
                raise ValueError(f"окна на стене «{wall_name}» больше площади этой стены")
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(window_groups=groups, window_area=area, window_type=None)
    await _ask_doors(message, state)


@router.callback_query(Survey.window_type, F.data.startswith("window:"))
async def window_type(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    if key not in WINDOWS:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(window_type=key)
    await _ask_doors(callback.message, state)
    await callback.answer()


@router.message(Survey.door_count)
async def door_count(message: Message, state: FSMContext) -> None:
    try:
        count = _parse_count(message.text)
        if count > 100:
            raise ValueError("количество дверей должно быть от 0 до 100")
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(door_count=count)
    if count == 0:
        await state.update_data(door_area=0.0, door_groups=[], door_u_value=None)
        await _advance_after_openings(message, state)
        return
    await _ask_door_method(message, state)


@router.callback_query(Survey.door_method, F.data.startswith("door_method:"))
async def door_method(callback: CallbackQuery, state: FSMContext) -> None:
    method = callback.data.split(":", 1)[1]
    locale = await _state_locale(state)
    if method == "area":
        await state.set_state(Survey.door_area)
        await callback.message.answer(tr("survey.door.area", locale))
    elif method == "dimensions":
        await state.set_state(Survey.door_dimensions)
        await callback.message.answer(tr("survey.door.dimensions", locale))
    elif method == "editor":
        from .opening_editor import start_editor

        await start_editor(callback.message, state, "door")
    elif method == "groups":
        await state.set_state(Survey.door_groups)
        await callback.message.answer(tr("expert.door_prompt", locale))
    else:
        await callback.answer(tr("common.invalid_option", locale), show_alert=True)
        return
    await callback.answer()


@router.message(Survey.door_area)
async def door_area(message: Message, state: FSMContext) -> None:
    try:
        area = _nonnegative(message.text)
        data = await state.get_data()
        if area <= 0:
            raise ValueError("площадь дверей должна быть больше нуля")
        if area + data["window_area"] > data["wall_gross_area"]:
            raise ValueError("окна и двери больше площади стен")
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(door_area=area, door_groups=[])
    await _ask_door_type(message, state)


@router.message(Survey.door_dimensions)
async def door_dimensions(message: Message, state: FSMContext) -> None:
    try:
        dimensions = parse_dimensions(message.text)
        if len(dimensions) != 1:
            raise ValueError("укажите размер одной типовой двери")
        data = await state.get_data()
        area = dimensions[0][0] * dimensions[0][1] * data["door_count"]
        if area + data["window_area"] > data["wall_gross_area"]:
            raise ValueError("окна и двери больше площади стен")
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(door_area=area, door_groups=[])
    await _ask_door_type(message, state)


@router.message(Survey.door_groups)
async def door_groups(message: Message, state: FSMContext) -> None:
    try:
        groups = parse_door_groups(message.text)
        data = await state.get_data()
        if sum(group["count"] for group in groups) != data["door_count"]:
            raise ValueError("сумма количества в группах не совпадает с числом дверей")
        area = sum(group["area_m2"] for group in groups)
        if area + data["window_area"] > data["wall_gross_area"]:
            raise ValueError("окна и двери больше площади стен")
        known_walls = {
            group["name"].casefold(): group["name"] for group in (data.get("wall_groups") or [])
        }
        gross_by_wall = {
            group["name"]: group["gross_area_m2"] for group in (data.get("wall_groups") or [])
        }
        assigned: dict[str, float] = {}
        for group in groups:
            if group["wall_name"]:
                canonical = known_walls.get(group["wall_name"].casefold())
                if canonical is None:
                    raise ValueError(f"не найдена стена «{group['wall_name']}»")
                group["wall_name"] = canonical
                assigned[canonical] = assigned.get(canonical, 0) + group["area_m2"]
        window_assigned: dict[str, float] = {}
        for group in data.get("window_groups") or []:
            if group.get("wall_name"):
                wall = group["wall_name"]
                window_assigned[wall] = window_assigned.get(wall, 0) + group["area_m2"]
        for wall, door_area_on_wall in assigned.items():
            if door_area_on_wall + window_assigned.get(wall, 0) > gross_by_wall[wall]:
                raise ValueError(f"окна и двери на стене «{wall}» больше её площади")
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(door_groups=groups, door_area=area, door_u_value=None)
    await _advance_after_openings(message, state)


@router.callback_query(Survey.door_type, F.data.startswith("door_type:"))
async def door_type(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    if key not in DOORS:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(door_type=key, door_u_value=DOORS[key].u_value)
    await _advance_after_openings(callback.message, state)
    await callback.answer()
