"""Telegram flow for floor, ceiling, attic, basement and ground boundaries."""

import math

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..catalog import MATERIALS, SELECTABLE_MATERIALS
from ..i18n import translate as tr
from ..keyboards import keyboard
from ..models import Boundary
from ..parsing import parse_number
from ..states import Survey
from .airflow import _ask_air_changes

router = Router(name=__name__)


async def _state_locale(state: FSMContext) -> str:
    return str((await state.get_data()).get("locale") or "ru")


async def _error(message: Message, exc: ValueError, state: FSMContext) -> None:
    locale = await _state_locale(state)
    detail = str(exc) if locale == "ru" else tr("common.invalid_input", locale)
    await message.answer(tr("common.retry", locale, message=detail))


def _temperature(text: str | None) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите температуру числом, например -18") from exc
    if not math.isfinite(value) or not -80 <= value <= 70:
        raise ValueError("Ожидается температура от -80 до +70 °C")
    return value


def _conductivity(text: str | None) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите λ числом, например 0,041") from exc
    if not math.isfinite(value) or not 0.005 <= value <= 5:
        raise ValueError("λ должна быть от 0,005 до 5 Вт/(м·К)")
    return value


def _material_name(key: str, locale: str) -> str:
    return tr(f"material.{key}", locale)


