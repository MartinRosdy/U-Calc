"""Quick and expert-import Telegram flows for exterior walls."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..catalog import SELECTABLE_MATERIALS
from ..i18n import translate as tr
from ..keyboards import keyboard
from ..parsing import parse_dimensions, parse_number, parse_wall_groups
from ..states import Survey
from .common import conductivity as _conductivity
from .common import input_error as _error
from .common import material_name as _material_name
from .common import state_locale as _state_locale
from .openings import _ask_windows

router = Router(name=__name__)


async def _ask_wall_material(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.wall_material)
    locale = await _state_locale(state)
    keys = ["brick_solid", "brick_hollow", "aerated_d500", "concrete", "wood"]
    items = [(_material_name(key, locale), f"mat:{key}") for key in keys]
    items.append((tr("survey.wall.material_custom", locale), "mat:custom"))
    await message.answer(
        tr("survey.wall.material", locale),
        reply_markup=keyboard(items, 1, locale=locale),
    )


async def _ask_wall_insulated(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.insulated)
    locale = await _state_locale(state)
    await message.answer(
        tr("survey.wall.insulated", locale),
        reply_markup=keyboard(
            [(tr("common.yes", locale), "ins:yes"), (tr("common.no", locale), "ins:no")],
            locale=locale,
        ),
    )


async def _ask_wall_insulation_material(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.insulation_material)
    locale = await _state_locale(state)
    keys = ["mineral_wool", "eps", "xps"]
    items = [(_material_name(key, locale), f"imat:{key}") for key in keys]
    items.append((tr("survey.wall.insulation_custom", locale), "imat:custom"))
    await message.answer(
        tr("survey.wall.insulation", locale),
        reply_markup=keyboard(items, 1, locale=locale),
    )


async def _ask_wall_method(message: Message, state: FSMContext) -> None:
    locale = await _state_locale(state)
    await state.set_state(Survey.wall_method)
    await message.answer(
        tr("survey.wall_method.question", locale),
        reply_markup=keyboard(
            [
                (tr("survey.wall_method.area", locale), "walls:area"),
                (tr("survey.wall_method.dimensions", locale), "walls:dimensions"),
                (tr("survey.wall_method.perimeter", locale), "walls:perimeter"),
                (tr("survey.wall_method.editor", locale), "walls:editor"),
                (tr("survey.wall_method.import", locale), "walls:groups"),
            ],
            1,
            locale=locale,
        ),
    )


@router.callback_query(Survey.wall_method, F.data.startswith("walls:"))
async def wall_method(callback: CallbackQuery, state: FSMContext) -> None:
    method = callback.data.split(":", 1)[1]
    if method not in {"area", "dimensions", "editor", "groups", "perimeter"}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    if method == "area":
        await state.set_state(Survey.wall_area)
        await callback.message.answer(tr("survey.wall.area", await _state_locale(state)))
    elif method == "dimensions":
        await state.set_state(Survey.wall_dimensions)
        await callback.message.answer(tr("survey.wall.dimensions", await _state_locale(state)))
    elif method == "editor":
        from .wall_editor import start_editor

        await start_editor(callback.message, state)
    elif method == "groups":
        await state.set_state(Survey.wall_groups)
        await callback.message.answer(tr("expert.wall_prompt", await _state_locale(state)))
    else:
        data = await state.get_data()
        area = 2 * (data["length"] + data["width"]) * data["height"]
        await state.update_data(wall_gross_area=area)
        await _ask_wall_material(callback.message, state)
    await callback.answer()


@router.message(Survey.wall_area)
async def wall_area(message: Message, state: FSMContext) -> None:
    try:
        area = parse_number(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(wall_gross_area=area)
    await _ask_wall_material(message, state)


@router.message(Survey.wall_dimensions)
async def wall_dimensions(message: Message, state: FSMContext) -> None:
    try:
        area = sum(width * height for width, height in parse_dimensions(message.text))
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(wall_gross_area=area)
    await _ask_wall_material(message, state)


@router.message(Survey.wall_groups)
async def wall_groups(message: Message, state: FSMContext) -> None:
    try:
        groups = parse_wall_groups(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(
        wall_groups=groups,
        wall_gross_area=sum(item["gross_area_m2"] for item in groups),
        wall_material=None,
        wall_thickness=0.0,
        insulation_material=None,
        insulation_thickness=0.0,
    )
    await _ask_windows(message, state)


@router.callback_query(Survey.wall_material, F.data.startswith("mat:"))
async def wall_material(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    locale = await _state_locale(state)
    if key == "custom":
        await state.set_state(Survey.wall_custom_lambda)
        await callback.message.answer(tr("survey.wall.custom_lambda", locale))
        await callback.answer()
        return
    if key not in SELECTABLE_MATERIALS:
        await callback.answer(tr("common.invalid_option", locale), show_alert=True)
        return
    await state.update_data(wall_material=key)
    await state.set_state(Survey.wall_thickness)
    await callback.message.answer(
        tr("survey.wall.thickness", locale, material=_material_name(key, locale))
    )
    await callback.answer()


@router.message(Survey.wall_custom_lambda)
async def wall_custom_lambda(message: Message, state: FSMContext) -> None:
    try:
        value = _conductivity(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(wall_material="custom", wall_conductivity=value)
    await state.set_state(Survey.wall_thickness)
    await message.answer(tr("survey.wall.custom_thickness", await _state_locale(state)))


@router.message(Survey.wall_thickness)
async def wall_thickness(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(wall_thickness=value / 100)
    await _ask_wall_insulated(message, state)


@router.callback_query(Survey.insulated, F.data.startswith("ins:"))
async def insulated(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.data not in {"ins:yes", "ins:no"}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    if callback.data == "ins:no":
        await state.update_data(insulation_material=None, insulation_thickness=0.0)
        await _ask_windows(callback.message, state)
    else:
        await _ask_wall_insulation_material(callback.message, state)
    await callback.answer()


@router.callback_query(Survey.insulation_material, F.data.startswith("imat:"))
async def insulation_material(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    locale = await _state_locale(state)
    if key == "custom":
        await state.set_state(Survey.insulation_custom_lambda)
        await callback.message.answer(tr("survey.wall.insulation_lambda", locale))
        await callback.answer()
        return
    if key not in {"mineral_wool", "eps", "xps"}:
        await callback.answer(tr("common.invalid_option", locale), show_alert=True)
        return
    await state.update_data(insulation_material=key)
    await state.set_state(Survey.insulation_thickness)
    await callback.message.answer(
        tr(
            "survey.wall.insulation_thickness",
            locale,
            material=_material_name(key, locale),
        )
    )
    await callback.answer()


@router.message(Survey.insulation_custom_lambda)
async def insulation_custom_lambda(message: Message, state: FSMContext) -> None:
    try:
        value = _conductivity(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(
        insulation_material="custom",
        insulation_conductivity=value,
    )
    await state.set_state(Survey.insulation_thickness)
    await message.answer(tr("survey.wall.custom_insulation_thickness", await _state_locale(state)))


@router.message(Survey.insulation_thickness)
async def insulation_thickness(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(insulation_thickness=value / 100)
    await _ask_windows(message, state)
