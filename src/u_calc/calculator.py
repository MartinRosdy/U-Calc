from dataclasses import replace

from .catalog import MATERIALS, ClimateProfile
from .models import (
    Boundary,
    Building,
    GroundFloorZone,
    HeatLossResult,
    LossLine,
    OpaqueSurface,
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

    Q_transmission = U × A × ΔT. Ventilation uses 0.33 × ACH × volume × ΔT.
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
            lines.append(LossLine(surface.name, "Ограждение", surface.area_m2, None, 0.0, 0.0))
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
        lines.append(LossLine(surface.name, "Ограждение", surface.area_m2, u, dt, watts))

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
        lines.append(LossLine(zone.name, "Пол по грунту", zone.area_m2, u, full_dt, watts))

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
        # Backward compatibility for v0.2 payloads: the historical ACH represented
        # one recoverable flow. New calculations always provide explicit components.
        mechanical_flow = building.air_changes_per_hour * building.volume_m3
        natural_flow = 0.0
        infiltration_flow = 0.0
        recovery = building.heat_recovery_efficiency
    else:
        mechanical_flow = building.airflow.mechanical_m3_h
        natural_flow = building.airflow.natural_m3_h
        infiltration_flow = building.airflow.infiltration_m3_h
        recovery = building.airflow.heat_recovery_efficiency

    mechanical_loss = 0.33 * mechanical_flow * full_dt * (1 - recovery)
    natural_loss = 0.33 * natural_flow * full_dt
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
