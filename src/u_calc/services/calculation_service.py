from dataclasses import dataclass
from typing import Any

from ..calculator import calculate_climate_scenarios, calculate_heat_loss
from ..catalog import ClimateProfile
from ..models import Building, HeatLossResult
from ..report import format_report
from .building_factory import build_from_answers, climate_from_answers


@dataclass(frozen=True, slots=True)
class CalculationBundle:
    building: Building
    result: HeatLossResult
    climate: ClimateProfile | None
    scenario_results: dict[str, HeatLossResult] | None
    report: str


def calculate_from_answers(data: dict[str, Any]) -> CalculationBundle:
    building = build_from_answers(data)
    result = calculate_heat_loss(building)
    climate = climate_from_answers(data)
    scenario_results = calculate_climate_scenarios(building, climate) if climate else None
    report = format_report(
        building,
        result,
        climate,
        str(data.get("scenario", "manual")),
        scenario_results,
    )
    return CalculationBundle(building, result, climate, scenario_results, report)
