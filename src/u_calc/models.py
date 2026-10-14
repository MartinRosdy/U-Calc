import math
from dataclasses import dataclass, field
from enum import StrEnum


class Boundary(StrEnum):
    OUTDOOR = "outdoor"
    UNHEATED = "unheated"
    GROUND = "ground"
    HEATED = "heated"


class SurfaceKind(StrEnum):
    WALL = "wall"
    FLOOR = "floor"
    CEILING = "ceiling"
    ROOF = "roof"


class Orientation(StrEnum):
    NORTH = "north"
    NORTH_EAST = "north_east"
    EAST = "east"
    SOUTH_EAST = "south_east"
    SOUTH = "south"
    SOUTH_WEST = "south_west"
    WEST = "west"
    NORTH_WEST = "north_west"


def _require_finite_range(
    value: float,
    label: str,
    minimum: float,
    maximum: float,
    *,
    inclusive_minimum: bool = True,
) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{label} должно быть конечным числом")
    below = value < minimum if inclusive_minimum else value <= minimum
    if below or value > maximum:
        left = "от" if inclusive_minimum else "больше"
        raise ValueError(f"{label} должно быть {left} {minimum:g} до {maximum:g}")


@dataclass(frozen=True, slots=True)
class Layer:
    material_key: str
    thickness_m: float
    conductivity_w_mk: float | None = None

    def __post_init__(self) -> None:
        _require_finite_range(self.thickness_m, "Толщина слоя, м", 0.001, 2.0)
        if self.conductivity_w_mk is not None:
            _require_finite_range(
                self.conductivity_w_mk,
                "Теплопроводность λ, Вт/(м·К)",
                0.005,
                5.0,
            )


@dataclass(frozen=True, slots=True)
class OpaqueSurface:
    name: str
    area_m2: float
    layers: tuple[Layer, ...]
    boundary: Boundary = Boundary.OUTDOOR
    adjacent_temperature_c: float | None = None
    kind: SurfaceKind = SurfaceKind.WALL
    additional_heat_loss_factor: float = 0.0
    position_factor: float = 1.0
    orientation: Orientation | None = None

    def __post_init__(self) -> None:
        _require_finite_range(self.area_m2, "Площадь ограждения, м²", 0.0, 100_000.0)
        if not self.layers and self.boundary != Boundary.HEATED:
            raise ValueError("Для ограждения нужен хотя бы один слой")
        if self.adjacent_temperature_c is not None:
            _require_finite_range(
                self.adjacent_temperature_c, "Температура смежной зоны, °C", -80.0, 70.0
            )
        _require_finite_range(self.additional_heat_loss_factor, "Дополнительные потери β", 0.0, 5.0)
        _require_finite_range(self.position_factor, "Коэффициент положения n", 0.0, 2.0)
        if self.orientation is not None and self.orientation not in tuple(Orientation):
            raise ValueError("Неизвестная ориентация ограждения")


@dataclass(frozen=True, slots=True)
class Opening:
    name: str
    area_m2: float
    u_value: float
    boundary: Boundary = Boundary.OUTDOOR
    additional_heat_loss_factor: float = 0.0
    position_factor: float = 1.0
    value_status: str = "unspecified"
    source_note: str = "Источник U не указан"
    orientation: Orientation | None = None

    def __post_init__(self) -> None:
        _require_finite_range(self.area_m2, "Площадь проёма, м²", 0.01, 10_000.0)
        _require_finite_range(self.u_value, "U-value проёма, Вт/(м²·К)", 0.1, 10.0)
        _require_finite_range(self.additional_heat_loss_factor, "Дополнительные потери β", 0.0, 5.0)
        _require_finite_range(self.position_factor, "Коэффициент положения n", 0.0, 2.0)
        if self.orientation is not None and self.orientation not in tuple(Orientation):
            raise ValueError("Неизвестная ориентация проёма")


@dataclass(frozen=True, slots=True)
class LinearThermalBridge:
    name: str
    length_m: float
    psi_w_mk: float

    def __post_init__(self) -> None:
        _require_finite_range(self.length_m, "Длина мостика, м", 0.01, 10_000.0)
        _require_finite_range(self.psi_w_mk, "ψ мостика, Вт/(м·К)", 0.0, 5.0)


@dataclass(frozen=True, slots=True)
class GroundFloorZone:
    name: str
    area_m2: float
    resistance_m2k_w: float

    def __post_init__(self) -> None:
        _require_finite_range(
            self.area_m2,
            "Площадь зоны, м²",
            0.0,
            1_000_000.0,
            inclusive_minimum=False,
        )
        _require_finite_range(self.resistance_m2k_w, "Сопротивление зоны, м²·К/Вт", 0.05, 100.0)


