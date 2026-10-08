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
        _require_finite_range(self.area_m2, "Площадь зоны, м²", 0.01, 100_000.0)
        _require_finite_range(self.resistance_m2k_w, "Сопротивление зоны, м²·К/Вт", 0.05, 100.0)


@dataclass(frozen=True, slots=True)
class Airflow:
    """Design airflows; heat recovery applies only to the mechanical component."""

    mechanical_m3_h: float = 0.0
    natural_m3_h: float = 0.0
    infiltration_m3_h: float = 0.0
    heat_recovery_efficiency: float = 0.0
    input_basis: str = "components_m3_h"

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


@dataclass(frozen=True, slots=True)
class HeatLossResult:
    transmission_w: float
    ventilation_w: float
    total_w: float
    recommended_w: float
    lines: tuple[LossLine, ...]

    @property
    def total_kw(self) -> float:
        return self.total_w / 1000

    @property
    def recommended_kw(self) -> float:
        return self.recommended_w / 1000
