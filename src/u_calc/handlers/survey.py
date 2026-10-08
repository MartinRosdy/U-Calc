import asyncio
import logging
import math
import secrets
from dataclasses import asdict

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.types.error_event import ErrorEvent

from ..catalog import CLIMATES, DOORS, MATERIALS, WINDOWS, ClimateProfile
from ..i18n import translate as tr
from ..keyboards import keyboard
from ..models import Boundary
from ..parsing import (
    parse_dimensions,
    parse_door_groups,
    parse_linear_thermal_bridges,
    parse_number,
    parse_triplet,
    parse_wall_groups,
    parse_window_groups,
)
from ..report import format_telegram_summary
from ..services.building_factory import InvalidCalculationData, climate_from_answers
from ..services.calculation_service import calculate_from_answers
from ..states import Survey
from ..storage import CalculationRepository

router = Router(name=__name__)
logger = logging.getLogger(__name__)


def _nonnegative(text: str | None) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите число, например 12,5") from exc
    if not math.isfinite(value):
        raise ValueError("Значение должно быть конечным числом")
    if not 0 <= value <= 100_000:
        raise ValueError("Значение должно быть от 0 до 100 000")
    return value


def _temperature(text: str) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите температуру числом, например -18") from exc
    if not math.isfinite(value) or not -80 <= value <= 70:
        raise ValueError("Ожидается температура от -80 до +70 °C")
    return value


def _conductivity(text: str) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите λ числом, например 0,041") from exc
    if not math.isfinite(value) or not 0.005 <= value <= 5:
        raise ValueError("λ должна быть от 0,005 до 5 Вт/(м·К)")
    return value


async def _error(message: Message, exc: ValueError, state: FSMContext | None = None) -> None:
    locale = await _state_locale(state) if state is not None else "ru"
    detail = str(exc) if locale == "ru" else tr("common.invalid_input", locale)
    await message.answer(tr("common.retry", locale, message=detail))


async def _state_locale(state: FSMContext) -> str:
    return str((await state.get_data()).get("locale") or "ru")


def _material_name(key: str, locale: str) -> str:
    return tr(f"material.{key}", locale)


async def _send_long_message(message: Message, text: str, limit: int = 3900) -> None:
    """Send text without exceeding Telegram's message length limit."""
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


async def _ask_windows(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.window_count)
    await message.answer(tr("survey.window.count", await _state_locale(state)))


async def _ask_doors(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.door_count)
    await message.answer(tr("survey.door.count", await _state_locale(state)))


