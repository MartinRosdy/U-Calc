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
) -> tuple[GroundFloorZone, ...]:
    """Split a rectangular slab into 2 m perimeter zones.

    Base resistances follow Appendix 9 of SHNQ 2.04.05-22. In zone I the
    four 2x2 m exterior-corner areas are counted twice, following the
    long-established calculation convention for this zonal method.
    An insulating layer with lambda < 1.2 W/(m*K) adds d/lambda.
    """
    if not 0 < length_m <= 1_000 or not 0 < width_m <= 1_000:
        raise ValueError("Размеры пола должны быть больше нуля")
    if not 0 <= insulation_resistance_m2k_w <= 50:
        raise ValueError("Сопротивление утеплителя не может быть отрицательным")

    def inner_area(inset_m: float) -> float:
        return max(length_m - 2 * inset_m, 0.0) * max(width_m - 2 * inset_m, 0.0)

    nested_areas = [inner_area(inset) for inset in (0.0, 2.0, 4.0, 6.0)]
    zone_areas = [
        nested_areas[0] - nested_areas[1],
        nested_areas[1] - nested_areas[2],
        nested_areas[2] - nested_areas[3],
        nested_areas[3],
    ]
    corner_side = min(2.0, length_m / 2, width_m / 2)
    zone_areas[0] += 4 * corner_side**2
    return tuple(
        GroundFloorZone(
            name=f"Пол по грунту — зона {index}",
            area_m2=area,
            resistance_m2k_w=base_resistance + insulation_resistance_m2k_w,
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
        watts = u * surface.area_m2 * dt
        transmission += watts
        lines.append(LossLine(surface.name, "Ограждение", surface.area_m2, u, dt, watts))

    for opening in building.openings:
        dt = _delta_t(
            building.indoor_temperature_c,
            building.outdoor_temperature_c,
            opening.boundary,
            None,
        )
        watts = opening.u_value * opening.area_m2 * dt
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

    ventilation = (
        0.33
        * building.air_changes_per_hour
        * building.volume_m3
        * full_dt
        * (1 - building.heat_recovery_efficiency)
    )
    lines.append(LossLine("Воздухообмен", "Вентиляция", None, None, full_dt, ventilation))
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
