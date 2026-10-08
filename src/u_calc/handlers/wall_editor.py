"""Button-driven, localized editor for multi-layer wall constructions."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..catalog import MATERIALS
from ..i18n import translate as tr
from ..keyboards import keyboard
from ..parsing import parse_dimensions, parse_number
from ..states import Survey

router = Router(name=__name__)

ORIENTATIONS = (
    "north",
    "north_east",
    "east",
    "south_east",
    "south",
    "south_west",
    "west",
    "north_west",
)


async def _locale(state: FSMContext) -> str:
    return str((await state.get_data()).get("locale") or "ru")


async def _error(message: Message, state: FSMContext, key: str, **values: object) -> None:
    locale = await _locale(state)
    await message.answer(tr("wall.editor.retry", locale, message=tr(key, locale, **values)))


def _material_name(key: str, locale: str) -> str:
    return tr(f"material.{key}", locale)


def _layer_items(prefix: str, locale: str) -> list[tuple[str, str]]:
    items = [(_material_name(key, locale), f"{prefix}:{key}") for key in MATERIALS]
    items.append((tr("wall.editor.passport", locale), f"{prefix}:custom"))
    return items


def _orientation_items(locale: str) -> list[tuple[str, str]]:
    items = [
        (tr(f"wall.editor.orientation.{value}", locale), f"wori:{value}")
        for value in ORIENTATIONS
    ]
    items.append((tr("wall.editor.orientation.unknown", locale), "wori:unknown"))
    return items


async def _ask_orientation(message: Message, state: FSMContext) -> None:
    locale = await _locale(state)
    await state.set_state(Survey.wall_editor_orientation)
    await message.answer(
        tr("wall.editor.orientation", locale),
        reply_markup=keyboard(_orientation_items(locale), 2, locale=locale),
    )


async def start_editor(message: Message, state: FSMContext) -> None:
    await state.update_data(wall_groups=[], wall_editor_edit_index=None)
    await ask_name(message, state)


async def ask_name(message: Message, state: FSMContext) -> None:
    await state.update_data(
        wall_editor_name=None,
        wall_editor_area=None,
        wall_editor_orientation=None,
        wall_editor_material=None,
        wall_editor_material_conductivity=None,
        wall_editor_thickness=None,
        wall_editor_insulation_material=None,
        wall_editor_insulation_conductivity=None,
        wall_editor_insulation_thickness=0.0,
        wall_editor_layers=[],
    )
    await state.set_state(Survey.wall_editor_name)
    await message.answer(tr("wall.editor.name", await _locale(state)))


@router.message(Survey.wall_editor_name)
async def wall_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not 1 <= len(name) <= 60:
        await _error(message, state, "wall.editor.error.name")
        return
    data = await state.get_data()
    if any(item["name"].casefold() == name.casefold() for item in data.get("wall_groups", [])):
        await _error(message, state, "wall.editor.error.duplicate", name=name)
        return
    await state.update_data(wall_editor_name=name)
    await state.set_state(Survey.wall_editor_area)
    await message.answer(tr("wall.editor.area", await _locale(state)))


@router.message(Survey.wall_editor_area)
async def wall_area(message: Message, state: FSMContext) -> None:
    text = message.text or ""
    try:
        if any(separator in text.casefold() for separator in ("x", "х", "×", "*")):
            dimensions = parse_dimensions(text)
            if len(dimensions) != 1:
                raise ValueError
            area = dimensions[0][0] * dimensions[0][1]
        else:
            area = parse_number(text, minimum=0.1, maximum=100_000, label="area")
    except ValueError:
        await _error(message, state, "wall.editor.error.area")
        return
    await state.update_data(wall_editor_area=area)
    await _ask_orientation(message, state)


@router.callback_query(Survey.wall_editor_orientation, F.data.startswith("wori:"))
async def wall_orientation(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    locale = await _locale(state)
    if value == "unknown":
        orientation = None
    elif value in ORIENTATIONS:
        orientation = value
    else:
        await callback.answer(tr("wall.editor.error.orientation", locale), show_alert=True)
        return
    await state.update_data(wall_editor_orientation=orientation)
    await state.set_state(Survey.wall_editor_material)
    keys = ("brick_solid", "brick_hollow", "aerated_d500", "concrete", "wood")
    items = [(_material_name(key, locale), f"wmat:{key}") for key in keys]
    items.append((tr("wall.editor.passport", locale), "wmat:custom"))
    await callback.message.answer(
        tr("wall.editor.material", locale), reply_markup=keyboard(items, 1, locale=locale)
    )
    await callback.answer()


@router.callback_query(Survey.wall_editor_material, F.data.startswith("wmat:"))
async def wall_material(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    locale = await _locale(state)
    if key == "custom":
        await state.set_state(Survey.wall_editor_custom_lambda)
        await callback.message.answer(tr("wall.editor.lambda", locale))
    elif key in MATERIALS:
        await state.update_data(
            wall_editor_material=key, wall_editor_material_conductivity=None
        )
        await state.set_state(Survey.wall_editor_thickness)
        await callback.message.answer(
            tr("wall.editor.thickness", locale, material=_material_name(key, locale))
        )
    else:
        await callback.answer(tr("wall.editor.error.material", locale), show_alert=True)
        return
    await callback.answer()


def _conductivity_value(text: str | None) -> float:
    return parse_number(text, minimum=0.005, maximum=5, label="lambda")


@router.message(Survey.wall_editor_custom_lambda)
async def wall_custom_lambda(message: Message, state: FSMContext) -> None:
    try:
        value = _conductivity_value(message.text)
    except ValueError:
        await _error(message, state, "wall.editor.error.lambda")
        return
    await state.update_data(
        wall_editor_material="custom", wall_editor_material_conductivity=value
    )
    await state.set_state(Survey.wall_editor_thickness)
    await message.answer(tr("wall.editor.base_thickness", await _locale(state)))


@router.message(Survey.wall_editor_thickness)
async def wall_thickness(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text, minimum=0.1, maximum=200, label="thickness")
    except ValueError:
        await _error(message, state, "wall.editor.error.thickness")
        return
    data = await state.get_data()
    await state.update_data(
        wall_editor_thickness=value / 100,
        wall_editor_layers=[
            {
                "material": data["wall_editor_material"],
                "material_conductivity": data.get("wall_editor_material_conductivity"),
                "thickness_m": value / 100,
            }
        ],
    )
    await state.set_state(Survey.wall_editor_insulated)
    locale = await _locale(state)
    await message.answer(
        tr("wall.editor.insulated", locale),
        reply_markup=keyboard(
            [(tr("common.no", locale), "wins:no"), (tr("common.yes", locale), "wins:yes")],
            2,
            locale=locale,
        ),
    )


@router.callback_query(Survey.wall_editor_insulated, F.data.startswith("wins:"))
async def wall_insulated(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    locale = await _locale(state)
    if value == "no":
        await state.update_data(
            wall_editor_insulation_material=None,
            wall_editor_insulation_conductivity=None,
            wall_editor_insulation_thickness=0.0,
        )
        await _finish_group(callback.message, state)
    elif value == "yes":
        await state.set_state(Survey.wall_editor_insulation_material)
        await callback.message.answer(
            tr("wall.editor.insulation", locale),
            reply_markup=keyboard(_layer_items("wimat", locale), 1, locale=locale),
        )
    else:
        await callback.answer(tr("wall.editor.error.option", locale), show_alert=True)
        return
    await callback.answer()


@router.callback_query(Survey.wall_editor_insulation_material, F.data.startswith("wimat:"))
async def insulation_material(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    locale = await _locale(state)
    if key == "custom":
        await state.set_state(Survey.wall_editor_insulation_custom_lambda)
        await callback.message.answer(tr("wall.editor.insulation_lambda", locale))
    elif key in MATERIALS:
        await state.update_data(
            wall_editor_insulation_material=key,
            wall_editor_insulation_conductivity=None,
        )
        await state.set_state(Survey.wall_editor_insulation_thickness)
        await callback.message.answer(
            tr("wall.editor.thickness", locale, material=_material_name(key, locale))
        )
    else:
        await callback.answer(tr("wall.editor.error.insulation", locale), show_alert=True)
        return
    await callback.answer()


@router.message(Survey.wall_editor_insulation_custom_lambda)
async def insulation_custom_lambda(message: Message, state: FSMContext) -> None:
    try:
        value = _conductivity_value(message.text)
    except ValueError:
        await _error(message, state, "wall.editor.error.lambda")
        return
    await state.update_data(
        wall_editor_insulation_material="custom",
        wall_editor_insulation_conductivity=value,
    )
    await state.set_state(Survey.wall_editor_insulation_thickness)
    await message.answer(tr("wall.editor.insulation_thickness", await _locale(state)))


@router.message(Survey.wall_editor_insulation_thickness)
async def insulation_thickness(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text, minimum=0.1, maximum=200, label="thickness")
    except ValueError:
        await _error(message, state, "wall.editor.error.thickness")
        return
    data = await state.get_data()
    layers = list(data.get("wall_editor_layers", []))
    if len(layers) >= 10:
        await _error(message, state, "wall.editor.error.layer_limit")
        return
    layers.append(
        {
            "material": data["wall_editor_insulation_material"],
            "material_conductivity": data.get("wall_editor_insulation_conductivity"),
            "thickness_m": value / 100,
        }
    )
    await state.update_data(
        wall_editor_insulation_thickness=value / 100, wall_editor_layers=layers
    )
    await state.set_state(Survey.wall_editor_more_layers)
    locale = await _locale(state)
    await message.answer(
        tr("wall.editor.layers", locale, count=len(layers)),
        reply_markup=keyboard(
            [
                (tr("wall.editor.add_layer", locale), "wlayer:add"),
                (tr("wall.editor.finish_layers", locale), "wlayer:finish"),
            ],
            1,
            locale=locale,
        ),
    )


@router.callback_query(Survey.wall_editor_more_layers, F.data.startswith("wlayer:"))
async def more_layers(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    locale = str(data.get("locale") or "ru")
    if action == "finish":
        await _finish_group(callback.message, state)
    elif action == "add":
        if len(data.get("wall_editor_layers", [])) >= 10:
            await callback.answer(
                tr("wall.editor.error.layer_limit_alert", locale), show_alert=True
            )
            return
        await state.update_data(
            wall_editor_insulation_material=None,
            wall_editor_insulation_conductivity=None,
            wall_editor_insulation_thickness=0.0,
        )
        await state.set_state(Survey.wall_editor_insulation_material)
        await callback.message.answer(
            tr("wall.editor.next_layer", locale),
            reply_markup=keyboard(_layer_items("wimat", locale), 1, locale=locale),
        )
    else:
        await callback.answer(tr("wall.editor.error.action", locale), show_alert=True)
        return
    await callback.answer()


async def _finish_group(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    groups = list(data.get("wall_groups", []))
    if len(groups) >= 12:
        await _error(message, state, "wall.editor.error.wall_limit")
        return
    layers = list(data.get("wall_editor_layers", []))
    legacy_insulation = layers[1] if len(layers) > 1 else {}
    group = {
        "name": data["wall_editor_name"],
        "gross_area_m2": data["wall_editor_area"],
        "orientation": data.get("wall_editor_orientation"),
        "material": data["wall_editor_material"],
        "material_conductivity": data.get("wall_editor_material_conductivity"),
        "thickness_m": data["wall_editor_thickness"],
        "insulation_material": legacy_insulation.get("material"),
        "insulation_conductivity": legacy_insulation.get("material_conductivity"),
        "insulation_thickness_m": legacy_insulation.get("thickness_m", 0.0),
        "layers": layers,
    }
    edit_index = data.get("wall_editor_edit_index")
    if isinstance(edit_index, int) and 0 <= edit_index <= len(groups):
        groups.insert(edit_index, group)
    else:
        groups.append(group)
    await state.update_data(wall_groups=groups, wall_editor_edit_index=None)
    await show_actions(message, state)


async def show_actions(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    locale = str(data.get("locale") or "ru")
    groups = data.get("wall_groups", [])
    summary = "\n".join(
        tr(
            "wall.editor.summary",
            locale,
            name=item["name"],
            area=f"{item['gross_area_m2']:g}",
            orientation=tr(
                f"wall.editor.orientation.{item.get('orientation') or 'unknown'}",
                locale,
            ),
        )
        for item in groups
    )
    await state.set_state(Survey.wall_editor_action)
    await message.answer(
        tr("wall.editor.saved", locale, count=len(groups), summary=summary),
        reply_markup=keyboard(
            [
                (tr("wall.editor.add_wall", locale), "wedit:add"),
                *[
                    (
                        tr("wall.editor.edit_wall", locale, name=item["name"]),
                        f"wedit:edit:{index}",
                    )
                    for index, item in enumerate(groups)
                ],
                *[
                    (
                        tr("wall.editor.delete_named_wall", locale, name=item["name"]),
                        f"wedit:delete:{index}",
                    )
                    for index, item in enumerate(groups)
                ],
                (tr("wall.editor.finish", locale), "wedit:finish"),
            ],
            1,
            locale=locale,
        ),
    )


@router.callback_query(Survey.wall_editor_action, F.data.startswith("wedit:"))
async def wall_action(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    action = parts[1]
    data = await state.get_data()
    locale = str(data.get("locale") or "ru")
    groups = list(data.get("wall_groups", []))
    if action == "add":
        if len(groups) >= 12:
            await callback.answer(
                tr("wall.editor.error.wall_limit_alert", locale), show_alert=True
            )
            return
        await ask_name(callback.message, state)
    elif action == "edit":
        try:
            index = int(parts[2])
            groups.pop(index)
        except (IndexError, ValueError):
            await callback.answer(tr("wall.editor.error.stale", locale), show_alert=True)
            return
        await state.update_data(wall_groups=groups, wall_editor_edit_index=index)
        await ask_name(callback.message, state)
    elif action == "delete":
        if not groups:
            await callback.answer(tr("wall.editor.error.empty", locale), show_alert=True)
            return
        try:
            index = int(parts[2]) if len(parts) > 2 else len(groups) - 1
            groups.pop(index)
        except (IndexError, ValueError):
            await callback.answer(tr("wall.editor.error.stale", locale), show_alert=True)
            return
        await state.update_data(wall_groups=groups)
        if groups:
            await show_actions(callback.message, state)
        else:
            await ask_name(callback.message, state)
    elif action == "finish":
        if not groups:
            await callback.answer(tr("wall.editor.error.required", locale), show_alert=True)
            return
        await state.update_data(
            wall_gross_area=sum(item["gross_area_m2"] for item in groups),
            wall_material=None,
            wall_thickness=0.0,
            insulation_material=None,
            insulation_thickness=0.0,
        )
        from .survey import _ask_windows

        await _ask_windows(callback.message, state)
    else:
        await callback.answer(tr("wall.editor.error.action", locale), show_alert=True)
        return
    await callback.answer()


async def render_editor_step(message: Message, state: FSMContext) -> bool:
    """Re-render wall editor screens after draft restore or back navigation."""
    getter = getattr(state, "get_state", None)
    if getter is not None:
        current = await getter()
    else:
        value = getattr(state, "state", None)
        current = getattr(value, "state", value)
    if current == Survey.wall_editor_action.state:
        await show_actions(message, state)
        return True
    if current == Survey.wall_editor_orientation.state:
        await _ask_orientation(message, state)
        return True
    prompts = {
        Survey.wall_editor_name.state: "wall.editor.name",
        Survey.wall_editor_area.state: "wall.editor.area",
        Survey.wall_editor_custom_lambda.state: "wall.editor.lambda",
        Survey.wall_editor_thickness.state: "wall.editor.base_thickness",
        Survey.wall_editor_insulation_custom_lambda.state: "wall.editor.insulation_lambda",
        Survey.wall_editor_insulation_thickness.state: "wall.editor.insulation_thickness",
        Survey.wall_editor_more_layers.state: "wall.editor.resume_layers",
    }
    if current in prompts:
        await message.answer(tr(prompts[current], await _locale(state)))
        return True
    return False
