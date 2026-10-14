import math
from dataclasses import dataclass
from typing import Any

from ..calculator import calculate_climate_scenarios, calculate_heat_loss
from ..catalog import ClimateProfile
from ..models import Building, HeatLossResult
from ..report import format_report
from .building_factory import InvalidCalculationData, build_from_answers, climate_from_answers


@dataclass(frozen=True, slots=True)
class CalculationBundle:
    building: Building
    result: HeatLossResult
    climate: ClimateProfile | None
    scenario_results: dict[str, HeatLossResult] | None
    report: str


def calculate_from_answers(data: dict[str, Any]) -> CalculationBundle:
    building = build_from_answers(data)
    climate = climate_from_answers(data)
    locale_raw = data.get("locale", "ru")
    if locale_raw not in {"ru", "uz"}:
        raise InvalidCalculationData("Неизвестный язык расчёта")
    locale = str(locale_raw)
    scenario_raw = data.get("scenario")
    if climate is None:
        if scenario_raw not in {None, "manual"}:
            raise InvalidCalculationData("Для ручного климата допустим только ручной сценарий")
        scenario = "manual"
    else:
        if climate.design_c is None:
            raise InvalidCalculationData(
                "Расчётная температура климатического профиля не подтверждена"
            )
        if scenario_raw not in {"economy", "design", "extreme", "future"}:
            raise InvalidCalculationData("Не выбран корректный климатический сценарий")
        scenario = str(scenario_raw)
        expected_outdoor = climate.outdoor_temperature(scenario)
        if not math.isclose(
            building.outdoor_temperature_c,
            expected_outdoor,
            rel_tol=0,
            abs_tol=1e-9,
        ):
            raise InvalidCalculationData(
                "Наружная температура не соответствует выбранному климатическому сценарию"
            )
    result = calculate_heat_loss(building)
    scenario_results = calculate_climate_scenarios(building, climate) if climate else None
    report = format_report(
        building,
        result,
        climate,
        scenario,
        scenario_results,
        locale,
    )
    return CalculationBundle(building, result, climate, scenario_results, report)