@dataclass(frozen=True, slots=True)
class Appendix8PressureInput:
    """Expert inputs for SHNQ 2.04.05-22 Appendix 8 formula (4)."""

    building_height_m: float
    opening_height_m: float
    indoor_temperature_c: float
    outdoor_temperature_c: float
    outdoor_air_density_kg_m3: float
    wind_speed_m_s: float
    windward_coefficient: float
    leeward_coefficient: float
    height_factor: float
    internal_pressure_pa: float

    def __post_init__(self) -> None:
        _require_finite_range(self.building_height_m, "Высота здания H, м", 0.01, 1_000.0)
        _require_finite_range(self.opening_height_m, "Высота проёма hi, м", 0.0, 1_000.0)
        if self.opening_height_m > self.building_height_m:
            raise ValueError("Высота проёма hi не может превышать высоту здания H")
        _require_finite_range(self.indoor_temperature_c, "Температура внутри, °C", -80, 100)
        _require_finite_range(self.outdoor_temperature_c, "Температура снаружи, °C", -100, 80)
        _require_finite_range(
            self.outdoor_air_density_kg_m3, "Плотность наружного воздуха, кг/м³", 0.5, 2.0
        )
        _require_finite_range(self.wind_speed_m_s, "Скорость ветра, м/с", 0.0, 100.0)
        _require_finite_range(self.windward_coefficient, "Коэффициент cₑ,n", -5.0, 5.0)
        _require_finite_range(self.leeward_coefficient, "Коэффициент cₑ,p", -5.0, 5.0)
        _require_finite_range(self.height_factor, "Коэффициент k₁", 0.0, 10.0)
        _require_finite_range(
            self.internal_pressure_pa, "Внутреннее давление pᵢnt, Па", -5_000, 5_000
        )


@dataclass(frozen=True, slots=True)
class InfiltrationPath:
    """One pressure group for SHNQ 2.04.05-22 Appendix 8 formula (3)."""

    pressure_pa: float
    first_floor_pressure_pa: float
    opening_area_m2: float = 0.0
    air_permeability_resistance_m2_h_pa_kg: float = 0.0
    envelope_area_m2: float = 0.0
    normative_air_permeability_kg_m2_h: float = 0.0
    gap_area_m2: float = 0.0
    panel_joint_length_m: float = 0.0
    pressure_input: Appendix8PressureInput | None = None
    first_floor_pressure_input: Appendix8PressureInput | None = None

    def __post_init__(self) -> None:
        _require_finite_range(self.pressure_pa, "Расчётный перепад давления, Па", 0.01, 5_000.0)
        _require_finite_range(
            self.first_floor_pressure_pa,
            "Перепад давления первого этажа, Па",
            0.01,
            5_000.0,
        )
        for value, label, maximum in (
            (self.opening_area_m2, "Площадь световых проёмов A1, м²", 100_000.0),
            (self.envelope_area_m2, "Площадь прочих ограждений A2, м²", 1_000_000.0),
            (self.gap_area_m2, "Площадь отверстий A3, м²", 10_000.0),
            (self.panel_joint_length_m, "Длина стыков l, м", 1_000_000.0),
        ):
            _require_finite_range(value, label, 0.0, maximum)
        _require_finite_range(
            self.air_permeability_resistance_m2_h_pa_kg,
            "Сопротивление воздухопроницанию Ru",
            0.0,
            1_000_000.0,
        )
        _require_finite_range(
            self.normative_air_permeability_kg_m2_h,
            "Нормативная воздухопроницаемость Gn",
            0.0,
            10_000.0,
        )
        if self.opening_area_m2 > 0 and self.air_permeability_resistance_m2_h_pa_kg <= 0:
            raise ValueError("Для A1 больше нуля требуется положительное Ru")
        if self.envelope_area_m2 > 0 and self.normative_air_permeability_kg_m2_h <= 0:
            raise ValueError("Для A2 больше нуля требуется положительное Gn")
        if (self.pressure_input is None) != (self.first_floor_pressure_input is None):
            raise ValueError("Для формулы 4 нужны исходные данные обеих высот")


