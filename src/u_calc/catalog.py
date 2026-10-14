"""Versioned engineering reference values used by U-Calc.

Thermal conductivities are representative design values, not product certificates.
Every production calculation should allow an engineer to override them.
"""

import math
from dataclasses import dataclass

CATALOG_VERSION = "2026.10.5"
ENGINE_VERSION = "1.0.0"
SHNQ_THERMAL_URL = "https://lex.uz/docs/-6874131"
SHNQ_THERMAL_PDF_URL = "https://lex.uz/files/8450985.pdf"
SHNQ_GASBLOCK_URL = "https://lex.uz/docs/-6540421"
SHNQ_CLIMATE_URL = "https://lex.uz/docs/-6363141"
SHNQ_CLIMATE_PDF_URL = "https://mc.uz/uploads/mcuz_5064970383794.pdf"
SHNQ_ENERGY_URL = "https://lex.uz/docs/-7340715"


@dataclass(frozen=True, slots=True)
class ValueSource:
    parameter: str
    value: float
    unit: str
    document: str
    edition: str
    location: str
    url: str
    observation_period: str
    updated_at: str
    status: str = "normative"


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
    density_or_grade: str = "не задано — выбрать точную нормативную строку или паспорт"
    table_row: str = "не подтверждена для обобщённой позиции"
    value_status: str = "reference_unverified"
    selectable: bool = True


@dataclass(frozen=True, slots=True)
class WindowType:
    key: str
    name: str
    u_value: float  # W/(m²·K)
    value_status: str = "typical_reference"
    source_note: str = "Не паспорт изделия; для рабочего расчёта ввести паспортный U"


@dataclass(frozen=True, slots=True)
class DoorType:
    key: str
    name: str
    u_value: float  # W/(m²·K), reference value
    value_status: str = "typical_reference"
    source_note: str = "Не паспорт изделия; для рабочего расчёта ввести паспортный U"


@dataclass(frozen=True, slots=True)
class ClimateProfile:
    key: str
    name: str
    cold_month_mean_c: float
    design_c: float | None
    observed_extreme_c: float
    hot_month_mean_c: float
    observed_maximum_c: float
    future_uncertainty_c: float = 2.0
    source_note: str = (
        "ШНҚ 2.01.01-22, таблицы 1 и 4; параметр Б определён по п. 14; "
        "для другого населённого пункта ввести адресные данные"
    )
    source_url: str = SHNQ_CLIMATE_PDF_URL
    data_period: str = "нормативная климатическая таблица; период уточнять в первоисточнике"
    version: str = "ШНҚ 2.01.01-22"
    updated_at: str = "2026-10-14"
    provenance: tuple[ValueSource, ...] = ()

    def __post_init__(self) -> None:
        temperatures = (
            self.cold_month_mean_c,
            self.observed_extreme_c,
            self.hot_month_mean_c,
            self.observed_maximum_c,
        )
        if not all(math.isfinite(value) and -100 <= value <= 100 for value in temperatures):
            raise ValueError("Температуры климатического профиля должны быть конечными")
        if self.observed_extreme_c > self.cold_month_mean_c:
            raise ValueError("Абсолютный минимум не может быть теплее холодного месяца")
        if self.design_c is not None:
            if not math.isfinite(self.design_c):
                raise ValueError("Расчётная температура должна быть конечной")
            if not self.observed_extreme_c <= self.design_c < self.cold_month_mean_c:
                raise ValueError(
                    "Расчётная температура должна быть между абсолютным минимумом "
                    "и средним холодного месяца"
                )
        if self.hot_month_mean_c < self.cold_month_mean_c:
            raise ValueError("Средний жаркий месяц не может быть холоднее холодного месяца")
        if self.observed_maximum_c < self.hot_month_mean_c:
            raise ValueError("Абсолютный максимум не может быть ниже среднего жаркого месяца")
        if not math.isfinite(self.future_uncertainty_c) or not 0 <= self.future_uncertainty_c <= 20:
            raise ValueError("Климатический резерв должен быть от 0 до 20 °C")

    def outdoor_temperature(self, scenario: str) -> float:
        if scenario == "economy":
            return self.cold_month_mean_c
        if scenario == "design":
            if self.design_c is None:
                raise ValueError("Расчётная температура требует подтверждения мастером")
            return self.design_c
        if scenario == "extreme":
            return self.observed_extreme_c
        if scenario == "future":
            if self.design_c is None:
                raise ValueError("Климатический резерв требует подтверждённой температуры")
            # A risk envelope, not a deterministic weather forecast.
            return max(self.design_c - self.future_uncertainty_c, self.observed_extreme_c)
        raise ValueError(f"Неизвестный климатический сценарий: {scenario}")


