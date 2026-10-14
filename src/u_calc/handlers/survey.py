import asyncio
import logging
import math
import re
import secrets

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.types.error_event import ErrorEvent

from ..i18n import translate as tr
from ..keyboards import keyboard
from ..parsing import (
    parse_linear_thermal_bridges,
    parse_number,
    parse_triplet,
)
from ..states import Survey
from ..storage import CalculationRepository
from .boundaries import (
    _advance_after_openings as _advance_after_openings,
)
from .boundaries import (
    _ask_adjacent_mode,
    _ask_ceiling,
    _ask_floor_boundary,
    _ask_ground_exterior_sides,
    _ask_ground_floor_construction,
    _ask_ground_insulation,
    _ask_heated_neighbor_mode,
    _ask_surface_insulated,
    _ask_surface_insulation_material,
    _ask_surface_material,
    _temperature,  # noqa: F401 - compatibility re-export
    ceiling_boundary,  # noqa: F401 - compatibility re-export
    floor_boundary,  # noqa: F401 - compatibility re-export
    ground_exterior_sides,  # noqa: F401 - compatibility re-export
    ground_floor_construction,  # noqa: F401 - compatibility re-export
    surface_adjacent_mode,  # noqa: F401 - compatibility re-export
    surface_insulated,  # noqa: F401 - compatibility re-export
    surface_insulation_material,  # noqa: F401 - compatibility re-export
    surface_insulation_thickness,  # noqa: F401 - compatibility re-export
    surface_material,  # noqa: F401 - compatibility re-export
    surface_thickness,  # noqa: F401 - compatibility re-export
)
from .climate import _ask_climate
from .common import bounded_text
from .common import conductivity as _conductivity  # noqa: F401 - compatibility re-export
from .common import (
    input_error as _error,
)
from .common import (
    nonnegative as _nonnegative,  # noqa: F401 - compatibility re-export
)
from .common import (
    parse_count as _parse_count,  # noqa: F401 - compatibility re-export
)
from .common import (
    state_locale as _state_locale,
)
from .openings import (
    _ask_door_method,
    _ask_door_type,
    _ask_doors,
    _ask_window_method,
    _ask_window_type,
    _ask_windows,
)
from .openings import (
    door_area as door_area,
)
from .openings import (
    door_count as door_count,
)
from .openings import (
    door_dimensions as door_dimensions,
)
from .openings import (
    door_groups as door_groups,
)
from .openings import (
    door_method as door_method,
)
from .openings import (
    door_type as door_type,
)
from .openings import (
    window_area as window_area,
)
from .openings import (
    window_count as window_count,
)
from .openings import (
    window_dimensions as window_dimensions,
)
from .openings import (
    window_groups as window_groups,
)
from .openings import (
    window_method as window_method,
)
from .openings import (
    window_type as window_type,
)
from .result import _ask_safety_factor
from .walls import (
    _ask_wall_insulated,
    _ask_wall_insulation_material,
    _ask_wall_material,
    _ask_wall_method,
)
from .walls import insulated as insulated
from .walls import insulation_custom_lambda as insulation_custom_lambda
from .walls import insulation_material as insulation_material
from .walls import insulation_thickness as insulation_thickness
from .walls import wall_area as wall_area
from .walls import wall_custom_lambda as wall_custom_lambda
from .walls import wall_dimensions as wall_dimensions
from .walls import wall_groups as wall_groups
from .walls import wall_material as wall_material
from .walls import wall_method as wall_method
from .walls import wall_thickness as wall_thickness

router = Router(name=__name__)
logger = logging.getLogger(__name__)

_SAFE_CALCULATION_REFERENCE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@router.message(Command("new"))
async def start(
    message: Message,
    state: FSMContext,
    repository: CalculationRepository | None = None,
) -> None:
    await state.clear()
    profile = None
    locale = "ru"
    prepared_by = ""
    if repository is not None:
        settings = await asyncio.to_thread(repository.get_user_settings, message.from_user.id)
        locale = settings.locale
        prepared_by = settings.prepared_by
        if settings.default_profile_id is not None:
            profile = await asyncio.to_thread(
                repository.get_profile,
                message.from_user.id,
                settings.default_profile_id,
            )
    await state.update_data(
        locale=locale,
        prepared_by=prepared_by,
        profile_defaults=dict(profile.settings) if profile else {},
        applied_profile_id=profile.id if profile else None,
        applied_profile_name=profile.name if profile else None,
    )
    await state.set_state(Survey.calculation_mode)
    profile_note = tr("survey.profile_applied", locale, name=profile.name) if profile else ""
    await message.answer(
        tr("survey.start", locale, profile_note=profile_note),
        reply_markup=keyboard(
            [
                (tr("survey.mode.quick", locale), "mode:quick"),
                (tr("survey.mode.advanced", locale), "mode:advanced"),
            ],
            1,
            navigation=False,
        ),
    )