@dataclass(frozen=True, slots=True)
class Airflow:
    """Design airflows; heat recovery applies only to the mechanical component."""

    mechanical_m3_h: float = 0.0
    natural_m3_h: float = 0.0
    infiltration_m3_h: float = 0.0
    heat_recovery_efficiency: float = 0.0
    input_basis: str = "components_m3_h"
    infiltration_basis: str = "manual_flow"
    infiltration_paths: tuple[InfiltrationPath, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for value, label in (
            (self.mechanical_m3_h, "Механическая вентиляция, м³/ч"),
            (self.natural_m3_h, "Естественная вентиляция, м³/ч"),
            (self.infiltration_m3_h, "Инфильтрация, м³/ч"),
        ):
            _require_finite_range(value, label, 0.0, 10_000_000.0)
        _require_finite_range(self.heat_recovery_efficiency, "КПД рекуперации", 0.0, 0.95)
        if self.input_basis not in {"components_m3_h", "components_ach", "quick_estimate"}:
            raise ValueError("Неизвестный способ задания воздухообмена")
        if self.infiltration_basis not in {
            "manual_flow",
            "none",
            "appendix8_residential_exhaust",
            "appendix8_envelope",
            "quick_estimate",
        }:
            raise ValueError("Неизвестный способ задания инфильтрации")
        if self.infiltration_basis == "appendix8_envelope" and not self.infiltration_paths:
            raise ValueError("Для формулы 3 приложения 8 нужна хотя бы одна группа ограждений")
        if self.infiltration_basis != "appendix8_envelope" and self.infiltration_paths:
            raise ValueError("Группы воздухопроницаемости допустимы только для формулы 3")


@dataclass(frozen=True, slots=True)
class Building:
    indoor_temperature_c: float
    outdoor_temperature_c: float
    volume_m3: float
    opaque_surfaces: tuple[OpaqueSurface, ...]
    heated_area_m2: float | None = None
    length_m: float | None = None
    width_m: float | None = None
    height_m: float | None = None
    openings: tuple[Opening, ...] = field(default_factory=tuple)
    ground_floor_zones: tuple[GroundFloorZone, ...] = field(default_factory=tuple)
    linear_thermal_bridges: tuple[LinearThermalBridge, ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    airflow: Airflow | None = None
    # Compatibility fields for calculations saved before format 0.3.
    air_changes_per_hour: float = 0.5
    heat_recovery_efficiency: float = 0.0
    thermal_bridge_factor: float = 0.0
    safety_factor: float = 1.10

    def __post_init__(self) -> None:
        _require_finite_range(self.volume_m3, "Объём, м³", 1.0, 10_000_000.0)
        if self.heated_area_m2 is not None:
            _require_finite_range(self.heated_area_m2, "Отапливаемая площадь, м²", 1.0, 1_000_000.0)
        for dimension, label in (
            (self.length_m, "Длина"),
            (self.width_m, "Ширина"),
            (self.height_m, "Высота"),
        ):
            if dimension is not None:
                _require_finite_range(dimension, f"{label}, м", 0.1, 1_000.0)
        _require_finite_range(self.indoor_temperature_c, "Внутренняя температура, °C", -30.0, 50.0)
        _require_finite_range(self.outdoor_temperature_c, "Наружная температура, °C", -80.0, 50.0)
        if self.indoor_temperature_c <= self.outdoor_temperature_c:
            raise ValueError("Внутренняя температура должна быть выше наружной")
        _require_finite_range(self.air_changes_per_hour, "Воздухообмен, 1/ч", 0.0, 10.0)
        _require_finite_range(self.heat_recovery_efficiency, "КПД рекуперации", 0.0, 0.95)
        _require_finite_range(self.thermal_bridge_factor, "Поправка на мостики холода", 0.0, 0.5)
        if self.thermal_bridge_factor and self.linear_thermal_bridges:
            raise ValueError("Нельзя одновременно применять процентные и точные мостики холода")
        _require_finite_range(self.safety_factor, "Коэффициент запаса", 1.0, 1.5)
        for surface in self.opaque_surfaces:
            if (
                surface.adjacent_temperature_c is not None
                and surface.adjacent_temperature_c >= self.indoor_temperature_c
            ):
                raise ValueError(
                    f"Температура смежной зоны «{surface.name}» должна быть ниже внутренней"
                )


@dataclass(frozen=True, slots=True)
class LossLine:
    name: str
    kind: str
    area_m2: float | None
    u_value: float | None
    delta_t_k: float
    watts: float
    surface_kind: SurfaceKind | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Название строки теплопотерь не может быть пустым")
        if not self.kind.strip():
            raise ValueError("Тип строки теплопотерь не может быть пустым")
        if self.area_m2 is not None:
            _require_finite_range(self.area_m2, "Площадь/длина строки", 0.0, 1_000_000.0)
        if self.u_value is not None:
            _require_finite_range(self.u_value, "U/ψ строки", 0.0, 1_000.0)
        _require_finite_range(self.delta_t_k, "ΔT строки, K", 0.0, 200.0)
        _require_finite_range(self.watts, "Теплопотери строки, Вт", 0.0, 1_000_000_000.0)
        if self.surface_kind is not None and self.surface_kind not in tuple(SurfaceKind):
            raise ValueError("Неизвестный тип поверхности строки")


@dataclass(frozen=True, slots=True)
class HeatLossResult:
    transmission_w: float
    ventilation_w: float
    total_w: float
    recommended_w: float
    lines: tuple[LossLine, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.transmission_w, "Трансмиссионные потери, Вт"),
            (self.ventilation_w, "Воздушные потери, Вт"),
            (self.total_w, "Итоговые потери, Вт"),
            (self.recommended_w, "Рекомендуемая мощность, Вт"),
        ):
            _require_finite_range(value, label, 0.0, 1_000_000_000.0)
        component_total = self.transmission_w + self.ventilation_w
        if not math.isclose(self.total_w, component_total, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError("Итоговые потери не равны сумме ограждений и воздухообмена")
        line_total = sum(line.watts for line in self.lines)
        if not math.isclose(self.total_w, line_total, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError("Итоговые потери не равны сумме строк расчёта")
        if self.recommended_w + 1e-6 < self.total_w:
            raise ValueError("Рекомендуемая мощность не может быть ниже расчётной")

    @property
    def total_kw(self) -> float:
        return self.total_w / 1000

    @property
    def recommended_kw(self) -> float:
        return self.recommended_w / 1000