async def _advance_after_openings(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    position = data.get("apartment_position")
    advanced = data.get("calculation_mode") == "advanced"
    if position == "middle":
        await state.update_data(floor_boundary="heated", ceiling_boundary="heated")
        if advanced:
            await _ask_heated_neighbor_mode(message, state, "floor")
            return
        await _ask_air_changes(message, state)
        return
    if position == "last":
        await state.update_data(floor_boundary="heated")
        if advanced:
            await _ask_heated_neighbor_mode(message, state, "floor")
            return
        await _ask_ceiling(message, state)
        return
    if position == "first":
        await state.update_data(ceiling_boundary="heated")
    await _ask_floor_boundary(message, state)


async def _ask_floor_boundary(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.floor_boundary)
    locale = await _state_locale(state)
    await message.answer(
        tr("survey.boundary.floor", locale),
        reply_markup=keyboard(
            [
                (tr("survey.boundary.heated_neighbor", locale), "floor:heated"),
                (tr("survey.boundary.unheated_basement", locale), "floor:unheated"),
                (tr("survey.boundary.ground", locale), "floor:ground"),
                (tr("survey.boundary.outdoor", locale), "floor:outdoor"),
            ],
            1,
            locale=locale,
        ),
    )


@router.callback_query(Survey.floor_boundary, F.data.startswith("floor:"))
async def floor_boundary(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    if value not in {item.value for item in Boundary}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    updates: dict[str, object] = {
        "floor_boundary": value,
        "floor_adjacent_temperature": None,
        "floor_neighbor_done": False,
    }
    if value != "ground":
        updates.update(
            floor_ground_method=None,
            ground_exterior_sides=None,
            floor_on_joists=False,
        )
    await state.update_data(**updates)
    if value == "heated":
        await _ask_heated_neighbor_mode(callback.message, state, "floor")
    elif value in {"unheated", "ground"}:
        await _ask_adjacent_mode(callback.message, state, "floor", value)
    else:
        await _ask_surface_material(callback.message, state, "floor")
    await callback.answer()


async def _ask_ceiling(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("ceiling_boundary") == "heated":
        if data.get("calculation_mode") == "advanced" and not data.get("ceiling_neighbor_done"):
            await _ask_heated_neighbor_mode(message, state, "ceiling")
            return
        await _ask_air_changes(message, state)
        return
    await state.set_state(Survey.ceiling_boundary)
    locale = await _state_locale(state)
    await message.answer(
        tr("survey.boundary.ceiling", locale),
        reply_markup=keyboard(
            [
                (tr("survey.boundary.heated_neighbor", locale), "ceiling:heated"),
                (tr("survey.boundary.unheated_attic", locale), "ceiling:unheated"),
                (tr("survey.boundary.roof", locale), "ceiling:outdoor"),
            ],
            1,
            locale=locale,
        ),
    )


@router.callback_query(Survey.ceiling_boundary, F.data.startswith("ceiling:"))
async def ceiling_boundary(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    if value not in {"heated", "unheated", "outdoor"}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(
        ceiling_boundary=value,
        ceiling_adjacent_temperature=None,
        ceiling_neighbor_done=False,
    )
    if value == "heated":
        await _ask_heated_neighbor_mode(callback.message, state, "ceiling")
    elif value == "unheated":
        await _ask_adjacent_mode(callback.message, state, "ceiling", value)
    else:
        await _ask_surface_material(callback.message, state, "ceiling")
    await callback.answer()


async def _ask_adjacent_mode(
    message: Message,
    state: FSMContext,
    surface: str,
    boundary: str,
) -> None:
    await state.update_data(active_surface=surface, active_boundary=boundary)
    await state.set_state(Survey.surface_adjacent_mode)
    locale = await _state_locale(state)
    zone = tr(
        "survey.adjacent.basement" if surface == "floor" else "survey.adjacent.attic",
        locale,
    )
    estimate = tr(
        "survey.adjacent.ground_estimate"
        if boundary == "ground"
        else "survey.adjacent.unheated_estimate",
        locale,
    )
    choices = [
        (tr("survey.adjacent.manual", locale), f"adjacent:{surface}:manual"),
        (
            tr("survey.adjacent.estimate", locale, estimate=estimate),
            f"adjacent:{surface}:estimate",
        ),
    ]
    if surface == "floor" and boundary == "ground":
        choices.insert(0, (tr("survey.adjacent.zonal", locale), "adjacent:floor:zonal"))
    await message.answer(
        tr("survey.adjacent.question", locale, zone=zone),
        reply_markup=keyboard(choices, 1, locale=locale),
    )


async def _ask_heated_neighbor_mode(message: Message, state: FSMContext, surface: str) -> None:
    await state.update_data(active_surface=surface, active_boundary="heated")
    await state.set_state(Survey.surface_adjacent_mode)
    locale = await _state_locale(state)
    zone = tr("survey.neighbor.below" if surface == "floor" else "survey.neighbor.above", locale)
    await message.answer(
        tr("survey.neighbor.question", locale, zone=zone),
        reply_markup=keyboard(
            [
                (tr("survey.neighbor.same", locale), f"adjacent:{surface}:same"),
                (tr("survey.neighbor.manual", locale), f"adjacent:{surface}:manual"),
            ],
            1,
            locale=locale,
        ),
    )


async def _ask_ground_insulation(message: Message, state: FSMContext) -> None:
    await state.update_data(active_surface="floor")
    await state.set_state(Survey.surface_insulated)
    locale = await _state_locale(state)
    await message.answer(
        tr("survey.ground.insulation", locale),
        reply_markup=keyboard(
            [(tr("common.yes", locale), "sins:yes"), (tr("common.no", locale), "sins:no")],
            locale=locale,
        ),
    )


async def _ask_ground_exterior_sides(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.ground_exterior_sides)
    locale = await _state_locale(state)
    await message.answer(
        tr("survey.ground.sides", locale),
        reply_markup=keyboard(
            [
                (tr("survey.ground.sides.all", locale), "gsides:n,e,s,w"),
                (tr("survey.ground.sides.n", locale), "gsides:n"),
                (tr("survey.ground.sides.e", locale), "gsides:e"),
                (tr("survey.ground.sides.s", locale), "gsides:s"),
                (tr("survey.ground.sides.w", locale), "gsides:w"),
                (tr("survey.ground.sides.ns", locale), "gsides:n,s"),
                (tr("survey.ground.sides.ew", locale), "gsides:e,w"),
                (tr("survey.ground.sides.ne", locale), "gsides:n,e"),
                (tr("survey.ground.sides.es", locale), "gsides:e,s"),
                (tr("survey.ground.sides.sw", locale), "gsides:s,w"),
                (tr("survey.ground.sides.wn", locale), "gsides:w,n"),
                (tr("survey.ground.sides.no_n", locale), "gsides:e,s,w"),
                (tr("survey.ground.sides.no_e", locale), "gsides:n,s,w"),
                (tr("survey.ground.sides.no_s", locale), "gsides:n,e,w"),
                (tr("survey.ground.sides.no_w", locale), "gsides:n,e,s"),
                (tr("survey.ground.sides.complex", locale), "gsides:complex"),
            ],
            2,
            locale=locale,
        ),
    )


async def _ask_ground_floor_construction(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.ground_floor_construction)
    locale = await _state_locale(state)
    await message.answer(
        tr("survey.ground.construction", locale),
        reply_markup=keyboard(
            [
                (tr("survey.ground.solid", locale), "ground_floor:solid"),
                (tr("survey.ground.joists", locale), "ground_floor:joists"),
            ],
            1,
            locale=locale,
        ),
    )


@router.callback_query(Survey.ground_exterior_sides, F.data.startswith("gsides:"))
async def ground_exterior_sides(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data.split(":", 1)[1]
    if code == "complex":
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        await callback.message.answer(
            tr("survey.ground.complex_help", await _state_locale(state))
        )
        return
    mapping = {"n": "north", "e": "east", "s": "south", "w": "west"}
    try:
        sides = [mapping[item] for item in code.split(",")]
    except KeyError:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    if len(sides) != len(set(sides)):
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(ground_exterior_sides=sides, ground_plan_shape="rectangle")
    await _ask_ground_floor_construction(callback.message, state)
    await callback.answer()


@router.callback_query(Survey.ground_floor_construction, F.data.startswith("ground_floor:"))
async def ground_floor_construction(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    if value not in {"solid", "joists"}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(floor_on_joists=value == "joists")
    await _ask_ground_insulation(callback.message, state)
    await callback.answer()


@router.callback_query(Survey.surface_adjacent_mode, F.data.startswith("adjacent:"))
async def surface_adjacent_mode(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        _, surface, mode = callback.data.split(":", 2)
    except ValueError:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    data = await state.get_data()
    if surface != data.get("active_surface"):
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    allowed_modes = {"manual", "estimate"}
    if data.get("active_boundary") == "ground":
        allowed_modes.add("zonal")
    if data.get("active_boundary") == "heated":
        allowed_modes.add("same")
    if mode not in allowed_modes:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    if mode == "same" and data.get("active_boundary") == "heated":
        await state.update_data(
            **{
                f"{surface}_adjacent_temperature": None,
                f"{surface}_neighbor_done": True,
            }
        )
        await _finish_surface(callback.message, state, surface)
    elif mode == "manual":
        if surface == "floor":
            await state.update_data(floor_ground_method="temperature")
        await state.set_state(Survey.surface_adjacent_temperature)
        await callback.message.answer(tr("survey.adjacent.temperature", await _state_locale(state)))
    else:
        if surface == "floor":
            method = "zonal" if mode == "zonal" else "factor"
            await state.update_data(floor_ground_method=method)
        await state.update_data(**{f"{surface}_adjacent_temperature": None})
        if mode == "zonal" and surface == "floor":
            await _ask_ground_exterior_sides(callback.message, state)
        else:
            await _ask_surface_material(callback.message, state, surface)
    await callback.answer()


@router.message(Survey.surface_adjacent_temperature)
async def surface_adjacent_temperature(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
        data = await state.get_data()
        if value >= data["indoor"]:
            raise ValueError("температура смежной зоны должна быть ниже температуры внутри")
    except ValueError as exc:
        await _error(message, exc, state)
        return
    surface = data["active_surface"]
    await state.update_data(
        **{
            f"{surface}_adjacent_temperature": value,
            f"{surface}_neighbor_done": data.get("active_boundary") == "heated",
        }
    )
    await _ask_surface_material(message, state, surface)


async def _ask_surface_material(message: Message, state: FSMContext, surface: str) -> None:
    await state.update_data(active_surface=surface)
    await state.set_state(Survey.surface_material)
    locale = await _state_locale(state)
    title = tr("survey.surface.floor" if surface == "floor" else "survey.surface.ceiling", locale)
    keys = ["concrete", "brick_solid", "aerated_d500", "wood"]
    items = [(_material_name(key, locale), f"smat:{key}") for key in keys]
    items.append((tr("survey.wall.material_custom", locale), "smat:custom"))
    await message.answer(
        tr("survey.surface.material", locale, surface=title),
        reply_markup=keyboard(items, 1, locale=locale),
    )


async def _ask_surface_insulated(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.surface_insulated)
    locale = await _state_locale(state)
    await message.answer(
        tr("survey.surface.insulated", locale),
        reply_markup=keyboard(
            [(tr("common.yes", locale), "sins:yes"), (tr("common.no", locale), "sins:no")],
            locale=locale,
        ),
    )


async def _ask_surface_insulation_material(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.surface_insulation_material)
    locale = await _state_locale(state)
    keys = ["mineral_wool", "eps", "xps"]
    items = [(_material_name(key, locale), f"simat:{key}") for key in keys]
    items.append((tr("survey.wall.insulation_custom", locale), "simat:custom"))
    await message.answer(
        tr("survey.surface.insulation", locale),
        reply_markup=keyboard(items, 1, locale=locale),
    )


async def _ask_surface_layer_action(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    surface = str(data.get("active_surface") or "floor")
    layers = data.get(f"{surface}_layers") or []
    locale = await _state_locale(state)
    await state.set_state(Survey.surface_layer_action)
    await message.answer(
        tr("survey.surface.layers.summary", locale, count=len(layers)),
        reply_markup=keyboard(
            [
                (tr("survey.surface.layers.add", locale), "slayer:add"),
                (tr("survey.surface.layers.finish", locale), "slayer:finish"),
            ],
            1,
            locale=locale,
        ),
    )


async def _ask_surface_layer_material(message: Message, state: FSMContext) -> None:
    locale = await _state_locale(state)
    await state.set_state(Survey.surface_layer_material)
    items = [(_material_name(key, locale), f"slmat:{key}") for key in SELECTABLE_MATERIALS]
    items.append((tr("survey.surface.layers.passport", locale), "slmat:custom"))
    await message.answer(
        tr("survey.surface.layers.material", locale),
        reply_markup=keyboard(items, 1, locale=locale),
    )


@router.callback_query(Survey.surface_material, F.data.startswith("smat:"))
async def surface_material(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    surface = data["active_surface"]
    key = callback.data.split(":", 1)[1]
    locale = await _state_locale(state)
    if key == "custom":
        await state.set_state(Survey.surface_custom_lambda)
        await callback.message.answer(tr("survey.wall.custom_lambda", locale))
        await callback.answer()
        return
    if key not in SELECTABLE_MATERIALS:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(
        **{
            f"{surface}_material": key,
            f"{surface}_conductivity": None,
            f"{surface}_layers": None,
        }
    )
    await state.set_state(Survey.surface_thickness)
    await callback.message.answer(
        tr("survey.wall.thickness", locale, material=_material_name(key, locale))
    )
    await callback.answer()


@router.message(Survey.surface_custom_lambda)
async def surface_custom_lambda(message: Message, state: FSMContext) -> None:
    try:
        value = _conductivity(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    data = await state.get_data()
    surface = data["active_surface"]
    await state.update_data(
        **{
            f"{surface}_material": "custom",
            f"{surface}_conductivity": value,
            f"{surface}_layers": None,
        }
    )
    await state.set_state(Survey.surface_thickness)
    await message.answer(tr("survey.wall.custom_thickness", await _state_locale(state)))


@router.message(Survey.surface_thickness)
async def surface_thickness(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(
            message.text,
            minimum=0.1,
            maximum=200,
            label="Толщина слоя",
        )
    except ValueError as exc:
        await _error(message, exc, state)
        return
    data = await state.get_data()
    surface = data["active_surface"]
    thickness = value / 100
    updates: dict[str, object] = {f"{surface}_thickness": thickness}
    if data.get("calculation_mode") == "advanced":
        updates[f"{surface}_layers"] = [
            {
                "material": data[f"{surface}_material"],
                "material_conductivity": data.get(f"{surface}_conductivity"),
                "thickness_m": thickness,
            }
        ]
        updates[f"{surface}_insulation_material"] = None
        updates[f"{surface}_insulation_thickness"] = 0.0
        await state.update_data(**updates)
        await _ask_surface_layer_action(message, state)
        return
    await state.update_data(**updates)
    await _ask_surface_insulated(message, state)


@router.callback_query(Survey.surface_layer_action, F.data.startswith("slayer:"))
async def surface_layer_action(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    surface = str(data.get("active_surface") or "")
    layers = data.get(f"{surface}_layers") if surface in {"floor", "ceiling"} else None
    locale = await _state_locale(state)
    if data.get("calculation_mode") != "advanced" or not isinstance(layers, list) or not layers:
        await callback.answer(tr("common.invalid_option", locale), show_alert=True)
        return
    if action == "finish":
        await _finish_surface(callback.message, state, surface)
    elif action == "add":
        if len(layers) >= 10:
            await callback.answer(tr("survey.surface.layers.limit", locale), show_alert=True)
            return
        await _ask_surface_layer_material(callback.message, state)
    else:
        await callback.answer(tr("common.invalid_option", locale), show_alert=True)
        return
    await callback.answer()


@router.callback_query(Survey.surface_layer_material, F.data.startswith("slmat:"))
async def surface_layer_material(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    locale = await _state_locale(state)
    if key == "custom":
        await state.update_data(
            surface_pending_material="custom",
            surface_pending_conductivity=None,
        )
        await state.set_state(Survey.surface_layer_custom_lambda)
        await callback.message.answer(tr("survey.surface.layers.lambda", locale))
    elif key in SELECTABLE_MATERIALS:
        await state.update_data(
            surface_pending_material=key,
            surface_pending_conductivity=None,
        )
        await state.set_state(Survey.surface_layer_thickness)
        await callback.message.answer(
            tr(
                "survey.surface.layers.thickness",
                locale,
                material=_material_name(key, locale),
            )
        )
    else:
        await callback.answer(tr("common.invalid_option", locale), show_alert=True)
        return
    await callback.answer()


@router.message(Survey.surface_layer_custom_lambda)
async def surface_layer_custom_lambda(message: Message, state: FSMContext) -> None:
    try:
        value = _conductivity(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(
        surface_pending_material="custom",
        surface_pending_conductivity=value,
    )
    await state.set_state(Survey.surface_layer_thickness)
    await message.answer(tr("survey.surface.layers.custom_thickness", await _state_locale(state)))


@router.message(Survey.surface_layer_thickness)
async def surface_layer_thickness(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(
            message.text,
            minimum=0.1,
            maximum=200,
            label="Толщина слоя",
        )
    except ValueError as exc:
        await _error(message, exc, state)
        return
    data = await state.get_data()
    surface = str(data.get("active_surface") or "")
    layers = list(data.get(f"{surface}_layers") or [])
    material = data.get("surface_pending_material")
    if surface not in {"floor", "ceiling"} or not layers or material not in {*MATERIALS, "custom"}:
        await _error(message, ValueError("повреждены данные редактора конструкции"), state)
        return
    if len(layers) >= 10:
        await _error(message, ValueError("допустимо не более 10 слоёв"), state)
        return
    layers.append(
        {
            "material": material,
            "material_conductivity": data.get("surface_pending_conductivity"),
            "thickness_m": value / 100,
        }
    )
    await state.update_data(
        **{
            f"{surface}_layers": layers,
            "surface_pending_material": None,
            "surface_pending_conductivity": None,
        }
    )
    await _ask_surface_layer_action(message, state)


@router.callback_query(Survey.surface_insulated, F.data.startswith("sins:"))
async def surface_insulated(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.data not in {"sins:yes", "sins:no"}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    data = await state.get_data()
    surface = data["active_surface"]
    if callback.data == "sins:no":
        await state.update_data(
            **{f"{surface}_insulation_material": None, f"{surface}_insulation_thickness": 0.0}
        )
        await _finish_surface(callback.message, state, surface)
    else:
        await _ask_surface_insulation_material(callback.message, state)
    await callback.answer()


@router.callback_query(Survey.surface_insulation_material, F.data.startswith("simat:"))
async def surface_insulation_material(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    surface = data["active_surface"]
    key = callback.data.split(":", 1)[1]
    locale = await _state_locale(state)
    if key == "custom":
        await state.set_state(Survey.surface_insulation_custom_lambda)
        await callback.message.answer(tr("survey.wall.insulation_lambda", locale))
        await callback.answer()
        return
    if key not in {"mineral_wool", "eps", "xps"}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(**{f"{surface}_insulation_material": key})
    await state.set_state(Survey.surface_insulation_thickness)
    await callback.message.answer(
        tr("survey.wall.insulation_thickness", locale, material=_material_name(key, locale))
    )
    await callback.answer()


@router.message(Survey.surface_insulation_custom_lambda)
async def surface_insulation_custom_lambda(message: Message, state: FSMContext) -> None:
    try:
        value = _conductivity(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    data = await state.get_data()
    surface = data["active_surface"]
    await state.update_data(
        **{
            f"{surface}_insulation_material": "custom",
            f"{surface}_insulation_conductivity": value,
        }
    )
    await state.set_state(Survey.surface_insulation_thickness)
    await message.answer(tr("survey.wall.custom_insulation_thickness", await _state_locale(state)))


@router.message(Survey.surface_insulation_thickness)
async def surface_insulation_thickness(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    data = await state.get_data()
    surface = data["active_surface"]
    await state.update_data(**{f"{surface}_insulation_thickness": value / 100})
    await _finish_surface(message, state, surface)


async def _finish_surface(message: Message, state: FSMContext, surface: str) -> None:
    if surface == "floor":
        await _ask_ceiling(message, state)
    else:
        await _ask_air_changes(message, state)


async def render_boundary_step(message: Message, state: FSMContext) -> bool:
    """Restore prompts for the multi-layer boundary editor after back or restart."""
    getter = getattr(state, "get_state", None)
    if getter is not None:
        current = await getter()
    else:
        value = getattr(state, "state", None)
        current = getattr(value, "state", value)
    data = await state.get_data()
    locale = str(data.get("locale") or "ru")
    if current == Survey.surface_layer_action.state:
        await _ask_surface_layer_action(message, state)
        return True
    if current == Survey.surface_layer_material.state:
        await _ask_surface_layer_material(message, state)
        return True
    if current == Survey.surface_layer_custom_lambda.state:
        await message.answer(tr("survey.surface.layers.lambda", locale))
        return True
    if current == Survey.surface_layer_thickness.state:
        material = data.get("surface_pending_material")
        if isinstance(material, str) and material in MATERIALS:
            prompt = tr(
                "survey.surface.layers.thickness",
                locale,
                material=_material_name(material, locale),
            )
        else:
            prompt = tr("survey.surface.layers.custom_thickness", locale)
        await message.answer(prompt)
        return True
    return False