MATERIALS = {
    item.key: item
    for item in (
        Material(
            "brick_solid",
            "Кладка из полнотелого глиняного кирпича",
            0.81,
            source="ШНҚ 2.01.04-18, приложение 1",
            source_url=SHNQ_THERMAL_PDF_URL,
            standard="ШНҚ 2.01.04-18, приложение 1, позиция 84",
            description="Кладка на цементно-песчаном растворе; расчётная λБ",
            design_conditions="Приняты условия эксплуатации Б; для условий А λ=0,70",
            density_or_grade="1800 кг/м³; кирпич по O‘zDSt 3255-2017",
            table_row="приложение 1, позиция 84, колонка λБ",
            value_status="normative_design_b",
        ),
        Material(
            "brick_hollow",
            "Кладка из пустотелого керамического кирпича",
            0.52,
            source="ШНҚ 2.01.04-18, приложение 1",
            source_url=SHNQ_THERMAL_PDF_URL,
            standard="ШНҚ 2.01.04-18, приложение 1, позиция 93",
            description="Кладка на цементно-песчаном растворе; расчётная λБ",
            design_conditions="Приняты условия эксплуатации Б; для условий А λ=0,47",
            density_or_grade="1000 кг/м³ (брутто)",
            table_row="приложение 1, позиция 93, колонка λБ",
            value_status="normative_design_b",
        ),
        Material(
            "aerated_d500",
            "Автоклавный силикатный газобетон D500",
            0.147,
            source="ШНҚ 2.03.15-23, приложение 5",
            source_url=SHNQ_GASBLOCK_URL,
            standard="ШНҚ 2.03.15-23, приложение 5, таблица 2, позиция 2",
            description="Расчётная теплопроводность материала для условий Б",
            design_conditions="Приняты условия эксплуатации Б; для условий А λ=0,141",
            density_or_grade="D500; λ0=0,12 Вт/(м·К)",
            table_row="приложение 5, таблица 2, позиция 2, колонка λБ",
            value_status="normative_design_b",
        ),
        Material(
            "concrete",
            "Железобетон",
            2.04,
            source="ШНҚ 2.01.04-18, приложение 1",
            source_url=SHNQ_THERMAL_PDF_URL,
            standard="ШНҚ 2.01.04-18, приложение 1, позиция 1",
            description="Расчётная теплопроводность для условий Б",
            design_conditions="Приняты условия эксплуатации Б; для условий А λ=1,92",
            density_or_grade="2500 кг/м³",
            table_row="приложение 1, позиция 1, колонка λБ",
            value_status="normative_design_b",
        ),
        Material(
            "wood",
            "Сосна/ель поперёк волокон",
            0.18,
            source="ШНҚ 2.01.04-18, приложение 1",
            source_url=SHNQ_THERMAL_PDF_URL,
            standard="ШНҚ 2.01.04-18, приложение 1, позиция 108",
            description="Расчётная теплопроводность поперёк волокон для условий Б",
            design_conditions="Приняты условия эксплуатации Б; для условий А λ=0,14",
            density_or_grade="сосна/ель, 500 кг/м³",
            table_row="приложение 1, позиция 108, колонка λБ",
            value_status="normative_design_b",
        ),
        Material(
            "mineral_wool",
            "Минераловатный прошивной мат",
            0.050,
            source="Изменение 2024 года к ШНҚ 2.01.04-18, приложение 1",
            standard="ШНҚ 2.01.04-18, изменение 2024 года; позиция 129",
            description=(
                "Расчётная λБ=0,050; λ0=0,040 и λА=0,046 не используются как "
                "универсальное расчётное значение"
            ),
            design_conditions=(
                "Консервативно приняты условия Б; паспортная λ конкретного изделия приоритетна"
            ),
            density_or_grade="30–50 кг/м³; GOST 21880-2022",
            table_row="приложение 1, позиция 129, колонка λБ",
            value_status="normative_design_b",
        ),
        Material(
            "eps",
            "Пенополистирол EPS",
            0.050,
            source="ШНҚ 2.01.04-18, приложение 1",
            source_url=SHNQ_THERMAL_PDF_URL,
            standard="ШНҚ 2.01.04-18, приложение 1, позиция 138",
            description="Расчётная теплопроводность для условий Б",
            design_conditions="Приняты условия эксплуатации Б; для условий А λ=0,041",
            density_or_grade="40 кг/м³; ГОСТ 15588-2014",
            table_row="приложение 1, позиция 138, колонка λБ",
            value_status="normative_design_b",
        ),
        Material(
            "xps",
            "Экструдированный пенополистирол XPS",
            0.032,
            source="ШНҚ 2.01.04-18, приложение 1",
            source_url=SHNQ_THERMAL_PDF_URL,
            standard="ШНҚ 2.01.04-18, приложение 1, позиция 146г",
            description="Расчётная теплопроводность для условий Б",
            design_conditions="Приняты условия эксплуатации Б; для условий А λ=0,031",
            density_or_grade="45 кг/м³",
            table_row="приложение 1, позиция 146г, колонка λБ",
            value_status="normative_design_b",
        ),
        Material(
            "pu_foam",
            "Пенополиуретан (только старые расчёты)",
            0.028,
            source="Legacy-каталог U-Calc до 1.0",
            source_url="",
            standard="Точная марка и паспорт не были сохранены",
            description="Не предлагать в новом расчёте; использовать паспортную custom λ",
            design_conditions="Значение сохранено только для воспроизводимости старых записей",
            density_or_grade="неизвестно",
            table_row="не подтверждена; legacy compatibility",
            value_status="legacy_reference_unverified",
            selectable=False,
        ),
    )
}

