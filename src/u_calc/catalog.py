"""Engineering reference values used by the MVP.

Thermal conductivities are representative design values, not product certificates.
Every production calculation should allow an engineer to override them.
"""

from dataclasses import dataclass

CATALOG_VERSION = "2026.10.1"
ENGINE_VERSION = "0.2.0"
SHNQ_THERMAL_URL = "https://lex.uz/docs/-6874131"
SHNQ_CLIMATE_URL = "https://lex.uz/uz/acts/-6363141"


@dataclass(frozen=True, slots=True)
class Material:
    key: str
    name: str
    conductivity: float  # W/(m·K)
    source: str = "Справочный каталог U-Calc"
    source_url: str = SHNQ_THERMAL_URL
    standard: str = "ШНҚ 2.01.04-18; сверить конкретную позицию и условия эксплуатации"
    description: str = "Типовое проектное значение, не паспорт конкретного изделия"
    design_conditions: str = "Влажность и плотность материала должны быть подтверждены"


@dataclass(frozen=True, slots=True)
class WindowType:
    key: str
    name: str
    u_value: float  # W/(m²·K)


@dataclass(frozen=True, slots=True)
class DoorType:
    key: str
    name: str
    u_value: float  # W/(m²·K), reference value


@dataclass(frozen=True, slots=True)
class ClimateProfile:
    key: str
    name: str
    cold_month_mean_c: float
    design_c: float
    observed_extreme_c: float
    hot_month_mean_c: float
    observed_maximum_c: float
    future_uncertainty_c: float = 2.0
    source_note: str = "ШНҚ 2.01.01-22; расчётную температуру подтвердить для адреса объекта"
    source_url: str = SHNQ_CLIMATE_URL
    data_period: str = "нормативная климатическая таблица; период уточнять в первоисточнике"
    version: str = "ШНҚ 2.01.01-22"
    updated_at: str = "2026-10-07"

    def outdoor_temperature(self, scenario: str) -> float:
        if scenario == "economy":
            return self.cold_month_mean_c
        if scenario == "design":
            return self.design_c
        if scenario == "extreme":
            return self.observed_extreme_c
        if scenario == "future":
            # A risk envelope, not a deterministic weather forecast.
            return max(self.design_c - self.future_uncertainty_c, self.observed_extreme_c)
        raise ValueError(f"Неизвестный климатический сценарий: {scenario}")


MATERIALS = {
    item.key: item
    for item in (
        Material("brick_solid", "Кирпич полнотелый", 0.81),
        Material("brick_hollow", "Кирпич пустотелый", 0.47),
        Material("aerated_d500", "Газоблок D500", 0.14),
        Material("concrete", "Железобетон", 2.04),
        Material("wood", "Древесина поперёк волокон", 0.18),
        Material("mineral_wool", "Каменная/минеральная вата", 0.040),
        Material("eps", "Пенополистирол EPS", 0.041),
        Material("xps", "Экструдированный пенополистирол XPS", 0.034),
        Material("pu_foam", "Пенополиуретан", 0.028),
    )
}

WINDOWS = {
    item.key: item
    for item in (
        WindowType("single", "Одинарное стекло", 5.8),
        WindowType("double_old", "Старое двойное окно", 2.8),
        WindowType("double", "2-стекольный стеклопакет", 1.6),
        WindowType("triple", "3-стекольный стеклопакет", 1.0),
        WindowType("efficient", "Энергоэффективное окно", 0.8),
    )
}

DOORS = {
    item.key: item
    for item in (
        DoorType("wood_old", "Старая деревянная дверь", 3.0),
        DoorType("metal_basic", "Металлическая без терморазрыва", 2.5),
        DoorType("insulated", "Утеплённая наружная дверь", 1.5),
        DoorType("efficient", "Энергоэффективная дверь", 1.0),
    )
}

# Monthly means and absolute minima are from official SHNQ 2.01.01-22 table 1.
# Design values are editable defaults and must be checked for the object's exact locality.
CLIMATES = {
    item.key: item
    for item in (
        ClimateProfile("tashkent", "Ташкент", 1.9, -14.0, -29.5, 27.8, 44.6),
        ClimateProfile("samarkand", "Самарканд", 1.9, -14.0, -25.4, 26.8, 42.4),
        ClimateProfile("nukus", "Нукус", -3.7, -19.0, -34.2, 29.1, 46.8),
    )
}

SCENARIO_NAMES = {
    "economy": "средний холодный месяц",
    "design": "расчётный мороз",
    "extreme": "исторический экстремум",
    "future": "климатический риск / резерв",
    "manual": "ручная температура",
}