def _parse_count(text: str) -> int:
    try:
        value = int(text.strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите целое количество, например 3") from exc
    if value < 0 or value > 500:
        raise ValueError("Количество должно быть от 0 до 500")
    return value


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
    from .bridge_editor import render_editor_step as render_bridge_editor_step
    from .opening_editor import render_editor_step
    from .wall_editor import render_editor_step as render_wall_editor_step

    if await render_editor_step(message, state):
        return
    if await render_bridge_editor_step(message, state):
        return
    if await render_wall_editor_step(message, state):
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
    if current == Survey.climate.state:
        await _ask_climate(message, state)
        return
    if current == Survey.scenario.state:
        profile = climate_from_answers(data)
        if profile is not None:
            await _ask_scenario(message, state, profile)
            return
    if current == Survey.indoor.state and "outdoor" in data:
        await _ask_indoor(message, state, float(data["outdoor"]))
        return
    if current == Survey.wall_method.state:
        await _ask_wall_method(message, state)
        return
    if current == Survey.air_changes.state:
        await _ask_air_changes(message, state)
        return
    if current == Survey.safety_factor.state:
        await _ask_safety_factor(message, state)
        return
    if current == Survey.confirmation.state:
        await _ask_confirmation(message, state)
        return
    prompts = {
        Survey.object_name.state: tr("survey.object_name", locale),
        Survey.custom_outdoor.state: tr("survey.outdoor_manual", locale),
        Survey.custom_city_name.state: tr("survey.city_name", locale),
        Survey.custom_cold_mean.state: tr("survey.custom.cold_mean", locale),
        Survey.custom_design.state: tr("survey.custom.design", locale),
        Survey.custom_extreme.state: tr("survey.custom.extreme", locale),
        Survey.custom_hot_mean.state: tr("survey.custom.hot_mean", locale),
        Survey.custom_hot_max.state: tr("survey.custom.hot_max", locale),
        Survey.dimensions.state: tr("survey.dimensions", locale),
        Survey.wall_area.state: tr("survey.wall.area", locale),
        Survey.wall_dimensions.state: tr("survey.wall.dimensions", locale),
        Survey.wall_thickness.state: "Введите толщину материала стены в сантиметрах:",
        Survey.wall_editor_name.state: "Название стены или группы (до 60 символов):",
        Survey.wall_editor_area.state: "Площадь стены либо ширина×высота:",
        Survey.wall_editor_custom_lambda.state: "Паспортная λ материала, Вт/(м·К):",
        Survey.wall_editor_thickness.state: "Толщина основного материала, см:",
        Survey.wall_editor_insulation_custom_lambda.state: ("Паспортная λ утеплителя, Вт/(м·К):"),
        Survey.wall_editor_insulation_thickness.state: "Толщина утеплителя, см:",
        Survey.wall_editor_more_layers.state: (
            "Добавьте следующий слой конструкции или завершите стену кнопкой выше."
        ),
        Survey.insulation_thickness.state: "Введите толщину утеплителя в сантиметрах:",
        Survey.window_count.state: "Сколько наружных окон? Если окон нет — 0:",
        Survey.door_count.state: "Сколько наружных дверей? Если дверей нет — 0:",
        Survey.mechanical_ventilation.state: "Введите расход механической вентиляции:",
        Survey.natural_ventilation.state: "Введите расход естественной вентиляции:",
        Survey.infiltration.state: "Введите расчётную инфильтрацию:",
        Survey.heat_recovery_efficiency.state: "Паспортный КПД рекуператора, %:",
        Survey.thermal_bridge_details.state: (
            "Введите мостики холода строками: название | длина | ψ"
        ),
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


async def _ask_climate(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.climate)
    locale = await _state_locale(state)
    items = [(tr(f"climate.{key}", locale), f"climate:{key}") for key in CLIMATES]
    items.extend(
        [
            (tr("survey.climate.custom", locale), "climate:custom"),
            (tr("survey.climate.manual", locale), "climate:manual"),
        ]
    )
    await message.answer(
        tr("survey.climate.question", locale),
        reply_markup=keyboard(items, 1, locale=locale),
    )


async def _ask_object_name(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.object_name)
    await message.answer(tr("survey.object_name", await _state_locale(state)))


@router.message(Survey.object_name)
async def object_name(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not 1 <= len(value) <= 120:
        await _error(message, ValueError("название должно содержать от 1 до 120 символов"), state)
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


@router.callback_query(Survey.climate, F.data.startswith("climate:"))
async def climate(callback: CallbackQuery, state: FSMContext) -> None:
    climate_key = callback.data.split(":", 1)[1]
    if climate_key not in {*CLIMATES, "manual", "custom"}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(climate_key=climate_key)
    if climate_key == "manual":
        await state.set_state(Survey.custom_outdoor)
        await callback.message.answer(tr("survey.outdoor_manual", await _state_locale(state)))
    elif climate_key == "custom":
        await state.set_state(Survey.custom_city_name)
        await callback.message.answer(tr("survey.city_name", await _state_locale(state)))
    else:
        profile = CLIMATES[climate_key]
        await _ask_scenario(callback.message, state, profile)
    await callback.answer()


async def _ask_scenario(message: Message, state: FSMContext, profile: "ClimateProfile") -> None:
    if profile.design_c is None:
        locale = await _state_locale(state)
        await state.set_state(Survey.profile_design)
        data = await state.get_data()
        climate_key = str(data.get("climate_key") or "")
        city = tr(f"climate.{climate_key}", locale) if climate_key in CLIMATES else profile.name
        await message.answer(tr("survey.profile_design", locale, city=city))
        return
    await state.set_state(Survey.scenario)
    locale = await _state_locale(state)
    data = await state.get_data()
    await message.answer(
        tr(
            "survey.scenario.question",
            locale,
            city=(
                tr(f"climate.{data['climate_key']}", locale)
                if data.get("climate_key") in CLIMATES
                else profile.name
            ),
            cold=f"{profile.cold_month_mean_c:g}",
            design=f"{profile.design_c:g}",
            extreme=f"{profile.observed_extreme_c:g}",
            hot=f"{profile.hot_month_mean_c:g}",
            maximum=f"{profile.observed_maximum_c:g}",
        ),
        reply_markup=keyboard(
            [
                (tr("survey.scenario.economy", locale), "scenario:economy"),
                (tr("survey.scenario.design", locale), "scenario:design"),
                (tr("survey.scenario.extreme", locale), "scenario:extreme"),
                (tr("survey.scenario.future", locale), "scenario:future"),
            ],
            1,
            locale=locale,
        ),
    )


@router.message(Survey.profile_design)
async def profile_design(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
        data = await state.get_data()
        profile = CLIMATES[data["climate_key"]]
        if value >= profile.cold_month_mean_c:
            raise ValueError("расчётный параметр Б должен быть холоднее среднемесячной температуры")
        if value < profile.observed_extreme_c:
            raise ValueError("расчётная температура не может быть ниже абсолютного минимума")
    except (KeyError, ValueError) as exc:
        await _error(message, ValueError(str(exc)), state)
        return
    await state.update_data(confirmed_design_c=value)
    confirmed = climate_from_answers(await state.get_data())
    if confirmed is None:
        await _error(message, ValueError("не удалось подтвердить климатический профиль"), state)
        return
    await _ask_scenario(message, state, confirmed)


@router.callback_query(Survey.scenario, F.data.startswith("scenario:"))
async def scenario(callback: CallbackQuery, state: FSMContext) -> None:
    scenario_key = callback.data.split(":", 1)[1]
    data = await state.get_data()
    profile = climate_from_answers(data)
    if profile is None:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    try:
        outdoor = profile.outdoor_temperature(scenario_key)
    except ValueError:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(scenario=scenario_key, outdoor=outdoor)
    await _ask_indoor(callback.message, state, outdoor)
    await callback.answer()


@router.message(Survey.custom_outdoor)
async def custom_outdoor(message: Message, state: FSMContext) -> None:
    try:
        outdoor = _temperature(message.text)
        if outdoor > 15:
            raise ValueError("для отопления ожидается температура не выше +15 °C")
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(outdoor=outdoor, scenario="manual")
    await _ask_indoor(message, state, outdoor)


@router.message(Survey.custom_city_name)
async def custom_city_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not 2 <= len(name) <= 80:
        await _error(message, ValueError("название должно содержать от 2 до 80 символов"), state)
        return
    await state.update_data(custom_city_name=name)
    await state.set_state(Survey.custom_cold_mean)
    await message.answer(tr("survey.custom.cold_mean", await _state_locale(state)))


@router.message(Survey.custom_cold_mean)
async def custom_cold_mean(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(custom_cold_mean=value)
    await state.set_state(Survey.custom_design)
    await message.answer(tr("survey.custom.design", await _state_locale(state)))


@router.message(Survey.custom_design)
async def custom_design(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
        data = await state.get_data()
        if value >= data["custom_cold_mean"]:
            raise ValueError("расчётный мороз должен быть холоднее среднемесячной температуры")
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(custom_design=value)
    await state.set_state(Survey.custom_extreme)
    await message.answer(tr("survey.custom.extreme", await _state_locale(state)))


@router.message(Survey.custom_extreme)
async def custom_extreme(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
        data = await state.get_data()
        if value > data["custom_design"]:
            raise ValueError("рекордный минимум не может быть теплее расчётного мороза")
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(custom_extreme=value)
    await state.set_state(Survey.custom_hot_mean)
    await message.answer(tr("survey.custom.hot_mean", await _state_locale(state)))


@router.message(Survey.custom_hot_mean)
async def custom_hot_mean(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(custom_hot_mean=value)
    await state.set_state(Survey.custom_hot_max)
    await message.answer(tr("survey.custom.hot_max", await _state_locale(state)))


@router.message(Survey.custom_hot_max)
async def custom_hot_max(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
        data = await state.get_data()
        if value < data["custom_hot_mean"]:
            raise ValueError("абсолютный максимум не может быть ниже среднего жаркого месяца")
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(custom_hot_max=value)
    data = await state.get_data()
    profile = climate_from_answers(data)
    if profile is None:  # Defensive guard for corrupted FSM data.
        await _error(message, ValueError("не удалось собрать климатический профиль"), state)
        return
    await _ask_scenario(message, state, profile)


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
        await callback.message.answer(
            "Каждая конструкция — с новой строки:\n"
            "Название | площадь или ширина×высота | материал | толщина см | "
            "утеплитель | толщина см\n\n"
            "Пример:\n"
            "Север | 10x3 | кирпич | 25 | минвата | 5\n"
            "Торец | 18 | газоблок | 30 | нет | 0\n\n"
            "Материалы: кирпич, пустотелый кирпич, газоблок, бетон, дерево. "
            "Утеплители: минвата, пенопласт, XPS, ППУ. Для паспортного материала "
            "введите вместо названия λ=0,12. Площади указываются до вычета окон."
        )
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
    if key not in MATERIALS:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
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
    await state.set_state(Survey.insulated)
    locale = await _state_locale(state)
    await message.answer(
        tr("survey.wall.insulated", locale),
        reply_markup=keyboard(
            [(tr("common.yes", locale), "ins:yes"), (tr("common.no", locale), "ins:no")],
            locale=locale,
        ),
    )


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
        await state.set_state(Survey.insulation_material)
        locale = await _state_locale(state)
        keys = ["mineral_wool", "eps", "xps", "pu_foam"]
        items = [(_material_name(key, locale), f"imat:{key}") for key in keys]
        items.append((tr("survey.wall.insulation_custom", locale), "imat:custom"))
        await callback.message.answer(
            tr("survey.wall.insulation", locale),
            reply_markup=keyboard(items, 1, locale=locale),
        )
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
    if key not in {"mineral_wool", "eps", "xps", "pu_foam"}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
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


@router.callback_query(Survey.window_method, F.data.startswith("window_method:"))
async def window_method(callback: CallbackQuery, state: FSMContext) -> None:
    method = callback.data.split(":", 1)[1]
    locale = await _state_locale(state)
    if method not in {"area", "dimensions", "editor", "groups"}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
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
        await callback.message.answer(
            "Каждая группа окон — с новой строки:\n"
            "Название | количество | ширина×высота, м | паспортный U | "
            "название стены (необязательно)\n\n"
            "Пример:\n"
            "ПВХ север | 3 | 1,4x1,5 | 1,1 | Север\n"
            "Окно кухни | 1 | 1,2x1,4 | 1,6 | Торец\n\n"
            "Название стены должно совпадать с расширенным списком стен. "
            "Если его не указать, площадь распределится пропорционально."
        )
    await callback.answer()


async def _accept_window_area(message: Message, state: FSMContext, area: float) -> None:
    data = await state.get_data()
    if area <= 0:
        raise ValueError("площадь окон должна быть больше нуля")
    if area > data["wall_gross_area"]:
        raise ValueError("площадь окон больше площади стен")
    await state.update_data(window_area=area)
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
        await callback.message.answer(
            "Каждая группа дверей — с новой строки:\n"
            "Название | количество | ширина×высота, м | паспортный U | стена (необязательно)\n\n"
            "Пример:\nВходная | 1 | 0,9x2,1 | 1,4 | Север"
        )
    else:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await callback.answer()


async def _ask_door_type(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.door_type)
    locale = await _state_locale(state)
    items = [(tr(f"door.{key}", locale), f"door_type:{key}") for key in DOORS]
    await message.answer(
        tr("survey.door.type", locale),
        reply_markup=keyboard(items, 1, locale=locale),
    )


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
    await state.update_data(floor_boundary=value)
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
    await state.update_data(ceiling_boundary=value)
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
    await state.set_state(Survey.ground_floor_construction)
    locale = await _state_locale(state)
    await callback.message.answer(
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
    if key not in MATERIALS:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(**{f"{surface}_material": key})
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
    await state.update_data(**{f"{surface}_material": "custom", f"{surface}_conductivity": value})
    await state.set_state(Survey.surface_thickness)
    await message.answer(tr("survey.wall.custom_thickness", await _state_locale(state)))


@router.message(Survey.surface_thickness)
async def surface_thickness(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    data = await state.get_data()
    surface = data["active_surface"]
    await state.update_data(**{f"{surface}_thickness": value / 100})
    await state.set_state(Survey.surface_insulated)
    locale = await _state_locale(state)
    await message.answer(
        tr("survey.surface.insulated", locale),
        reply_markup=keyboard(
            [(tr("common.yes", locale), "sins:yes"), (tr("common.no", locale), "sins:no")],
            locale=locale,
        ),
    )


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
        await state.set_state(Survey.surface_insulation_material)
        locale = await _state_locale(state)
        keys = ["mineral_wool", "eps", "xps", "pu_foam"]
        items = [(_material_name(key, locale), f"simat:{key}") for key in keys]
        items.append((tr("survey.wall.insulation_custom", locale), "simat:custom"))
        await callback.message.answer(
            tr("survey.surface.insulation", locale),
            reply_markup=keyboard(items, 1, locale=locale),
        )
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
    if key not in {"mineral_wool", "eps", "xps", "pu_foam"}:
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


async def _ask_air_changes(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.air_changes)
    data = await state.get_data()
    locale = str(data.get("locale") or "ru")
    if data.get("calculation_mode") == "advanced":
        await message.answer(
            tr("survey.air.advanced", locale),
            reply_markup=keyboard(
                [
                    (tr("survey.air.unit.m3h", locale), "airflow_unit:m3h"),
                    (tr("survey.air.unit.ach", locale), "airflow_unit:ach"),
                ],
                1,
                locale=locale,
            ),
        )
        return
    options = [("0,3", "ach:0.3"), ("0,5", "ach:0.5"), ("0,8", "ach:0.8"), ("1,0", "ach:1.0")]
    try:
        profile_ach = float(data.get("profile_defaults", {}).get("air_changes"))
    except (TypeError, ValueError):
        profile_ach = math.nan
    if profile_ach in {0.3, 0.5, 0.8, 1.0}:
        options = [
            (
                tr("survey.air.from_profile", locale, value=f"{profile_ach:g}"),
                f"ach:{profile_ach:g}",
            ),
            *[item for item in options if item[1] != f"ach:{profile_ach:g}"],
        ]
    await message.answer(
        tr("survey.air.quick", locale),
        reply_markup=keyboard(options, locale=locale),
    )


@router.callback_query(Survey.air_changes, F.data.startswith("ach:"))
async def air_changes(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        ach = float(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer(
            tr("survey.air.error.invalid", await _state_locale(state)), show_alert=True
        )
        return
    if ach not in {0.3, 0.5, 0.8, 1.0}:
        await callback.answer(
            tr("survey.air.error.option", await _state_locale(state)), show_alert=True
        )
        return
    data = await state.get_data()
    if data.get("calculation_mode") == "advanced":
        await callback.answer(
            tr("survey.air.error.units_required", await _state_locale(state)),
            show_alert=True,
        )
        return
    combined_flow = ach * data["volume"]
    await state.update_data(
        air_changes=ach,
        mechanical_ventilation_m3_h=0.0,
        natural_ventilation_m3_h=combined_flow,
        infiltration_m3_h=0.0,
        airflow_input_basis="quick_estimate",
    )
    await state.set_state(Survey.heat_recovery)
    locale = await _state_locale(state)
    await callback.message.answer(
        tr("survey.recovery.quick", locale),
        reply_markup=keyboard(
            [
                (tr("common.no", locale), "recovery:no"),
                (tr("common.yes", locale), "recovery:yes"),
            ],
            2,
            locale=locale,
        ),
    )
    await callback.answer()


@router.callback_query(Survey.air_changes, F.data.startswith("airflow_unit:"))
async def airflow_unit(callback: CallbackQuery, state: FSMContext) -> None:
    unit = callback.data.split(":", 1)[1]
    if unit not in {"m3h", "ach"}:
        await callback.answer(
            tr("survey.air.error.units", await _state_locale(state)), show_alert=True
        )
        return
    data = await state.get_data()
    if data.get("calculation_mode") != "advanced":
        await callback.answer(
            tr("survey.air.error.advanced_only", await _state_locale(state)),
            show_alert=True,
        )
        return
    await state.update_data(airflow_input_basis=f"components_{unit}")
    await state.set_state(Survey.mechanical_ventilation)
    locale = await _state_locale(state)
    suffix = tr(f"survey.air.units.{unit}", locale)
    await callback.message.answer(
        tr("survey.air.mechanical", locale, unit=suffix)
    )
    await callback.answer()


def _airflow_value_to_m3_h(value: float, data: dict) -> float:
    if data.get("airflow_input_basis") == "components_ach":
        return value * data["volume"]
    return value


async def _parse_airflow_component(
    message: Message, state: FSMContext
) -> tuple[float, dict] | None:
    data = await state.get_data()
    maximum = 10.0 if data.get("airflow_input_basis") == "components_ach" else 100_000.0
    try:
        value = parse_number(
            message.text,
            minimum=0,
            maximum=maximum,
            label="Расход воздуха",
        )
    except ValueError as exc:
        await _error(message, exc, state)
        return None
    return _airflow_value_to_m3_h(value, data), data


@router.message(Survey.mechanical_ventilation)
async def mechanical_ventilation(message: Message, state: FSMContext) -> None:
    parsed = await _parse_airflow_component(message, state)
    if parsed is None:
        return
    value, data = parsed
    await state.update_data(mechanical_ventilation_m3_h=value)
    await state.set_state(Survey.natural_ventilation)
    unit = "m3h" if data["airflow_input_basis"] == "components_m3h" else "ach"
    suffix = tr(f"survey.air.units.{unit}", await _state_locale(state))
    await message.answer(
        tr("survey.air.natural", await _state_locale(state), unit=suffix)
    )


@router.message(Survey.natural_ventilation)
async def natural_ventilation(message: Message, state: FSMContext) -> None:
    parsed = await _parse_airflow_component(message, state)
    if parsed is None:
        return
    value, data = parsed
    await state.update_data(natural_ventilation_m3_h=value)
    await state.set_state(Survey.infiltration)
    unit = "m3h" if data["airflow_input_basis"] == "components_m3h" else "ach"
    suffix = tr(f"survey.air.units.{unit}", await _state_locale(state))
    await message.answer(
        tr("survey.air.infiltration", await _state_locale(state), unit=suffix)
    )


@router.message(Survey.infiltration)
async def infiltration(message: Message, state: FSMContext) -> None:
    parsed = await _parse_airflow_component(message, state)
    if parsed is None:
        return
    value, _ = parsed
    await state.update_data(infiltration_m3_h=value, air_changes=0.0)
    data = await state.get_data()
    if data["mechanical_ventilation_m3_h"] > 0:
        await state.set_state(Survey.heat_recovery)
        locale = await _state_locale(state)
        await message.answer(
            tr("survey.air.recovery", locale),
            reply_markup=keyboard(
                [
                    (tr("common.no", locale), "recovery:no"),
                    (tr("common.yes", locale), "recovery:yes"),
                ],
                2,
                locale=locale,
            ),
        )
    else:
        await state.update_data(heat_recovery_efficiency=0.0)
        await _ask_thermal_bridges(message, state)


@router.callback_query(Survey.heat_recovery, F.data.startswith("recovery:"))
async def heat_recovery(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    data = await state.get_data()
    if data.get("airflow_input_basis") == "quick_estimate":
        await state.update_data(heat_recovery_efficiency=0.0)
        if value == "yes":
            await callback.message.answer(
                tr("survey.recovery.quick_note", await _state_locale(state))
            )
        elif value != "no":
            await callback.answer(
                tr("survey.air.error.recovery", await _state_locale(state)),
                show_alert=True,
            )
            return
        await _ask_thermal_bridges(callback.message, state)
        await callback.answer()
        return
    if value == "no":
        await state.update_data(heat_recovery_efficiency=0.0)
        await _ask_thermal_bridges(callback.message, state)
    elif value == "yes":
        await state.set_state(Survey.heat_recovery_efficiency)
        await callback.message.answer(
            tr("survey.air.recovery_efficiency", await _state_locale(state))
        )
    else:
        await callback.answer(
            tr("survey.air.error.recovery", await _state_locale(state)), show_alert=True
        )
        return
    await callback.answer()


@router.message(Survey.heat_recovery_efficiency)
async def heat_recovery_efficiency(message: Message, state: FSMContext) -> None:
    try:
        efficiency = (
            parse_number(
                message.text,
                minimum=1,
                maximum=95,
                label="КПД рекуператора, %",
            )
            / 100
        )
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(heat_recovery_efficiency=efficiency)
    await _ask_thermal_bridges(message, state)


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
        await callback.message.answer(
            "Каждый мостик — с новой строки:\n"
            "Название | длина, м | ψ, Вт/(м·К)\n\n"
            "Пример:\nБалконная плита | 4,5 | 0,35\nПеремычки | 8 | 0,12"
        )
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


async def _ask_safety_factor(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.safety_factor)
    locale = await _state_locale(state)
    options = [
        ("0%", "safety:1.0"),
        (tr("survey.safety.normal", locale), "safety:1.10"),
        ("15%", "safety:1.15"),
        ("20%", "safety:1.20"),
    ]
    data = await state.get_data()
    try:
        profile_factor = float(data.get("profile_defaults", {}).get("safety_factor"))
    except (TypeError, ValueError):
        profile_factor = math.nan
    if profile_factor in {1.0, 1.10, 1.15, 1.20}:
        callback_data = f"safety:{profile_factor}"
        options = [
            (
                tr(
                    "survey.safety.from_profile",
                    locale,
                    value=f"{(profile_factor - 1) * 100:.0f}",
                ),
                callback_data,
            ),
            *[item for item in options if float(item[1].split(":", 1)[1]) != profile_factor],
        ]
    await message.answer(
        tr("survey.safety.question", locale),
        reply_markup=keyboard(options, 2, locale=locale),
    )


def _confirmation_text(data: dict) -> str:
    locale = str(data.get("locale") or "ru")
    building = tr(f"survey.object.{data.get('building_type', 'house')}", locale)
    climate_key = str(data.get("climate_key", "manual"))
    if climate_key in CLIMATES:
        climate_name = tr(f"climate.{climate_key}", locale)
    elif climate_key == "custom" and data.get("custom_city_name"):
        climate_name = str(data["custom_city_name"])
    else:
        climate_name = tr("survey.climate.manual_name", locale)
    wall_area = float(data.get("wall_gross_area", 0))
    openings_area = float(data.get("window_area", 0)) + float(data.get("door_area", 0))
    airflow = (
        float(data.get("mechanical_ventilation_m3_h", 0))
        + float(data.get("natural_ventilation_m3_h", 0))
        + float(data.get("infiltration_m3_h", 0))
    )
    if not airflow:
        airflow_text = tr(
            "survey.confirm.airflow_simple",
            locale,
            value=f"{float(data.get('air_changes', 0)):g}",
        )
    else:
        airflow_text = tr("survey.confirm.airflow_total", locale, value=f"{airflow:g}")
    return tr(
        "survey.confirm.body",
        locale,
        title=tr("survey.confirm.title", locale),
        building=building,
        climate=climate_name,
        outdoor=f"{float(data.get('outdoor', 0)):g}",
        indoor=f"{float(data.get('indoor', 0)):g}",
        length=f"{float(data.get('length', 0)):g}",
        width=f"{float(data.get('width', 0)):g}",
        height=f"{float(data.get('height', 0)):g}",
        walls=f"{wall_area:g}",
        openings=f"{openings_area:g}",
        airflow=airflow_text,
        safety=f"{(float(data.get('safety_factor', 1)) - 1) * 100:.0f}",
    )


async def _ask_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("calculation_request_id"):
        await state.update_data(calculation_request_id=secrets.token_urlsafe(18))
        data = await state.get_data()
    await state.set_state(Survey.confirmation)
    locale = str(data.get("locale") or "ru")
    await message.answer(
        _confirmation_text(data),
        reply_markup=keyboard(
            [
                (tr("survey.confirm.calculate", locale), "confirm:calculate"),
                (tr("survey.confirm.climate", locale), "confirm:climate"),
                (tr("survey.confirm.walls", locale), "confirm:walls"),
                (tr("survey.confirm.openings", locale), "confirm:openings"),
                (tr("survey.confirm.boundaries", locale), "confirm:boundaries"),
                (tr("survey.confirm.airflow", locale), "confirm:airflow"),
                (tr("common.cancel", locale), "nav:cancel"),
            ],
            1,
            navigation=False,
            locale=locale,
        ),
    )


@router.callback_query(Survey.safety_factor, F.data.startswith("safety:"))
async def safety_factor(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    try:
        factor = float(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    if factor not in {1.0, 1.10, 1.15, 1.20}:
        await callback.answer(
            tr("common.invalid_option", await _state_locale(state)), show_alert=True
        )
        return
    await state.update_data(safety_factor=factor)
    await _ask_confirmation(callback.message, state)
    await callback.answer()


@router.callback_query(Survey.confirmation, F.data.startswith("confirm:"))
async def confirmation(
    callback: CallbackQuery,
    state: FSMContext,
    repository: CalculationRepository,
) -> None:
    action = callback.data.split(":", 1)[1]
    if action == "climate":
        await _ask_climate(callback.message, state)
        await callback.answer()
        return
    if action == "walls":
        await _ask_wall_method(callback.message, state)
        await callback.answer()
        return
    if action == "openings":
        await _ask_windows(callback.message, state)
        await callback.answer()
        return
    if action == "boundaries":
        await _ask_floor_boundary(callback.message, state)
        await callback.answer()
        return
    if action == "airflow":
        await _ask_air_changes(callback.message, state)
        await callback.answer()
        return
    if action != "calculate":
        await callback.answer(
            tr("survey.confirm.error.action", await _state_locale(state)), show_alert=True
        )
        return

    state_data = await state.get_data()
    data = {key: value for key, value in state_data.items() if not key.startswith("_")}
    locale = str(data.get("locale") or "ru")
    try:
        bundle = calculate_from_answers(data)
    except InvalidCalculationData as exc:
        await callback.message.answer(tr("result.invalid", locale, message=str(exc)))
        await callback.answer()
        return

    except Exception:
        logger.exception(
            "Unexpected calculation failure user_id=%s",
            callback.from_user.id,
        )
        await callback.message.answer(tr("result.internal", locale))
        await callback.answer()
        return

    data["calculation_snapshot"] = {
        "building": asdict(bundle.building),
        "result": asdict(bundle.result),
        "climate": asdict(bundle.climate) if bundle.climate else None,
        "scenario_results": {
            key: asdict(value) for key, value in (bundle.scenario_results or {}).items()
        },
        "report": bundle.report,
    }

    calculation_id: int | None = None
    try:
        calculation_id = await asyncio.to_thread(
            repository.save,
            callback.from_user.id,
            data,
            bundle.result.total_kw,
            bundle.result.recommended_kw,
            bundle.report,
            parent_id=data.get("parent_calculation_id"),
            request_id=data.get("calculation_request_id"),
        )
    except Exception:
        logger.exception("Database save failed user_id=%s", callback.from_user.id)
        await _send_long_message(
            callback.message,
            tr("result.unsaved", locale)
            + "\n\n"
            + format_telegram_summary(
                str(data.get("object_name") or tr("summary.untitled", locale)),
                bundle.building,
                bundle.result,
                bundle.climate,
                str(data.get("scenario") or "manual"),
                str(data.get("locale") or "ru"),
            ),
        )
    else:
        await _send_long_message(
            callback.message,
            tr("result.saved", locale, id=calculation_id)
            + "\n\n"
            + format_telegram_summary(
                str(data.get("object_name") or tr("summary.untitled", locale)),
                bundle.building,
                bundle.result,
                bundle.climate,
                str(data.get("scenario") or "manual"),
                str(data.get("locale") or "ru"),
            ),
        )
    try:
        from ..pdf_report import build_pdf_report

        data["calculation_id"] = calculation_id or "unsaved"
        pdf_bytes = await asyncio.to_thread(
            build_pdf_report,
            bundle,
            data,
            callback.from_user.id,
        )
        safe_id = str(calculation_id) if calculation_id is not None else "unsaved"
        await callback.message.answer_document(
            BufferedInputFile(pdf_bytes, filename=f"u-calc-{safe_id}.pdf"),
            caption=tr("result.pdf_caption", locale),
        )
    except Exception:
        logger.exception("PDF generation failed user_id=%s", callback.from_user.id)
        await callback.message.answer(tr("result.pdf_failed", locale))
    await callback.message.answer(tr("result.new", locale))
    await state.clear()
    await callback.answer()


@router.callback_query()
async def stale_callback(callback: CallbackQuery, repository: CalculationRepository) -> None:
    settings = await asyncio.to_thread(repository.get_user_settings, callback.from_user.id)
    await callback.answer(tr("common.stale", settings.locale), show_alert=True)


@router.errors()
async def global_error_handler(
    event: ErrorEvent, repository: CalculationRepository
) -> bool:
    update = event.update
    message = update.message
    callback = update.callback_query
    user = (message or callback).from_user if (message or callback) else None
    exception = event.exception
    logger.error(
        "Unhandled Telegram update error user_id=%s update_id=%s",
        getattr(user, "id", None),
        update.update_id,
        exc_info=(type(exception), exception, exception.__traceback__),
    )
    locale = "ru"
    if user is not None:
        try:
            settings = await asyncio.to_thread(repository.get_user_settings, user.id)
            locale = settings.locale
        except Exception:
            logger.exception("Failed to resolve locale for error notification")
    text = tr("common.unhandled", locale)
    try:
        if callback:
            await callback.answer(tr("common.internal", locale), show_alert=True)
            if callback.message:
                await callback.message.answer(text)
        elif message:
            await message.answer(text)
    except Exception:
        logger.exception("Failed to notify user about handler error")
    return True
