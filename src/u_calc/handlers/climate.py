"""Telegram flow for built-in, confirmed and custom climate profiles."""

import math

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..catalog import CLIMATES, ClimateProfile
from ..i18n import translate as tr
from ..keyboards import keyboard
from ..services.building_factory import InvalidCalculationData, climate_from_answers
from ..states import Survey
from .common import bounded_text

router = Router(name=__name__)


async def _locale(state: FSMContext) -> str:
    return str((await state.get_data()).get("locale") or "ru")


def _temperature(text: str | None) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите температуру числом, например -18") from exc
    if not math.isfinite(value) or not -80 <= value <= 70:
        raise ValueError("Ожидается температура от -80 до +70 °C")
    return value


def _source_reference(text: str | None) -> str:
    value = (text or "").strip()
    if value == "-":
        return "не указан пользователем"
    try:
        return bounded_text(text, minimum=3, maximum=300, label="Источник")
    except ValueError as exc:
        raise ValueError(
            "укажите источник от 3 до 300 символов без управляющих знаков либо отправьте «-»"
        ) from exc


async def _error(message: Message, exc: ValueError, state: FSMContext) -> None:
    locale = await _locale(state)
    detail = str(exc) if locale == "ru" else tr("common.invalid_input", locale)
    await message.answer(tr("common.retry", locale, message=detail))


async def _ask_climate(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.climate)
    locale = await _locale(state)
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


async def _ask_scenario(message: Message, state: FSMContext, profile: ClimateProfile) -> None:
    if profile.design_c is None:
        locale = await _locale(state)
        await state.set_state(Survey.profile_design)
        data = await state.get_data()
        climate_key = str(data.get("climate_key") or "")
        city = tr(f"climate.{climate_key}", locale) if climate_key in CLIMATES else profile.name
        await message.answer(tr("survey.profile_design", locale, city=city))
        return
    await state.set_state(Survey.scenario)
    locale = await _locale(state)
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


@router.callback_query(Survey.climate, F.data.startswith("climate:"))
async def climate(callback: CallbackQuery, state: FSMContext) -> None:
    climate_key = callback.data.split(":", 1)[1]
    if climate_key not in {*CLIMATES, "manual", "custom"}:
        await callback.answer(tr("common.invalid_option", await _locale(state)), show_alert=True)
        return
    await state.update_data(climate_key=climate_key)
    if climate_key == "manual":
        await state.set_state(Survey.custom_outdoor)
        await callback.message.answer(tr("survey.outdoor_manual", await _locale(state)))
    elif climate_key == "custom":
        await state.set_state(Survey.custom_city_name)
        await callback.message.answer(tr("survey.city_name", await _locale(state)))
    else:
        await _ask_scenario(callback.message, state, CLIMATES[climate_key])
    await callback.answer()


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
    await state.set_state(Survey.profile_design_source)
    await message.answer(tr("survey.climate.source", await _locale(state)))


@router.message(Survey.profile_design_source)
async def profile_design_source(message: Message, state: FSMContext) -> None:
    try:
        source = _source_reference(message.text)
        confirmed = climate_from_answers(
            {**await state.get_data(), "confirmed_design_source": source}
        )
        if confirmed is None:
            raise ValueError("не удалось подтвердить климатический профиль")
    except InvalidCalculationData as exc:
        await _error(message, ValueError(str(exc)), state)
        return
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(confirmed_design_source=source)
    await _ask_scenario(message, state, confirmed)


@router.callback_query(Survey.scenario, F.data.startswith("scenario:"))
async def scenario(callback: CallbackQuery, state: FSMContext) -> None:
    scenario_key = callback.data.split(":", 1)[1]
    try:
        profile = climate_from_answers(await state.get_data())
    except InvalidCalculationData:
        await callback.answer(tr("common.invalid_option", await _locale(state)), show_alert=True)
        return
    if profile is None:
        await callback.answer(tr("common.invalid_option", await _locale(state)), show_alert=True)
        return
    try:
        outdoor = profile.outdoor_temperature(scenario_key)
    except ValueError:
        await callback.answer(tr("common.invalid_option", await _locale(state)), show_alert=True)
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
    await state.set_state(Survey.manual_climate_source)
    await message.answer(tr("survey.climate.source", await _locale(state)))


@router.message(Survey.manual_climate_source)
async def manual_climate_source(message: Message, state: FSMContext) -> None:
    try:
        source = _source_reference(message.text)
        data = await state.get_data()
        outdoor = _temperature(str(data["outdoor"]))
        if outdoor > 15:
            raise ValueError("для отопления ожидается температура не выше +15 °C")
    except (KeyError, TypeError, ValueError) as exc:
        await _error(message, ValueError(str(exc)), state)
        return
    await state.update_data(manual_climate_source=source)
    await _ask_indoor(message, state, outdoor)


