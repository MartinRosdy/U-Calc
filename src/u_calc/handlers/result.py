"""Final review, calculation, persistence and report delivery flow."""

import asyncio
import logging
import math
import secrets
from dataclasses import asdict

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from ..catalog import CLIMATES
from ..i18n import translate as tr
from ..keyboards import keyboard
from ..report import format_telegram_summary
from ..services.building_factory import InvalidCalculationData
from ..services.calculation_service import calculate_from_answers
from ..states import Survey
from ..storage import CalculationRepository

router = Router(name=__name__)
logger = logging.getLogger(__name__)


async def _locale(state: FSMContext) -> str:
    return str((await state.get_data()).get("locale") or "ru")


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


async def _ask_safety_factor(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.safety_factor)
    locale = await _locale(state)
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
    building_type = data.get("building_type")
    building = (
        tr(f"survey.object.{building_type}", locale)
        if isinstance(building_type, str) and building_type in {"apartment", "house"}
        else tr("history.kind.unknown", locale)
    )
    climate_key = str(data.get("climate_key", "manual"))
    if climate_key in CLIMATES:
        climate_name = tr(f"climate.{climate_key}", locale)
    elif (
        climate_key == "custom"
        and isinstance(data.get("custom_city_name"), str)
        and str(data["custom_city_name"]).strip()
    ):
        climate_name = str(data["custom_city_name"]).strip()
    elif climate_key == "custom":
        climate_name = "—"
    else:
        climate_name = tr("survey.climate.manual_name", locale)
    wall_area = _safe_display_number(data.get("wall_gross_area", 0))
    window_area = _safe_display_number(data.get("window_area", 0))
    door_area = _safe_display_number(data.get("door_area", 0))
    openings_area = (
        window_area + door_area if window_area is not None and door_area is not None else None
    )
    airflow_components = tuple(
        _safe_display_number(data.get(key, 0))
        for key in (
            "mechanical_ventilation_m3_h",
            "natural_ventilation_m3_h",
            "infiltration_m3_h",
        )
    )
    airflow = (
        sum(value for value in airflow_components if value is not None)
        if all(value is not None for value in airflow_components)
        else None
    )
    if airflow == 0:
        airflow_text = tr(
            "survey.confirm.airflow_simple",
            locale,
            value=_display_number(data.get("air_changes", 0)),
        )
    else:
        airflow_text = tr(
            "survey.confirm.airflow_total",
            locale,
            value=_format_display_number(airflow),
        )
    safety_factor = _safe_display_number(data.get("safety_factor", 1))
    safety = None if safety_factor is None else (safety_factor - 1) * 100
    return tr(
        "survey.confirm.body",
        locale,
        title=tr("survey.confirm.title", locale),
        building=building,
        climate=climate_name,
        outdoor=_display_number(data.get("outdoor", 0)),
        indoor=_display_number(data.get("indoor", 0)),
        length=_display_number(data.get("length", 0)),
        width=_display_number(data.get("width", 0)),
        height=_display_number(data.get("height", 0)),
        walls=_format_display_number(wall_area),
        openings=_format_display_number(openings_area),
        airflow=airflow_text,
        safety="—" if safety is None else f"{safety:.0f}",
    )


def _safe_display_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _format_display_number(value: float | None) -> str:
    return "—" if value is None else f"{value:g}"


def _display_number(value: object) -> str:
    return _format_display_number(_safe_display_number(value))


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
async def safety_factor(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        factor = float(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer(tr("common.invalid_option", await _locale(state)), show_alert=True)
        return
    if factor not in {1.0, 1.10, 1.15, 1.20}:
        await callback.answer(tr("common.invalid_option", await _locale(state)), show_alert=True)
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
        from .climate import _ask_climate

        await _ask_climate(callback.message, state)
        await callback.answer()
        return
    if action in {"walls", "openings", "boundaries"}:
        from .boundaries import _ask_floor_boundary
        from .openings import _ask_windows
        from .walls import _ask_wall_method

        ask = {
            "walls": _ask_wall_method,
            "openings": _ask_windows,
            "boundaries": _ask_floor_boundary,
        }[action]
        await ask(callback.message, state)
        await callback.answer()
        return
    if action == "airflow":
        from .airflow import _ask_air_changes

        await _ask_air_changes(callback.message, state)
        await callback.answer()
        return
    if action != "calculate":
        await callback.answer(
            tr("survey.confirm.error.action", await _locale(state)), show_alert=True
        )
        return

    state_data = await state.get_data()
    data = {key: value for key, value in state_data.items() if not key.startswith("_")}
    locale = str(data.get("locale") or "ru")
    try:
        bundle = await asyncio.to_thread(calculate_from_answers, data)
    except InvalidCalculationData as exc:
        await callback.message.answer(tr("result.invalid", locale, message=str(exc)))
        await callback.answer()
        return
    except Exception:
        logger.exception("Unexpected calculation failure user_id=%s", callback.from_user.id)
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
        status = tr("result.unsaved", locale)
    else:
        status = tr("result.saved", locale, id=calculation_id)
    await _send_long_message(
        callback.message,
        status
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
        pdf_bytes = await asyncio.to_thread(build_pdf_report, bundle, data, callback.from_user.id)
        if calculation_id is not None:
            stored = await asyncio.to_thread(
                repository.store_pdf_for_user,
                callback.from_user.id,
                calculation_id,
                pdf_bytes,
            )
            if not stored:
                logger.error(
                    "PDF artifact could not be attached user_id=%s calculation_id=%s",
                    callback.from_user.id,
                    calculation_id,
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


async def render_result_step(message: Message, state: FSMContext) -> bool:
    """Re-render final review screens after draft restore or back navigation."""
    getter = getattr(state, "get_state", None)
    if getter is not None:
        current = await getter()
    else:
        value = getattr(state, "state", None)
        current = getattr(value, "state", value)
    if current == Survey.safety_factor.state:
        await _ask_safety_factor(message, state)
        return True
    if current == Survey.confirmation.state:
        await _ask_confirmation(message, state)
        return True
    return False
