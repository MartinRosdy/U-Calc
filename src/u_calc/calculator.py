import math
from dataclasses import replace

from .catalog import MATERIALS, ClimateProfile
from .models import (
    Appendix8PressureInput,
    Boundary,
    Building,
    GroundFloorZone,
    HeatLossResult,
    InfiltrationPath,
    LossLine,
    OpaqueSurface,
    Orientation,
    SurfaceKind,
)

INTERNAL_SURFACE_RESISTANCE = {
    SurfaceKind.WALL: 0.13,
    SurfaceKind.FLOOR: 0.17,
    SurfaceKind.CEILING: 0.10,
    SurfaceKind.ROOF: 0.10,
}

# ISO 6946:2017, table 7: Rse=0.04 m²K/W for surfaces facing outdoor air.
# For another room/air zone, both faces use internal surface resistance.
EXTERNAL_SURFACE_RESISTANCE = 0.04

BOUNDARY_FACTORS = {
    Boundary.OUTDOOR: 1.0,
    Boundary.UNHEATED: 0.7,
    Boundary.GROUND: 0.5,
    Boundary.HEATED: 0.0,
}

GROUND_ZONE_RESISTANCES = (2.1, 4.3, 8.5, 14.2)

# SHNQ 2.04.05-22, appendix 9, clause 2(a), current revision 07.07.2026.
# South and south-west are not assigned an orientation increment by this clause.
ORIENTATION_HEAT_LOSS_FACTORS = {
    Orientation.NORTH: 0.10,
    Orientation.NORTH_EAST: 0.10,
    Orientation.EAST: 0.10,
    Orientation.SOUTH_EAST: 0.05,
    Orientation.SOUTH: 0.0,
    Orientation.SOUTH_WEST: 0.0,
    Orientation.WEST: 0.05,
    Orientation.NORTH_WEST: 0.10,
}


def orientation_heat_loss_factor(orientation: Orientation | None) -> float:
    """Return the normative orientation increment, or zero when it is unknown."""
    return ORIENTATION_HEAT_LOSS_FACTORS.get(orientation, 0.0)


def appendix8_infiltration_mass_flow(paths: tuple[InfiltrationPath, ...]) -> float:
    """Return infiltrating air mass flow in kg/h by Appendix 8 formula (3).

    Each item represents surfaces at one calculated pressure difference. This
    preserves the summation prescribed by the formula instead of averaging
    pressure across openings at different elevations.
    """
    total = 0.0
    for path in paths:
        pressure_ratio = path.pressure_pa / path.first_floor_pressure_pa
        opening_term = 0.0
        if path.opening_area_m2:
            opening_term = (
                0.216
                * path.opening_area_m2
                * path.pressure_pa**0.67
                / path.air_permeability_resistance_m2_h_pa_kg
            )
        total += (
            opening_term
            + path.envelope_area_m2
            * path.normative_air_permeability_kg_m2_h
            * pressure_ratio**0.67
            + 3456 * path.gap_area_m2 * path.pressure_pa**0.5
            + 0.5 * path.panel_joint_length_m * pressure_ratio
        )
    return total


def appendix8_air_specific_weight_n_m3(temperature_c: float) -> float:
    """Return air specific weight by Appendix 8 formula (5), N/m³."""
    if not isinstance(temperature_c, (int, float)) or not math.isfinite(temperature_c):
        raise ValueError("Температура воздуха должна быть конечным числом")
    if temperature_c <= -273:
        raise ValueError("Температура воздуха должна быть выше −273 °C")
    return 3463.0 / (273.0 + temperature_c)


def appendix8_pressure_difference_pa(inputs: Appendix8PressureInput) -> float:
    """Return the signed pressure difference from Appendix 8 formula (4)."""
    indoor_weight = appendix8_air_specific_weight_n_m3(inputs.indoor_temperature_c)
    outdoor_weight = appendix8_air_specific_weight_n_m3(inputs.outdoor_temperature_c)
    stack = (inputs.building_height_m - inputs.opening_height_m) * (
        indoor_weight - outdoor_weight
    )
    wind = (
        0.5
        * inputs.outdoor_air_density_kg_m3
        * inputs.wind_speed_m_s**2
        * (inputs.windward_coefficient - inputs.leeward_coefficient)
        * inputs.height_factor
    )
    return stack + wind - inputs.internal_pressure_pa