@router.message(Survey.custom_city_name)
async def custom_city_name(message: Message, state: FSMContext) -> None:
    try:
        name = bounded_text(message.text, minimum=2, maximum=80, label="Название города")
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(custom_city_name=name)
    await state.set_state(Survey.custom_cold_mean)
    await message.answer(tr("survey.custom.cold_mean", await _locale(state)))


@router.message(Survey.custom_cold_mean)
async def custom_cold_mean(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(custom_cold_mean=value)
    await state.set_state(Survey.custom_design)
    await message.answer(tr("survey.custom.design", await _locale(state)))


@router.message(Survey.custom_design)
async def custom_design(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
        data = await state.get_data()
        if value >= data["custom_cold_mean"]:
            raise ValueError("расчётный мороз должен быть холоднее среднемесячной температуры")
    except (KeyError, ValueError) as exc:
        await _error(message, ValueError(str(exc)), state)
        return
    await state.update_data(custom_design=value)
    await state.set_state(Survey.custom_extreme)
    await message.answer(tr("survey.custom.extreme", await _locale(state)))


@router.message(Survey.custom_extreme)
async def custom_extreme(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
        data = await state.get_data()
        if value > data["custom_design"]:
            raise ValueError("рекордный минимум не может быть теплее расчётного мороза")
    except (KeyError, ValueError) as exc:
        await _error(message, ValueError(str(exc)), state)
        return
    await state.update_data(custom_extreme=value)
    await state.set_state(Survey.custom_hot_mean)
    await message.answer(tr("survey.custom.hot_mean", await _locale(state)))


@router.message(Survey.custom_hot_mean)
async def custom_hot_mean(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
        data = await state.get_data()
        if value < data["custom_cold_mean"]:
            raise ValueError(
                "средний жаркий месяц не может быть холоднее среднего холодного месяца"
            )
    except (KeyError, ValueError) as exc:
        await _error(message, ValueError(str(exc)), state)
        return
    await state.update_data(custom_hot_mean=value)
    await state.set_state(Survey.custom_hot_max)
    await message.answer(tr("survey.custom.hot_max", await _locale(state)))


@router.message(Survey.custom_hot_max)
async def custom_hot_max(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
        data = await state.get_data()
        if value < data["custom_hot_mean"]:
            raise ValueError("абсолютный максимум не может быть ниже среднего жаркого месяца")
    except (KeyError, ValueError) as exc:
        await _error(message, ValueError(str(exc)), state)
        return
    await state.update_data(custom_hot_max=value)
    await state.set_state(Survey.custom_source)
    await message.answer(tr("survey.custom.source", await _locale(state)))


@router.message(Survey.custom_source)
async def custom_source(message: Message, state: FSMContext) -> None:
    try:
        source = _source_reference(message.text)
        profile = climate_from_answers({**await state.get_data(), "custom_climate_source": source})
        if profile is None:
            raise ValueError("не удалось собрать климатический профиль")
    except InvalidCalculationData as exc:
        await _error(message, ValueError(str(exc)), state)
        return
    except ValueError as exc:
        await _error(message, exc, state)
        return
    await state.update_data(custom_climate_source=source)
    await _ask_scenario(message, state, profile)


async def _ask_indoor(message: Message, state: FSMContext, outdoor: float) -> None:
    from .survey import _ask_indoor as ask_indoor

    await ask_indoor(message, state, outdoor)


async def render_climate_step(message: Message, state: FSMContext) -> bool:
    """Re-render climate screens after draft restore or back navigation."""
    getter = getattr(state, "get_state", None)
    if getter is not None:
        current = await getter()
    else:
        value = getattr(state, "state", None)
        current = getattr(value, "state", value)
    data = await state.get_data()
    locale = str(data.get("locale") or "ru")
    if current == Survey.climate.state:
        await _ask_climate(message, state)
        return True
    if current == Survey.scenario.state:
        profile = climate_from_answers(data)
        if profile is not None:
            await _ask_scenario(message, state, profile)
            return True
    if current == Survey.profile_design.state:
        profile = CLIMATES.get(str(data.get("climate_key")))
        if profile is not None:
            await message.answer(
                tr("survey.profile_design", locale, city=tr(f"climate.{profile.key}", locale))
            )
            return True
    prompts = {
        Survey.custom_outdoor.state: "survey.outdoor_manual",
        Survey.manual_climate_source.state: "survey.climate.source",
        Survey.profile_design_source.state: "survey.climate.source",
        Survey.custom_city_name.state: "survey.city_name",
        Survey.custom_cold_mean.state: "survey.custom.cold_mean",
        Survey.custom_design.state: "survey.custom.design",
        Survey.custom_extreme.state: "survey.custom.extreme",
        Survey.custom_hot_mean.state: "survey.custom.hot_mean",
        Survey.custom_hot_max.state: "survey.custom.hot_max",
        Survey.custom_source.state: "survey.custom.source",
    }
    if current in prompts:
        await message.answer(tr(prompts[current], locale))
        return True
    return False