SELECTABLE_MATERIALS = {
    key: material for key, material in MATERIALS.items() if material.selectable
}


def _climate_sources(
    city: str,
    cold_mean: float,
    design: float,
    extreme: float,
    hot_mean: float,
    maximum: float,
    extreme_year: int,
    maximum_year: int,
) -> tuple[ValueSource, ...]:
    common = dict(
        document="ШНҚ 2.01.01-22",
        edition="утверждён 19.12.2022, действует с 20.12.2022",
        url=SHNQ_CLIMATE_PDF_URL,
        observation_period="полный период наблюдений в публикации не указан",
        updated_at="2026-10-14",
    )
    return (
        ValueSource(
            "cold_month_mean_c",
            cold_mean,
            "°C",
            location=f"приложение, таблица 1, строка {city}, колонка I (январь)",
            **common,
        ),
        ValueSource(
            "design_c",
            design,
            "°C",
            location=(
                f"таблица 4, строка {city}, колонка 10 "
                "(параметры Б, холодный период, t); определение — п. 14"
            ),
            **common,
        ),
        ValueSource(
            "observed_extreme_c",
            extreme,
            "°C",
            location=(f"приложение, таблица 1, строка {city}, колонка 15; год {extreme_year}"),
            **common,
        ),
        ValueSource(
            "hot_month_mean_c",
            hot_mean,
            "°C",
            location=f"приложение, таблица 1, строка {city}, колонка VII (июль)",
            **common,
        ),
        ValueSource(
            "observed_maximum_c",
            maximum,
            "°C",
            location=(f"приложение, таблица 1, строка {city}, колонка 16; год {maximum_year}"),
            **common,
        ),
    )


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

# Monthly means and absolute extremes are from table 1; design values are the cold-period
# parameter B from table 4, column 10 of the official SHNQ 2.01.01-22 PDF.
CLIMATES = {
    item.key: item
    for item in (
        ClimateProfile(
            "tashkent",
            "Ташкент",
            1.9,
            -14.0,
            -29.5,
            27.8,
            44.6,
            provenance=_climate_sources(
                "Ташкент", 1.9, -14.0, -29.5, 27.8, 44.6, 1930, 1997
            ),
        ),
        ClimateProfile(
            "samarkand",
            "Самарканд",
            1.9,
            -12.0,
            -25.4,
            26.8,
            42.4,
            provenance=_climate_sources(
                "Самарканд", 1.9, -12.0, -25.4, 26.8, 42.4, 1969, 1983
            ),
        ),
        ClimateProfile(
            "nukus",
            "Нукус",
            -3.7,
            -20.0,
            -34.2,
            29.1,
            46.8,
            provenance=_climate_sources(
                "Нукус", -3.7, -20.0, -34.2, 29.1, 46.8, 1973, 2002
            ),
        ),
    )
}

SCENARIO_NAMES = {
    "economy": "средний холодный месяц",
    "design": "расчётный мороз",
    "extreme": "исторический экстремум",
    "future": "климатический риск / резерв",
    "manual": "ручная температура",
}