def ground_floor_zones(
    length_m: float,
    width_m: float,
    insulation_resistance_m2k_w: float = 0.0,
    exterior_sides: tuple[str, ...] = ("north", "east", "south", "west"),
    floor_on_joists: bool = False,
) -> tuple[GroundFloorZone, ...]:
    """Split a rectangular slab into 2 m zones along selected exterior walls.

    Base resistances follow Appendix 9 of SHNQ 2.04.05-22. In zone I the
    exterior-corner areas are counted twice, following the
    long-established calculation convention for this zonal method.
    An insulating layer with lambda < 1.2 W/(m*K) adds d/lambda.
    For a floor on joists the resulting resistance is multiplied by 1.18.
    """
    if not 0 < length_m <= 1_000 or not 0 < width_m <= 1_000:
        raise ValueError("Размеры пола должны быть больше нуля")
    if not 0 <= insulation_resistance_m2k_w <= 50:
        raise ValueError("Сопротивление утеплителя не может быть отрицательным")
    allowed_sides = {"north", "east", "south", "west"}
    if not exterior_sides or len(set(exterior_sides)) != len(exterior_sides):
        raise ValueError("Нужно указать неповторяющиеся наружные стороны пола")
    if not set(exterior_sides) <= allowed_sides:
        raise ValueError("Неизвестная наружная сторона пола")

    x_breaks = {0.0, length_m}
    y_breaks = {0.0, width_m}
    for offset in (2.0, 4.0, 6.0):
        if "west" in exterior_sides:
            x_breaks.add(min(offset, length_m))
        if "east" in exterior_sides:
            x_breaks.add(max(length_m - offset, 0.0))
        if "south" in exterior_sides:
            y_breaks.add(min(offset, width_m))
        if "north" in exterior_sides:
            y_breaks.add(max(width_m - offset, 0.0))

    zone_areas = [0.0, 0.0, 0.0, 0.0]
    xs = sorted(x_breaks)
    ys = sorted(y_breaks)
    for x0, x1 in zip(xs, xs[1:], strict=False):
        for y0, y1 in zip(ys, ys[1:], strict=False):
            midpoint_x = (x0 + x1) / 2
            midpoint_y = (y0 + y1) / 2
            distances = []
            if "west" in exterior_sides:
                distances.append(midpoint_x)
            if "east" in exterior_sides:
                distances.append(length_m - midpoint_x)
            if "south" in exterior_sides:
                distances.append(midpoint_y)
            if "north" in exterior_sides:
                distances.append(width_m - midpoint_y)
            zone_index = min(int(min(distances) // 2), 3)
            zone_areas[zone_index] += (x1 - x0) * (y1 - y0)

    adjacent_pairs = (
        ("north", "east"),
        ("east", "south"),
        ("south", "west"),
        ("west", "north"),
    )
    corner_side = min(2.0, length_m / 2, width_m / 2)
    exterior_set = set(exterior_sides)
    zone_areas[0] += sum(
        corner_side**2 for first, second in adjacent_pairs if {first, second} <= exterior_set
    )
    return tuple(
        GroundFloorZone(
            name=f"Пол по грунту — зона {index}",
            area_m2=area,
            resistance_m2k_w=(base_resistance + insulation_resistance_m2k_w)
            * (1.18 if floor_on_joists else 1.0),
        )
        for index, (area, base_resistance) in enumerate(
            zip(zone_areas, GROUND_ZONE_RESISTANCES, strict=True), start=1
        )
        if area > 0
    )


def surface_resistances(surface: OpaqueSurface) -> tuple[float, float]:
    r_inside = INTERNAL_SURFACE_RESISTANCE[surface.kind]
    if surface.boundary == Boundary.OUTDOOR:
        return r_inside, EXTERNAL_SURFACE_RESISTANCE
    if surface.boundary == Boundary.GROUND:
        return r_inside, 0.0
    return r_inside, INTERNAL_SURFACE_RESISTANCE[surface.kind]


def u_value(surface: OpaqueSurface) -> float:
    """Return U-value in W/(m²·K) from layer resistances."""
    r_inside, r_outside = surface_resistances(surface)
    resistance = r_inside + r_outside
    for layer in surface.layers:
        if layer.conductivity_w_mk is not None:
            conductivity = layer.conductivity_w_mk
        else:
            try:
                conductivity = MATERIALS[layer.material_key].conductivity
            except KeyError as exc:
                raise ValueError(f"Неизвестный материал: {layer.material_key}") from exc
        resistance += layer.thickness_m / conductivity
    return 1 / resistance


def _delta_t(indoor: float, outdoor: float, boundary: Boundary, adjacent: float | None) -> float:
    if boundary == Boundary.HEATED:
        return 0.0 if adjacent is None else max(0.0, indoor - adjacent)
    if adjacent is not None:
        return max(0.0, indoor - adjacent)
    return max(0.0, indoor - outdoor) * BOUNDARY_FACTORS[boundary]


def calculate_heat_loss(building: Building) -> HeatLossResult:
    """Calculate steady-state design heat loss.

    Q_transmission = U × A × ΔT. Air losses use separate mechanical, natural and
    infiltration flows; heat recovery applies only to the mechanical component.
    Results are heating-system load estimates, not annual energy consumption.
    """
    lines: list[LossLine] = []
    transmission = 0.0
    for surface in building.opaque_surfaces:
        if (
            surface.boundary == Boundary.HEATED
            and not surface.layers
            and surface.adjacent_temperature_c is None
        ):
            lines.append(
                LossLine(
                    surface.name,
                    "Ограждение",
                    surface.area_m2,
                    None,
                    0.0,
                    0.0,
                    surface.kind,
                )
            )
            continue
        u = u_value(surface)
        dt = _delta_t(
            building.indoor_temperature_c,
            building.outdoor_temperature_c,
            surface.boundary,
            surface.adjacent_temperature_c,
        )
        watts = (
            u
            * surface.area_m2
            * dt
            * (1 + surface.additional_heat_loss_factor)
            * surface.position_factor
        )
        transmission += watts
        lines.append(
            LossLine(surface.name, "Ограждение", surface.area_m2, u, dt, watts, surface.kind)
        )

    for opening in building.openings:
        dt = _delta_t(
            building.indoor_temperature_c,
            building.outdoor_temperature_c,
            opening.boundary,
            None,
        )
        watts = (
            opening.u_value
            * opening.area_m2
            * dt
            * (1 + opening.additional_heat_loss_factor)
            * opening.position_factor
        )
        transmission += watts
        lines.append(LossLine(opening.name, "Проём", opening.area_m2, opening.u_value, dt, watts))

    full_dt = building.indoor_temperature_c - building.outdoor_temperature_c
    for zone in building.ground_floor_zones:
        u = 1 / zone.resistance_m2k_w
        watts = u * zone.area_m2 * full_dt
        transmission += watts
        lines.append(
            LossLine(
                zone.name,
                "Пол по грунту",
                zone.area_m2,
                u,
                full_dt,
                watts,
                SurfaceKind.FLOOR,
            )
        )

    bridge_loss = transmission * building.thermal_bridge_factor
    if bridge_loss:
        transmission += bridge_loss
        lines.append(
            LossLine(
                "Мостики холода (оценка)",
                "Поправка",
                None,
                None,
                building.indoor_temperature_c - building.outdoor_temperature_c,
                bridge_loss,
            )
        )

    for bridge in building.linear_thermal_bridges:
        watts = bridge.psi_w_mk * bridge.length_m * full_dt
        transmission += watts
        lines.append(
            LossLine(
                f"Мостик: {bridge.name}",
                "Линейный мостик",
                bridge.length_m,
                bridge.psi_w_mk,
                full_dt,
                watts,
            )
        )

    if building.airflow is None:
        # A legacy v0.2 ACH did not distinguish mechanical ventilation from
        # infiltration. Recalculating it as recoverable would understate the load,
        # so preserve the input but conservatively treat the combined flow as natural.
        mechanical_flow = 0.0
        natural_flow = building.air_changes_per_hour * building.volume_m3
        infiltration_flow = 0.0
        recovery = 0.0
    else:
        mechanical_flow = building.airflow.mechanical_m3_h
        natural_flow = building.airflow.natural_m3_h
        infiltration_flow = building.airflow.infiltration_m3_h
        recovery = building.airflow.heat_recovery_efficiency

    mechanical_loss = 0.33 * mechanical_flow * full_dt * (1 - recovery)
    natural_loss = 0.33 * natural_flow * full_dt
    if (
        building.airflow is not None
        and building.airflow.infiltration_basis == "appendix8_residential_exhaust"
    ):
        # SHNQ 2.04.05-22, appendix 8, formula (2):
        # Q = 0.28 * L_n * rho * c * delta_t, c = 1 kJ/(kg*K).
        room_air_density = 353 / (273 + building.indoor_temperature_c)
        infiltration_loss = 0.28 * infiltration_flow * room_air_density * full_dt
    elif (
        building.airflow is not None
        and building.airflow.infiltration_basis == "appendix8_envelope"
    ):
        # Appendix 8 requires the larger heat loss from formulas (1) and (2).
        mass_flow = appendix8_infiltration_mass_flow(building.airflow.infiltration_paths)
        formula_three_loss = 0.28 * mass_flow * full_dt
        room_air_density = 353 / (273 + building.indoor_temperature_c)
        formula_two_loss = 0.28 * infiltration_flow * room_air_density * full_dt
        infiltration_loss = max(formula_three_loss, formula_two_loss)
    else:
        infiltration_loss = 0.33 * infiltration_flow * full_dt
    airflow_lines = (
        ("Механическая вентиляция", "Вентиляция", mechanical_flow, mechanical_loss),
        ("Естественная вентиляция", "Вентиляция", natural_flow, natural_loss),
        ("Инфильтрация", "Инфильтрация", infiltration_flow, infiltration_loss),
    )
    for name, kind, flow, watts in airflow_lines:
        lines.append(LossLine(name, kind, flow, None, full_dt, watts))
    ventilation = mechanical_loss + natural_loss + infiltration_loss
    total = transmission + ventilation
    return HeatLossResult(
        transmission_w=transmission,
        ventilation_w=ventilation,
        total_w=total,
        recommended_w=total * building.safety_factor,
        lines=tuple(lines),
    )


def calculate_climate_scenarios(
    building: Building, climate: ClimateProfile
) -> dict[str, HeatLossResult]:
    """Recalculate an unchanged building for every supported winter scenario."""
    return {
        scenario: calculate_heat_loss(
            replace(building, outdoor_temperature_c=climate.outdoor_temperature(scenario))
        )
        for scenario in ("economy", "design", "future", "extreme")
    }
