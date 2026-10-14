import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from u_calc.calculator import calculate_heat_loss, ground_floor_zones
from u_calc.models import Airflow, Boundary, Building, Layer, OpaqueSurface, SurfaceKind
from u_calc.services.building_factory import build_from_answers

FINITE_POSITIVE = st.floats(
    min_value=0.1,
    max_value=1_000,
    allow_nan=False,
    allow_infinity=False,
)
EXTERIOR_SIDES = st.sets(
    st.sampled_from(("north", "east", "south", "west")),
    min_size=1,
    max_size=4,
).map(lambda values: tuple(sorted(values)))


@settings(max_examples=150, deadline=None)
@given(
    north_area=st.floats(
        min_value=1,
        max_value=1_000,
        allow_nan=False,
        allow_infinity=False,
    ),
    south_area=st.floats(
        min_value=1,
        max_value=1_000,
        allow_nan=False,
        allow_infinity=False,
    ),
    assigned_fraction=st.floats(
        min_value=0,
        max_value=0.9,
        allow_nan=False,
        allow_infinity=False,
    ),
    unassigned_fraction=st.floats(
        min_value=0,
        max_value=0.9,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_mixed_opening_distribution_preserves_gross_wall_area(
    north_area: float,
    south_area: float,
    assigned_fraction: float,
    unassigned_fraction: float,
) -> None:
    assigned_area = north_area * assigned_fraction
    if assigned_area < 0.01:
        assigned_area = 0.0
    remaining = north_area + south_area - assigned_area
    unassigned_area = remaining * unassigned_fraction
    if unassigned_area < 0.01:
        unassigned_area = 0.0
    window_groups = []
    if assigned_area >= 0.01:
        window_groups.append(
            {
                "name": "Привязанные",
                "count": 1,
                "area_m2": assigned_area,
                "u_value": 1.1,
                "wall_name": "Север",
            }
        )
    if unassigned_area >= 0.01:
        window_groups.append(
            {
                "name": "Непривязанные",
                "count": 1,
                "area_m2": unassigned_area,
                "u_value": 1.1,
                "wall_name": None,
            }
        )
    building = build_from_answers(
        {
            "wall_groups": [
                {
                    "name": "Север",
                    "gross_area_m2": north_area,
                    "material": "brick_solid",
                    "thickness_m": 0.25,
                },
                {
                    "name": "Юг",
                    "gross_area_m2": south_area,
                    "material": "brick_solid",
                    "thickness_m": 0.25,
                },
            ],
            "wall_gross_area": north_area + south_area,
            "window_area": sum(item["area_m2"] for item in window_groups),
            "window_groups": window_groups,
            "door_area": 0,
            "length": 10,
            "width": 8,
            "height": 3,
            "volume": 240,
            "floor_boundary": "heated",
            "ceiling_boundary": "heated",
            "indoor": 24,
            "outdoor": -14,
            "air_changes": 0.5,
        }
    )
    wall_surfaces = [
        surface for surface in building.opaque_surfaces if surface.kind == SurfaceKind.WALL
    ]
    actual_opening_area = sum(opening.area_m2 for opening in building.openings)
    assert all(surface.area_m2 >= 0 for surface in wall_surfaces)
    assert sum(surface.area_m2 for surface in wall_surfaces) + actual_opening_area == pytest.approx(
        north_area + south_area
    )


@settings(max_examples=150, deadline=None)
@given(length=FINITE_POSITIVE, width=FINITE_POSITIVE, sides=EXTERIOR_SIDES)
def test_ground_zone_partition_preserves_area_plus_documented_corner_counting(
    length: float,
    width: float,
    sides: tuple[str, ...],
) -> None:
    zones = ground_floor_zones(length, width, exterior_sides=sides)
    side_set = set(sides)
    adjacent_pairs = (
        {"north", "east"},
        {"east", "south"},
        {"south", "west"},
        {"west", "north"},
    )
    corner_count = sum(pair <= side_set for pair in adjacent_pairs)
    corner_side = min(2.0, length / 2, width / 2)
    expected_calculation_area = length * width + corner_count * corner_side**2

    assert sum(zone.area_m2 for zone in zones) == pytest.approx(expected_calculation_area)
    assert all(zone.area_m2 > 0 for zone in zones)
    assert all(math.isfinite(zone.resistance_m2k_w) for zone in zones)
    assert [zone.name for zone in zones] == sorted(zone.name for zone in zones)


@settings(max_examples=100, deadline=None)
@given(
    length=FINITE_POSITIVE,
    width=FINITE_POSITIVE,
    sides=EXTERIOR_SIDES,
    insulation=st.floats(
        min_value=0.001,
        max_value=50,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_ground_insulation_strictly_reduces_zone_u_values(
    length: float,
    width: float,
    sides: tuple[str, ...],
    insulation: float,
) -> None:
    base = ground_floor_zones(length, width, exterior_sides=sides)
    insulated = ground_floor_zones(
        length,
        width,
        insulation_resistance_m2k_w=insulation,
        exterior_sides=sides,
    )

    assert [zone.area_m2 for zone in insulated] == pytest.approx(
        [zone.area_m2 for zone in base]
    )
    assert all(
        1 / improved.resistance_m2k_w < 1 / original.resistance_m2k_w
        for original, improved in zip(base, insulated, strict=True)
    )


@settings(max_examples=150, deadline=None)
@given(
    indoor=st.floats(min_value=-29, max_value=50, allow_nan=False, allow_infinity=False),
    temperature_gap=st.floats(
        min_value=0.1,
        max_value=50,
        allow_nan=False,
        allow_infinity=False,
    ),
    area=st.floats(min_value=0.01, max_value=100_000, allow_nan=False, allow_infinity=False),
    thickness=st.floats(min_value=0.001, max_value=2, allow_nan=False, allow_infinity=False),
    conductivity=st.floats(
        min_value=0.005,
        max_value=5,
        allow_nan=False,
        allow_infinity=False,
    ),
    volume=st.floats(min_value=1, max_value=10_000_000, allow_nan=False, allow_infinity=False),
    mechanical=st.floats(
        min_value=0,
        max_value=1_000_000,
        allow_nan=False,
        allow_infinity=False,
    ),
    natural=st.floats(
        min_value=0,
        max_value=1_000_000,
        allow_nan=False,
        allow_infinity=False,
    ),
    infiltration=st.floats(
        min_value=0,
        max_value=1_000_000,
        allow_nan=False,
        allow_infinity=False,
    ),
    recovery=st.floats(min_value=0, max_value=0.95, allow_nan=False, allow_infinity=False),
    safety=st.floats(min_value=1, max_value=1.5, allow_nan=False, allow_infinity=False),
)
def test_valid_heat_loss_inputs_always_produce_finite_nonnegative_balances(
    indoor: float,
    temperature_gap: float,
    area: float,
    thickness: float,
    conductivity: float,
    volume: float,
    mechanical: float,
    natural: float,
    infiltration: float,
    recovery: float,
    safety: float,
) -> None:
    outdoor = max(-80.0, indoor - temperature_gap)
    building = Building(
        indoor_temperature_c=indoor,
        outdoor_temperature_c=outdoor,
        volume_m3=volume,
        opaque_surfaces=(
            OpaqueSurface(
                "Property wall",
                area,
                (Layer("passport", thickness, conductivity_w_mk=conductivity),),
                boundary=Boundary.OUTDOOR,
            ),
        ),
        airflow=Airflow(
            mechanical_m3_h=mechanical,
            natural_m3_h=natural,
            infiltration_m3_h=infiltration,
            heat_recovery_efficiency=recovery,
        ),
        safety_factor=safety,
    )
    result = calculate_heat_loss(building)

    values = (
        result.transmission_w,
        result.ventilation_w,
        result.total_w,
        result.recommended_w,
        *(line.watts for line in result.lines),
    )
    assert all(math.isfinite(value) and value >= 0 for value in values)
    assert result.total_w == pytest.approx(
        result.transmission_w + result.ventilation_w
    )
    assert result.total_w == pytest.approx(sum(line.watts for line in result.lines))
    assert result.recommended_w == pytest.approx(result.total_w * safety)