async def _ask_indoor(message: Message, state: FSMContext, outdoor: float) -> None:
    data = await state.get_data()
    locale = str(data.get("locale") or "ru")
    defaults = data.get("profile_defaults", {})
    items: list[tuple[str, str]] = []
    try:
        default = float(defaults["indoor"])
    except (KeyError, TypeError, ValueError):
        default = math.nan
    if math.isfinite(default) and outdoor < default <= 35:
        items.append(
            (
                tr("survey.from_profile_temperature", locale, temperature=f"{default:g}"),
                f"profile_indoor:{default:g}",
            )
        )
    await state.set_state(Survey.indoor)
    await message.answer(
        tr("survey.indoor", locale, outdoor=f"{outdoor:g}"),
        reply_markup=keyboard(items, 1, locale=locale) if items else None,
    )


async def _accept_indoor(message: Message, state: FSMContext, value: float) -> None:
    data = await state.get_data()
    if value <= data["outdoor"]:
        raise ValueError("внутренняя температура должна быть выше наружной")
    await state.update_data(indoor=value)
    await state.set_state(Survey.dimensions)
    await message.answer(tr("survey.dimensions", await _state_locale(state)))


@router.callback_query(Survey.calculation_mode, F.data.startswith("mode:"))
async def calculation_mode(callback: CallbackQuery, state: FSMContext) -> None:
    mode = callback.data.split(":", 1)[1]
    if mode not in {"quick", "advanced"}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(calculation_mode=mode)
    await state.set_state(Survey.building_type)
    locale = await _state_locale(state)
    await callback.message.answer(
        tr("survey.object.question", locale),
        reply_markup=keyboard(
            [
                (tr("survey.object.apartment", locale), "type:apartment"),
                (tr("survey.object.house", locale), "type:house"),
            ],
            locale=locale,
        ),
    )
    await callback.answer()


@router.message(Command("resume"))
async def resume_draft(
    message: Message, state: FSMContext, repository: CalculationRepository
) -> None:
    draft = await asyncio.to_thread(repository.load_draft, message.from_user.id)
    if draft is None:
        await message.answer(tr("survey.draft_missing", await _state_locale(state)))
        return
    await state.set_data(draft.data)
    await state.set_state(draft.current_step)
    await message.answer(tr("survey.draft_restored", await _state_locale(state)))
    await _render_current_step(message, state)


