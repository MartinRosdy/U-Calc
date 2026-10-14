"""Telegram flow for ventilation, infiltration and heat recovery inputs."""

import math

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..calculator import appendix8_pressure_difference_pa
from ..i18n import translate as tr
from ..keyboards import keyboard
from ..models import Appendix8PressureInput
from ..parsing import (
    parse_appendix8_infiltration_paths,
    parse_appendix8_pressure_globals,
    parse_appendix8_pressure_groups,
    parse_number,
)
from ..states import Survey

router = Router(name=__name__)


async def _locale(state: FSMContext) -> str:
    return str((await state.get_data()).get("locale") or "ru")


async def _error(message: Message, exc: ValueError, state: FSMContext) -> None:
    locale = await _locale(state)
    detail = str(exc) if locale == "ru" else tr("common.invalid_input", locale)
    await message.answer(tr("common.retry", locale, message=detail))


def _unit_label(data: dict, locale: str) -> str:
    unit = "ach" if data.get("airflow_input_basis") == "components_ach" else "m3h"
    return tr(f"survey.air.units.{unit}", locale)


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


async def _ask_heat_recovery(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.heat_recovery)
    data = await state.get_data()
    locale = await _locale(state)
    prompt = (
        tr("survey.recovery.quick", locale)
        if data.get("airflow_input_basis") == "quick_estimate"
        else tr("survey.air.recovery", locale)
    )
    await message.answer(
        prompt,
        reply_markup=keyboard(
            [
                (tr("common.no", locale), "recovery:no"),
                (tr("common.yes", locale), "recovery:yes"),
            ],
            2,
            locale=locale,
        ),
    )


async def _ask_infiltration(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.infiltration)
    data = await state.get_data()
    locale = await _locale(state)
    await message.answer(
        tr("survey.air.infiltration", locale, unit=_unit_label(data, locale)),
        reply_markup=keyboard(
            [
                (
                    tr("survey.air.infiltration.residential", locale),
                    "infiltration_method:residential",
                ),
                (
                    tr("survey.air.infiltration.envelope", locale),
                    "infiltration_method:envelope",
                ),
                (tr("survey.air.infiltration.none", locale), "infiltration_method:none"),
            ],
            1,
            locale=locale,
        ),
    )