@router.message(Command("discard_draft"))
async def discard_draft(
    message: Message, state: FSMContext, repository: CalculationRepository
) -> None:
    locale = await _state_locale(state)
    await state.clear()
    deleted = await asyncio.to_thread(repository.delete_draft, message.from_user.id)
    await message.answer(
        tr("survey.draft_deleted", locale) if deleted else tr("survey.draft_missing", locale)
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    locale = await _state_locale(state)
    await state.clear()
    await message.answer(tr("survey.cancelled", locale))


async def _go_back(state: FSMContext) -> bool:
    data = await state.get_data()
    stack = list(data.get("_back_stack", []))
    if not stack:
        return False
    snapshot = stack.pop()
    restored = dict(snapshot["data"])
    restored["_back_stack"] = stack
    await state.set_data(restored)
    await state.set_state(snapshot["state"])
    return True


async def _current_state_name(state: FSMContext) -> str | None:
    getter = getattr(state, "get_state", None)
    if getter is not None:
        return await getter()
    value = getattr(state, "state", None)
    return getattr(value, "state", value)


async def _render_current_step(message: Message, state: FSMContext) -> None:
    """Render a fresh prompt after back/resume instead of relying on old messages."""
    from .airflow import render_airflow_step
    from .boundaries import render_boundary_step
    from .bridge_editor import render_editor_step as render_bridge_editor_step
    from .climate import render_climate_step
    from .opening_editor import render_editor_step
    from .result import render_result_step
    from .wall_editor import render_editor_step as render_wall_editor_step

    if await render_editor_step(message, state):
        return
    if await render_bridge_editor_step(message, state):
        return
    if await render_wall_editor_step(message, state):
        return
    if await render_airflow_step(message, state):
        return
    if await render_boundary_step(message, state):
        return
    if await render_climate_step(message, state):
        return
    if await render_result_step(message, state):
        return
    current = await _current_state_name(state)
    data = await state.get_data()
    locale = str(data.get("locale") or "ru")
    if current == Survey.calculation_mode.state:
        await message.answer(
            tr("survey.start", locale, profile_note=""),
            reply_markup=keyboard(
                [
                    (tr("survey.mode.quick", locale), "mode:quick"),
                    (tr("survey.mode.advanced", locale), "mode:advanced"),
                ],
                1,
                navigation=False,
            ),
        )
        return
    if current == Survey.building_type.state:
        await message.answer(
            tr("survey.object.question", locale),
            reply_markup=keyboard(
                [
                    (tr("survey.object.apartment", locale), "type:apartment"),
                    (tr("survey.object.house", locale), "type:house"),
                ]
            ),
        )
        return
    if current == Survey.apartment_position.state:
        await _ask_apartment_position(message, state)
        return
    if current == Survey.indoor.state and "outdoor" in data:
        await _ask_indoor(message, state, float(data["outdoor"]))
        return
    if current == Survey.wall_method.state:
        await _ask_wall_method(message, state)
        return
    if current == Survey.wall_groups.state:
        await message.answer(tr("expert.wall_prompt", locale))
        return
    if current == Survey.wall_material.state:
        await _ask_wall_material(message, state)
        return
    if current == Survey.insulated.state:
        await _ask_wall_insulated(message, state)
        return
    if current == Survey.insulation_material.state:
        await _ask_wall_insulation_material(message, state)
        return
    if current == Survey.window_count.state:
        await _ask_windows(message, state)
        return
    if current == Survey.window_method.state:
        await _ask_window_method(message, state)
        return
    if current == Survey.window_groups.state:
        await message.answer(tr("expert.window_prompt", locale))
        return
    if current == Survey.window_type.state:
        await _ask_window_type(message, state)
        return
    if current == Survey.door_count.state:
        await _ask_doors(message, state)
        return
    if current == Survey.door_method.state:
        await _ask_door_method(message, state)
        return
    if current == Survey.door_groups.state:
        await message.answer(tr("expert.door_prompt", locale))
        return
    if current == Survey.door_type.state:
        await _ask_door_type(message, state)
        return
    if current == Survey.floor_boundary.state:
        await _ask_floor_boundary(message, state)
        return
    if current == Survey.ceiling_boundary.state:
        await _ask_ceiling(message, state)
        return
    if current == Survey.surface_adjacent_mode.state:
        surface = str(data.get("active_surface") or "floor")
        boundary = str(data.get("active_boundary") or "unheated")
        if boundary == "heated":
            await _ask_heated_neighbor_mode(message, state, surface)
        else:
            await _ask_adjacent_mode(message, state, surface, boundary)
        return
    if current == Survey.ground_exterior_sides.state:
        await _ask_ground_exterior_sides(message, state)
        return
    if current == Survey.ground_floor_construction.state:
        await _ask_ground_floor_construction(message, state)
        return
    if current == Survey.surface_material.state:
        await _ask_surface_material(message, state, str(data.get("active_surface") or "floor"))
        return
    if current == Survey.surface_insulated.state:
        if (
            data.get("active_surface") == "floor"
            and data.get("active_boundary") == "ground"
            and data.get("floor_ground_method") == "zonal"
        ):
            await _ask_ground_insulation(message, state)
        else:
            await _ask_surface_insulated(message, state)
        return
    if current == Survey.surface_insulation_material.state:
        await _ask_surface_insulation_material(message, state)
        return
    if current == Survey.thermal_bridges.state:
        await _ask_thermal_bridges(message, state)
        return
    prompts = {
        Survey.object_name.state: tr("survey.object_name", locale),
        Survey.dimensions.state: tr("survey.dimensions", locale),
        Survey.wall_area.state: tr("survey.wall.area", locale),
        Survey.wall_dimensions.state: tr("survey.wall.dimensions", locale),
        Survey.wall_custom_lambda.state: tr("survey.wall.custom_lambda", locale),
        Survey.wall_thickness.state: tr("survey.wall.custom_thickness", locale),
        Survey.insulation_custom_lambda.state: tr("survey.wall.insulation_lambda", locale),
        Survey.insulation_thickness.state: tr("survey.wall.custom_insulation_thickness", locale),
        Survey.window_area.state: tr("survey.window.area", locale),
        Survey.window_dimensions.state: tr("survey.window.dimensions", locale),
        Survey.door_area.state: tr("survey.door.area", locale),
        Survey.door_dimensions.state: tr("survey.door.dimensions", locale),
        Survey.surface_adjacent_temperature.state: tr("survey.adjacent.temperature", locale),
        Survey.surface_custom_lambda.state: tr("survey.wall.custom_lambda", locale),
        Survey.surface_thickness.state: tr("survey.wall.custom_thickness", locale),
        Survey.surface_insulation_custom_lambda.state: tr("survey.wall.insulation_lambda", locale),
        Survey.surface_insulation_thickness.state: tr(
            "survey.wall.custom_insulation_thickness", locale
        ),
        Survey.thermal_bridge_details.state: tr("expert.bridge_prompt", locale),
    }
    await message.answer(
        prompts.get(
            current,
            tr("survey.resume_fallback", locale),
        )
    )


@router.message(Command("back"))
async def back_command(message: Message, state: FSMContext) -> None:
    locale = await _state_locale(state)
    if await _go_back(state):
        await message.answer(tr("survey.back_restored", locale))
        await _render_current_step(message, state)
    else:
        await message.answer(tr("survey.back_missing", locale))


@router.callback_query(F.data == "nav:back")
async def back_callback(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _state_locale(state)
    if await _go_back(state):
        await callback.message.answer(tr("survey.back_restored", locale))
        await _render_current_step(callback.message, state)
        await callback.answer()
    else:
        await callback.answer(tr("survey.back_missing_alert", locale), show_alert=True)


@router.callback_query(F.data == "nav:cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _state_locale(state)
    await state.clear()
    await callback.message.answer(tr("survey.cancelled", locale))
    await callback.answer()


@router.callback_query(Survey.building_type, F.data.startswith("type:"))
async def building_type(callback: CallbackQuery, state: FSMContext) -> None:
    kind = callback.data.split(":", 1)[1]
    if kind not in {"apartment", "house"}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(building_type=kind)
    if kind == "apartment":
        await _ask_apartment_position(callback.message, state)
        await callback.answer()
        return
    await state.update_data(apartment_position=None)
    await _ask_object_name(callback.message, state)
    await callback.answer()


async def _ask_apartment_position(message: Message, state: FSMContext) -> None:
    locale = await _state_locale(state)
    await state.set_state(Survey.apartment_position)
    await message.answer(
        tr("survey.position.question", locale),
        reply_markup=keyboard(
            [
                (tr("survey.position.middle", locale), "position:middle"),
                (tr("survey.position.first", locale), "position:first"),
                (tr("survey.position.last", locale), "position:last"),
                (tr("survey.position.first_last", locale), "position:first_last"),
            ],
            1,
            locale=locale,
        ),
    )


async def _ask_object_name(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.object_name)
    await message.answer(tr("survey.object_name", await _state_locale(state)))


@router.message(Survey.object_name)
async def object_name(message: Message, state: FSMContext) -> None:
    try:
        value = bounded_text(message.text, minimum=1, maximum=120, label="Название объекта")
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(object_name=value)
    await _ask_climate(message, state)


@router.callback_query(Survey.apartment_position, F.data.startswith("position:"))
async def apartment_position(callback: CallbackQuery, state: FSMContext) -> None:
    position = callback.data.split(":", 1)[1]
    if position not in {"middle", "first", "last", "first_last"}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(apartment_position=position)
    await _ask_object_name(callback.message, state)
    await callback.answer()


@router.message(Survey.indoor)
async def indoor(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text)
        await _accept_indoor(message, state, value)
    except ValueError as exc:
        await _error(message, exc, state)


@router.callback_query(Survey.indoor, F.data.startswith("profile_indoor:"))
async def profile_indoor(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        value = float(callback.data.split(":", 1)[1])
        await _accept_indoor(callback.message, state, value)
    except (IndexError, ValueError, KeyError) as exc:
        await callback.answer(str(exc) or "Некорректная температура", show_alert=True)
        return
    await callback.answer()


@router.message(Survey.dimensions)
async def dimensions(message: Message, state: FSMContext) -> None:
    try:
        length, width, height = parse_triplet(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(
        length=length, width=width, height=height, volume=length * width * height
    )
    await _ask_wall_method(message, state)


async def _ask_thermal_bridges(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.thermal_bridges)
    locale = await _state_locale(state)
    await message.answer(
        tr("survey.bridges.question", locale),
        reply_markup=keyboard(
            [
                (tr("survey.bridges.zero", locale), "bridges:0"),
                (tr("survey.bridges.good", locale), "bridges:0.05"),
                (tr("survey.bridges.normal", locale), "bridges:0.10"),
                (tr("survey.bridges.weak", locale), "bridges:0.15"),
                (tr("survey.bridges.exact", locale), "bridges:exact"),
                (tr("survey.bridges.import", locale), "bridges:import"),
            ],
            1,
            locale=locale,
        ),
    )


@router.callback_query(Survey.thermal_bridges, F.data.startswith("bridges:"))
async def thermal_bridges(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    value = callback.data.split(":", 1)[1]
    if value == "exact":
        from .bridge_editor import start_editor

        await start_editor(callback.message, state)
        await callback.answer()
        return
    if value == "import":
        await state.set_state(Survey.thermal_bridge_details)
        await callback.message.answer(tr("expert.bridge_prompt", await _state_locale(state)))
        await callback.answer()
        return
    if value not in {"0", "0.05", "0.10", "0.15"}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(
        thermal_bridge_factor=float(value),
        linear_thermal_bridges=[],
    )
    await _ask_safety_factor(callback.message, state)
    await callback.answer()


@router.message(Survey.thermal_bridge_details)
async def thermal_bridge_details(message: Message, state: FSMContext) -> None:
    try:
        bridges = parse_linear_thermal_bridges(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(
        thermal_bridge_factor=0.0,
        linear_thermal_bridges=bridges,
    )
    await _ask_safety_factor(message, state)


@router.callback_query()
async def stale_callback(callback: CallbackQuery, repository: CalculationRepository) -> None:
    settings = await asyncio.to_thread(repository.get_user_settings, callback.from_user.id)
    await callback.answer(tr("common.stale", settings.locale), show_alert=True)


def _safe_calculation_reference(value: object) -> str | int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and _SAFE_CALCULATION_REFERENCE.fullmatch(value):
        return value
    return None


def _handler_reference(exception: BaseException) -> str | None:
    """Return the deepest application handler frame without logging user input."""
    reference = None
    traceback = exception.__traceback__
    while traceback is not None:
        module = traceback.tb_frame.f_globals.get("__name__")
        if isinstance(module, str) and module.startswith("u_calc.handlers."):
            reference = f"{module}.{traceback.tb_frame.f_code.co_name}"
        traceback = traceback.tb_next
    return reference


async def global_error_handler(
    event: ErrorEvent,
    repository: CalculationRepository,
    state: FSMContext | None = None,
) -> bool:
    incident_id = secrets.token_hex(4)
    update = event.update
    message = update.message
    callback = update.callback_query
    user = (message or callback).from_user if (message or callback) else None
    exception = event.exception
    handler_ref = _handler_reference(exception)
    calculation_ref = None
    if state is not None:
        try:
            state_data = await state.get_data()
            calculation_ref = _safe_calculation_reference(
                state_data.get("calculation_id")
                or state_data.get("calculation_request_id")
            )
        except Exception:
            logger.exception(
                "Failed to resolve calculation reference for error log incident_id=%s",
                incident_id,
            )
    logger.error(
        "Unhandled Telegram update error incident_id=%s handler_ref=%s user_id=%s "
        "update_id=%s calculation_ref=%s",
        incident_id,
        handler_ref,
        getattr(user, "id", None),
        update.update_id,
        calculation_ref,
        exc_info=(type(exception), exception, exception.__traceback__),
    )
    locale = "ru"
    if user is not None:
        try:
            locale = await asyncio.to_thread(repository.get_saved_locale, user.id)
        except Exception:
            logger.exception(
                "Failed to resolve locale for error notification incident_id=%s",
                incident_id,
            )
    text = tr("common.unhandled", locale, incident_id=incident_id)
    try:
        if callback:
            await callback.answer(tr("common.internal", locale), show_alert=True)
            if callback.message:
                await callback.message.answer(text)
        elif message:
            await message.answer(text)
    except Exception:
        logger.exception("Failed to notify user about handler error incident_id=%s", incident_id)
    return True