async def _advance_after_infiltration(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if float(data.get("mechanical_ventilation_m3_h") or 0.0) > 0:
        await _ask_heat_recovery(message, state)
    else:
        await state.update_data(heat_recovery_efficiency=0.0)
        await _ask_thermal_bridges(message, state)


@router.callback_query(Survey.air_changes, F.data.startswith("ach:"))
async def air_changes(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        ach = float(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer(tr("survey.air.error.invalid", await _locale(state)), show_alert=True)
        return
    if ach not in {0.3, 0.5, 0.8, 1.0}:
        await callback.answer(tr("survey.air.error.option", await _locale(state)), show_alert=True)
        return
    data = await state.get_data()
    if data.get("calculation_mode") == "advanced":
        await callback.answer(
            tr("survey.air.error.units_required", await _locale(state)),
            show_alert=True,
        )
        return
    combined_flow = ach * data["volume"]
    await state.update_data(
        air_changes=ach,
        mechanical_ventilation_m3_h=0.0,
        natural_ventilation_m3_h=combined_flow,
        infiltration_m3_h=0.0,
        infiltration_basis="quick_estimate",
        infiltration_paths=[],
        airflow_input_basis="quick_estimate",
    )
    await _ask_heat_recovery(callback.message, state)
    await callback.answer()


@router.callback_query(Survey.air_changes, F.data.startswith("airflow_unit:"))
async def airflow_unit(callback: CallbackQuery, state: FSMContext) -> None:
    unit = callback.data.split(":", 1)[1]
    if unit not in {"m3h", "ach"}:
        await callback.answer(tr("survey.air.error.units", await _locale(state)), show_alert=True)
        return
    data = await state.get_data()
    if data.get("calculation_mode") != "advanced":
        await callback.answer(
            tr("survey.air.error.advanced_only", await _locale(state)),
            show_alert=True,
        )
        return
    basis = "components_m3_h" if unit == "m3h" else "components_ach"
    await state.update_data(airflow_input_basis=basis)
    await state.set_state(Survey.mechanical_ventilation)
    locale = await _locale(state)
    await callback.message.answer(
        tr("survey.air.mechanical", locale, unit=tr(f"survey.air.units.{unit}", locale))
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
        value = parse_number(message.text, minimum=0, maximum=maximum, label="Расход воздуха")
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
    unit = (
        "m3h"
        if data["airflow_input_basis"] in {"components_m3h", "components_m3_h"}
        else "ach"
    )
    locale = await _locale(state)
    await message.answer(
        tr("survey.air.natural", locale, unit=tr(f"survey.air.units.{unit}", locale))
    )


@router.message(Survey.natural_ventilation)
async def natural_ventilation(message: Message, state: FSMContext) -> None:
    parsed = await _parse_airflow_component(message, state)
    if parsed is None:
        return
    value, _ = parsed
    await state.update_data(natural_ventilation_m3_h=value)
    await _ask_infiltration(message, state)


@router.message(Survey.infiltration)
async def infiltration(message: Message, state: FSMContext) -> None:
    parsed = await _parse_airflow_component(message, state)
    if parsed is None:
        return
    value, _ = parsed
    await state.update_data(
        infiltration_m3_h=value,
        infiltration_basis="manual_flow",
        infiltration_living_area_m2=None,
        infiltration_paths=[],
        air_changes=0.0,
    )
    await _advance_after_infiltration(message, state)


@router.callback_query(Survey.infiltration, F.data.startswith("infiltration_method:"))
async def infiltration_method(callback: CallbackQuery, state: FSMContext) -> None:
    method = callback.data.split(":", 1)[1]
    locale = await _locale(state)
    if method == "residential":
        await state.set_state(Survey.infiltration_living_area)
        await callback.message.answer(tr("survey.air.infiltration.living_area", locale))
    elif method == "envelope":
        await state.set_state(Survey.infiltration_envelope)
        await callback.message.answer(
            tr("survey.air.infiltration.pressure_method", locale),
            reply_markup=keyboard(
                [
                    (
                        tr("survey.air.infiltration.pressure_direct", locale),
                        "pressure_method:direct",
                    ),
                    (
                        tr("survey.air.infiltration.pressure_formula4", locale),
                        "pressure_method:formula4",
                    ),
                ],
                1,
                locale=locale,
            ),
        )
    elif method == "none":
        await state.update_data(
            infiltration_m3_h=0.0,
            infiltration_basis="none",
            infiltration_living_area_m2=None,
            infiltration_paths=[],
            air_changes=0.0,
        )
        await _advance_after_infiltration(callback.message, state)
    else:
        await callback.answer(tr("common.invalid_option", locale), show_alert=True)
        return
    await callback.answer()


@router.callback_query(Survey.infiltration_envelope, F.data.startswith("pressure_method:"))
async def infiltration_pressure_method(callback: CallbackQuery, state: FSMContext) -> None:
    method = callback.data.split(":", 1)[1]
    locale = await _locale(state)
    if method == "direct":
        await callback.message.answer(tr("survey.air.infiltration.envelope_input", locale))
    elif method == "formula4":
        await state.set_state(Survey.infiltration_pressure_globals)
        await callback.message.answer(tr("survey.air.infiltration.pressure_globals", locale))
    else:
        await callback.answer(tr("common.invalid_option", locale), show_alert=True)
        return
    await callback.answer()


@router.message(Survey.infiltration_pressure_globals)
async def infiltration_pressure_globals(message: Message, state: FSMContext) -> None:
    try:
        values = parse_appendix8_pressure_globals(message.text)
        data = await state.get_data()
        values.update(
            indoor_temperature_c=float(data["indoor"]),
            outdoor_temperature_c=float(data["outdoor"]),
        )
        Appendix8PressureInput(opening_height_m=0.0, **values)
    except (KeyError, TypeError, ValueError) as exc:
        if not isinstance(exc, ValueError):
            exc = ValueError("температуры текущего расчёта не найдены")
        await _error(message, exc, state)
        return
    await state.update_data(infiltration_pressure_globals=values)
    await state.set_state(Survey.infiltration_pressure_groups)
    await message.answer(tr("survey.air.infiltration.pressure_groups", await _locale(state)))


@router.message(Survey.infiltration_pressure_groups)
async def infiltration_pressure_groups(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    globals_ = data.get("infiltration_pressure_globals")
    try:
        if not isinstance(globals_, dict):
            raise ValueError("общие параметры формулы 4 не найдены")
        groups = parse_appendix8_pressure_groups(message.text)
        paths: list[dict] = []
        for line_number, group in enumerate(groups, start=1):
            current = Appendix8PressureInput(
                opening_height_m=group.pop("opening_height_m"), **globals_
            )
            first = Appendix8PressureInput(
                opening_height_m=group.pop("first_floor_opening_height_m"), **globals_
            )
            pressure = appendix8_pressure_difference_pa(current)
            first_pressure = appendix8_pressure_difference_pa(first)
            if pressure <= 0 or first_pressure <= 0:
                raise ValueError(
                    f"строка {line_number}: формула 4 дала неположительный Δp "
                    f"({pressure:.2f}/{first_pressure:.2f} Па); проверьте pᵢnt и коэффициенты"
                )
            paths.append(
                {
                    **group,
                    "pressure_pa": pressure,
                    "first_floor_pressure_pa": first_pressure,
                    "pressure_input": {
                        **globals_,
                        "opening_height_m": current.opening_height_m,
                    },
                    "first_floor_pressure_input": {
                        **globals_,
                        "opening_height_m": first.opening_height_m,
                    },
                }
            )
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(
        infiltration_paths=paths,
        infiltration_m3_h=0.0,
        infiltration_basis="appendix8_envelope",
        infiltration_living_area_m2=None,
        air_changes=0.0,
    )
    await state.set_state(Survey.infiltration_envelope_living_area)
    await message.answer(tr("survey.air.infiltration.envelope_living_area", await _locale(state)))


@router.message(Survey.infiltration_envelope)
async def infiltration_envelope(message: Message, state: FSMContext) -> None:
    try:
        paths = parse_appendix8_infiltration_paths(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(
        infiltration_paths=paths,
        infiltration_m3_h=0.0,
        infiltration_basis="appendix8_envelope",
        infiltration_living_area_m2=None,
        air_changes=0.0,
    )
    await state.set_state(Survey.infiltration_envelope_living_area)
    await message.answer(
        tr("survey.air.infiltration.envelope_living_area", await _locale(state))
    )


@router.message(Survey.infiltration_envelope_living_area)
async def infiltration_envelope_living_area(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        maximum = float(data.get("length", 1_000)) * float(data.get("width", 1_000))
        if not math.isfinite(maximum) or maximum < 1:
            raise ValueError("не удалось определить площадь объекта")
        area = parse_number(
            message.text,
            minimum=0,
            maximum=maximum,
            label="Площадь жилых комнат",
        )
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(
        infiltration_m3_h=3.0 * area,
        infiltration_living_area_m2=area,
    )
    await _advance_after_infiltration(message, state)


@router.message(Survey.infiltration_living_area)
async def infiltration_living_area(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        maximum = float(data.get("length", 1_000)) * float(data.get("width", 1_000))
        if not math.isfinite(maximum) or maximum < 1:
            raise ValueError("не удалось определить площадь объекта")
        area = parse_number(
            message.text,
            minimum=1,
            maximum=maximum,
            label="Площадь жилых комнат",
        )
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(
        infiltration_m3_h=3.0 * area,
        infiltration_basis="appendix8_residential_exhaust",
        infiltration_living_area_m2=area,
        infiltration_paths=[],
        air_changes=0.0,
    )
    await _advance_after_infiltration(message, state)


@router.callback_query(Survey.heat_recovery, F.data.startswith("recovery:"))
async def heat_recovery(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    data = await state.get_data()
    if data.get("airflow_input_basis") == "quick_estimate":
        await state.update_data(heat_recovery_efficiency=0.0)
        if value == "yes":
            await callback.message.answer(tr("survey.recovery.quick_note", await _locale(state)))
        elif value != "no":
            await callback.answer(
                tr("survey.air.error.recovery", await _locale(state)),
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
        await callback.message.answer(tr("survey.air.recovery_efficiency", await _locale(state)))
    else:
        await callback.answer(
            tr("survey.air.error.recovery", await _locale(state)), show_alert=True
        )
        return
    await callback.answer()


@router.message(Survey.heat_recovery_efficiency)
async def heat_recovery_efficiency(message: Message, state: FSMContext) -> None:
    try:
        efficiency = (
            parse_number(message.text, minimum=1, maximum=95, label="КПД рекуператора, %")
            / 100
        )
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(heat_recovery_efficiency=efficiency)
    await _ask_thermal_bridges(message, state)


async def _ask_thermal_bridges(message: Message, state: FSMContext) -> None:
    # Lazy import keeps the airflow feature independent from survey import order.
    from .survey import _ask_thermal_bridges as ask_thermal_bridges

    await ask_thermal_bridges(message, state)


async def render_airflow_step(message: Message, state: FSMContext) -> bool:
    """Re-render airflow screens after draft restore or back navigation."""
    getter = getattr(state, "get_state", None)
    if getter is not None:
        current = await getter()
    else:
        value = getattr(state, "state", None)
        current = getattr(value, "state", value)
    data = await state.get_data()
    locale = str(data.get("locale") or "ru")
    if current == Survey.air_changes.state:
        await _ask_air_changes(message, state)
        return True
    if current == Survey.heat_recovery.state:
        await _ask_heat_recovery(message, state)
        return True
    if current == Survey.infiltration.state:
        await _ask_infiltration(message, state)
        return True
    if current == Survey.infiltration_living_area.state:
        await message.answer(tr("survey.air.infiltration.living_area", locale))
        return True
    if current == Survey.infiltration_envelope.state:
        await message.answer(tr("survey.air.infiltration.pressure_method", locale))
        return True
    if current == Survey.infiltration_pressure_globals.state:
        await message.answer(tr("survey.air.infiltration.pressure_globals", locale))
        return True
    if current == Survey.infiltration_pressure_groups.state:
        await message.answer(tr("survey.air.infiltration.pressure_groups", locale))
        return True
    if current == Survey.infiltration_envelope_living_area.state:
        await message.answer(tr("survey.air.infiltration.envelope_living_area", locale))
        return True
    prompts = {
        Survey.mechanical_ventilation.state: "survey.air.mechanical",
        Survey.natural_ventilation.state: "survey.air.natural",
    }
    if current in prompts:
        await message.answer(tr(prompts[current], locale, unit=_unit_label(data, locale)))
        return True
    if current == Survey.heat_recovery_efficiency.state:
        await message.answer(tr("survey.air.recovery_efficiency", locale))
        return True
    return False
