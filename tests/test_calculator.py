import unittest
from dataclasses import replace
from itertools import combinations
from math import isfinite

from u_calc.calculator import (
    appendix8_air_specific_weight_n_m3,
    appendix8_infiltration_mass_flow,
    appendix8_pressure_difference_pa,
    calculate_climate_scenarios,
    calculate_heat_loss,
    ground_floor_zones,
    u_value,
)
from u_calc.catalog import CLIMATES
from u_calc.models import (
    Airflow,
    Appendix8PressureInput,
    Boundary,
    Building,
    InfiltrationPath,
    Layer,
    LinearThermalBridge,
    OpaqueSurface,
    Opening,
    Orientation,
    SurfaceKind,
)


class CalculatorTests(unittest.TestCase):
    def test_appendix8_formula_four_and_five_match_official_expression(self) -> None:
        inputs = Appendix8PressureInput(
            building_height_m=12,
            opening_height_m=8,
            indoor_temperature_c=24,
            outdoor_temperature_c=-15,
            outdoor_air_density_kg_m3=1.3,
            wind_speed_m_s=5,
            windward_coefficient=0.8,
            leeward_coefficient=-0.6,
            height_factor=1,
            internal_pressure_pa=2,
        )
        expected = (
            (12 - 8) * (3463 / (273 + 24) - 3463 / (273 - 15))
            + 0.5 * 1.3 * 5**2 * (0.8 - (-0.6))
            - 2
        )
        self.assertAlmostEqual(appendix8_pressure_difference_pa(inputs), expected)
        self.assertAlmostEqual(appendix8_air_specific_weight_n_m3(-15), 3463 / 258)

    def test_appendix8_formula_three_matches_official_expression(self) -> None:
        path = InfiltrationPath(
            pressure_pa=12,
            first_floor_pressure_pa=10,
            opening_area_m2=20,
            air_permeability_resistance_m2_h_pa_kg=0.5,
            envelope_area_m2=100,
            normative_air_permeability_kg_m2_h=0.2,
            gap_area_m2=0.01,
            panel_joint_length_m=25,
        )
        expected = (
            0.216 * 20 * 12**0.67 / 0.5
            + 100 * 0.2 * (12 / 10) ** 0.67
            + 3456 * 0.01 * 12**0.5
            + 0.5 * 25 * (12 / 10)
        )
        self.assertAlmostEqual(appendix8_infiltration_mass_flow((path,)), expected)

    def test_appendix8_envelope_uses_larger_of_formula_one_and_two(self) -> None:
        path = InfiltrationPath(
            pressure_pa=10,
            first_floor_pressure_pa=10,
            envelope_area_m2=1,
            normative_air_permeability_kg_m2_h=1,
        )
        building = Building(
            indoor_temperature_c=24,
            outdoor_temperature_c=-6,
            volume_m3=200,
            opaque_surfaces=(),
            airflow=Airflow(
                infiltration_m3_h=90,
                infiltration_basis="appendix8_envelope",
                infiltration_paths=(path,),
            ),
            safety_factor=1,
        )
        result = calculate_heat_loss(building)
        density = 353 / (273 + 24)
        self.assertAlmostEqual(result.ventilation_w, 0.28 * 90 * density * 30)

        formula_three_building = replace(
            building,
            airflow=Airflow(
                infiltration_m3_h=0,
                infiltration_basis="appendix8_envelope",
                infiltration_paths=(
                    InfiltrationPath(
                        pressure_pa=10,
                        first_floor_pressure_pa=10,
                        gap_area_m2=0.1,
                    ),
                ),
            ),
        )
        formula_three = calculate_heat_loss(formula_three_building)
        self.assertAlmostEqual(formula_three.ventilation_w, 0.28 * 3456 * 0.1 * 10**0.5 * 30)

    def test_recovery_never_reduces_infiltration(self) -> None:
        common = dict(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=100,
            opaque_surfaces=(),
            safety_factor=1,
        )
        without_recovery = calculate_heat_loss(
            Building(
                airflow=Airflow(mechanical_m3_h=100, infiltration_m3_h=40),
                **common,
            )
        )
        with_recovery = calculate_heat_loss(
            Building(
                airflow=Airflow(
                    mechanical_m3_h=100,
                    infiltration_m3_h=40,
                    heat_recovery_efficiency=0.8,
                ),
                **common,
            )
        )
        infiltration_without = next(
            line for line in without_recovery.lines if line.kind == "Инфильтрация"
        )
        infiltration_with = next(
            line for line in with_recovery.lines if line.kind == "Инфильтрация"
        )
        self.assertEqual(infiltration_with.watts, infiltration_without.watts)
        self.assertAlmostEqual(infiltration_with.watts, 0.33 * 40 * 30)

    def test_zero_recovery_equals_sum_of_all_airflows(self) -> None:
        building = Building(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=100,
            opaque_surfaces=(),
            airflow=Airflow(
                mechanical_m3_h=100,
                natural_m3_h=20,
                infiltration_m3_h=40,
            ),
            safety_factor=1,
        )
        result = calculate_heat_loss(building)
        self.assertAlmostEqual(result.ventilation_w, 0.33 * (100 + 20 + 40) * 30)

    def test_legacy_combined_ach_never_receives_heat_recovery(self) -> None:
        building = Building(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=100,
            opaque_surfaces=(),
            air_changes_per_hour=0.5,
            heat_recovery_efficiency=0.8,
            safety_factor=1,
        )

        result = calculate_heat_loss(building)

        self.assertAlmostEqual(result.ventilation_w, 0.33 * 0.5 * 100 * 30)
        mechanical = next(line for line in result.lines if line.name == "Механическая вентиляция")
        natural = next(line for line in result.lines if line.name == "Естественная вентиляция")
        self.assertEqual(mechanical.watts, 0)
        self.assertAlmostEqual(natural.watts, result.ventilation_w)

    def test_eighty_percent_recovery_reduces_only_mechanical_flow(self) -> None:
        building = Building(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=100,
            opaque_surfaces=(),
            airflow=Airflow(
                mechanical_m3_h=100,
                natural_m3_h=20,
                infiltration_m3_h=40,
                heat_recovery_efficiency=0.8,
            ),
            safety_factor=1,
        )
        result = calculate_heat_loss(building)
        expected = 0.33 * (100 * 0.2 + 20 + 40) * 30
        self.assertAlmostEqual(result.ventilation_w, expected)

    def test_zero_airflow_component_is_reported_without_error(self) -> None:
        building = Building(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=100,
            opaque_surfaces=(),
            airflow=Airflow(mechanical_m3_h=0, infiltration_m3_h=30),
            safety_factor=1,
        )
        result = calculate_heat_loss(building)
        mechanical = next(line for line in result.lines if line.name == "Механическая вентиляция")
        self.assertEqual(mechanical.watts, 0)
        self.assertAlmostEqual(result.ventilation_w, 0.33 * 30 * 30)

    def test_appendix8_residential_infiltration_uses_formula_two(self) -> None:
        building = Building(
            indoor_temperature_c=24,
            outdoor_temperature_c=-6,
            volume_m3=200,
            opaque_surfaces=(),
            airflow=Airflow(
                infiltration_m3_h=90,
                infiltration_basis="appendix8_residential_exhaust",
            ),
            safety_factor=1,
        )
        result = calculate_heat_loss(building)
        density = 353 / (273 + 24)
        expected = 0.28 * 90 * density * 30
        infiltration = next(line for line in result.lines if line.kind == "Инфильтрация")
        self.assertAlmostEqual(infiltration.watts, expected)
        self.assertAlmostEqual(result.ventilation_w, expected)

    def test_unknown_infiltration_basis_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "способ задания инфильтрации"):
            Airflow(infiltration_basis="n50-magic")

    def test_ground_floor_zones_count_exterior_corners_twice(self) -> None:
        zones = ground_floor_zones(30, 20)
        # Appendix 9 uses 2 m strips parallel to every exterior wall. The four
        # 2x2 m corner intersections belong to both adjoining strips (16 m² extra).
        self.assertEqual([zone.area_m2 for zone in zones], [200, 152, 120, 144])
        self.assertEqual(sum(zone.area_m2 for zone in zones), 616)
        self.assertEqual([zone.resistance_m2k_w for zone in zones], [2.1, 4.3, 8.5, 14.2])

    def test_ground_floor_golden_rectangle_10_by_8(self) -> None:
        zones = ground_floor_zones(10, 8)
        self.assertEqual([zone.area_m2 for zone in zones], [72, 24])
        self.assertEqual([zone.resistance_m2k_w for zone in zones], [2.1, 4.3])

    def test_ground_floor_golden_narrow_rectangle_under_four_metres(self) -> None:
        zones = ground_floor_zones(10, 3)
        self.assertEqual([zone.area_m2 for zone in zones], [39])

    def test_ground_floor_golden_small_rectangle_under_four_by_four(self) -> None:
        zones = ground_floor_zones(3, 3)
        self.assertEqual([zone.area_m2 for zone in zones], [18])

    def test_ground_floor_golden_long_narrow_rectangle(self) -> None:
        zones = ground_floor_zones(30, 2)
        self.assertEqual([zone.area_m2 for zone in zones], [64])

    def test_ground_floor_golden_one_exterior_side(self) -> None:
        zones = ground_floor_zones(10, 8, exterior_sides=("north",))
        self.assertEqual([zone.area_m2 for zone in zones], [20, 20, 20, 20])
        self.assertEqual(sum(zone.area_m2 for zone in zones), 80)

    def test_ground_floor_golden_two_adjacent_exterior_sides(self) -> None:
        zones = ground_floor_zones(10, 8, exterior_sides=("north", "west"))
        self.assertEqual([zone.area_m2 for zone in zones], [36, 24, 16, 8])
        self.assertEqual(sum(zone.area_m2 for zone in zones), 84)

    def test_ground_floor_golden_two_opposite_exterior_sides(self) -> None:
        zones = ground_floor_zones(10, 8, exterior_sides=("north", "south"))
        self.assertEqual([zone.area_m2 for zone in zones], [40, 40])

    def test_ground_floor_golden_insulated_and_on_joists(self) -> None:
        zones = ground_floor_zones(
            10,
            8,
            insulation_resistance_m2k_w=2.5,
            floor_on_joists=True,
        )
        self.assertEqual([zone.area_m2 for zone in zones], [72, 24])
        self.assertEqual(
            [zone.resistance_m2k_w for zone in zones],
            [(2.1 + 2.5) * 1.18, (4.3 + 2.5) * 1.18],
        )

    def test_ground_floor_rejects_unknown_or_duplicate_sides(self) -> None:
        with self.assertRaisesRegex(ValueError, "Неизвестная"):
            ground_floor_zones(10, 8, exterior_sides=("roof",))
        with self.assertRaisesRegex(ValueError, "неповторяющиеся"):
            ground_floor_zones(10, 8, exterior_sides=("north", "north"))

    def test_ground_geometry_properties_for_all_exterior_side_combinations(self) -> None:
        sides = ("north", "east", "south", "west")
        for length, width in ((0.5, 0.5), (3.9, 2.1), (10, 8), (100, 1.5)):
            corner_side = min(2.0, length / 2, width / 2)
            for count in range(1, 5):
                for selected in combinations(sides, count):
                    with self.subTest(length=length, width=width, selected=selected):
                        zones = ground_floor_zones(length, width, exterior_sides=selected)
                        adjacent = sum(
                            {first, second} <= set(selected)
                            for first, second in (
                                ("north", "east"),
                                ("east", "south"),
                                ("south", "west"),
                                ("west", "north"),
                            )
                        )
                        expected = length * width + adjacent * corner_side**2
                        self.assertAlmostEqual(sum(zone.area_m2 for zone in zones), expected)
                        self.assertTrue(
                            all(
                                zone.area_m2 > 0
                                and isfinite(zone.area_m2)
                                and zone.resistance_m2k_w > 0
                                for zone in zones
                            )
                        )

    def test_small_ground_floor_omits_empty_inner_zone(self) -> None:
        zones = ground_floor_zones(20, 10)
        self.assertEqual([zone.area_m2 for zone in zones], [120, 72, 24])
        self.assertEqual(sum(zone.area_m2 for zone in zones), 216)

    def test_ground_floor_loss_uses_area_delta_t_over_resistance(self) -> None:
        zones = ground_floor_zones(10, 8)
        building = Building(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=240,
            opaque_surfaces=(),
            ground_floor_zones=zones,
            air_changes_per_hour=0,
            safety_factor=1,
        )
        result = calculate_heat_loss(building)
        expected = sum(zone.area_m2 * 30 / zone.resistance_m2k_w for zone in zones)
        self.assertAlmostEqual(result.transmission_w, expected)
        ground_lines = [line for line in result.lines if line.kind == "Пол по грунту"]
        self.assertEqual(len(ground_lines), len(zones))

    def test_ground_floor_insulation_reduces_loss(self) -> None:
        common = dict(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=240,
            opaque_surfaces=(),
            air_changes_per_hour=0,
            safety_factor=1,
        )
        bare = calculate_heat_loss(Building(ground_floor_zones=ground_floor_zones(10, 8), **common))
        insulated = calculate_heat_loss(
            Building(ground_floor_zones=ground_floor_zones(10, 8, 2.5), **common)
        )
        self.assertLess(insulated.total_w, bare.total_w)

    def test_wall_u_value_uses_all_layers(self) -> None:
        bare = OpaqueSurface("Стена", 10, (Layer("brick_solid", 0.25),))
        insulated = OpaqueSurface(
            "Стена", 10, (Layer("brick_solid", 0.25), Layer("mineral_wool", 0.05))
        )
        self.assertLess(u_value(insulated), u_value(bare))
        # R = Rsi + 0.25 / 0.81 + 0.05 / 0.05 + Rse for catalog λБ values.
        self.assertAlmostEqual(u_value(insulated), 0.6762962344)

    def test_custom_passport_conductivity_overrides_catalog(self) -> None:
        custom = OpaqueSurface("Стена", 10, (Layer("custom", 0.30, 0.10),))
        expected = 1 / (0.13 + 0.30 / 0.10 + 0.04)
        self.assertAlmostEqual(u_value(custom), expected)

    def test_heat_loss_formula_and_safety_factor(self) -> None:
        building = Building(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=100,
            opaque_surfaces=(OpaqueSurface("Стена", 20, (Layer("aerated_d500", 0.30),)),),
            openings=(Opening("Окно", 2, 1.0),),
            air_changes_per_hour=0.5,
            safety_factor=1.1,
        )
        result = calculate_heat_loss(building)
        expected_wall = u_value(building.opaque_surfaces[0]) * 20 * 30
        self.assertAlmostEqual(result.transmission_w, expected_wall + 60)
        self.assertAlmostEqual(result.ventilation_w, 495)
        self.assertAlmostEqual(result.recommended_w, result.total_w * 1.1)

    def test_heated_neighbor_has_no_loss_by_default(self) -> None:
        building = Building(
            indoor_temperature_c=24,
            outdoor_temperature_c=-15,
            volume_m3=200,
            opaque_surfaces=(OpaqueSurface("Потолок", 80, (), Boundary.HEATED),),
            air_changes_per_hour=0,
        )
        self.assertEqual(calculate_heat_loss(building).total_w, 0)

    def test_unheated_boundary_uses_reduction_factor_and_internal_surface_films(self) -> None:
        outdoor = OpaqueSurface(
            "Пол",
            50,
            (Layer("concrete", 0.2),),
            Boundary.OUTDOOR,
            kind=SurfaceKind.FLOOR,
        )
        basement = OpaqueSurface(
            "Пол",
            50,
            (Layer("concrete", 0.2),),
            Boundary.UNHEATED,
            kind=SurfaceKind.FLOOR,
        )
        common = dict(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=100,
            air_changes_per_hour=0,
        )
        q_basement = calculate_heat_loss(Building(opaque_surfaces=(basement,), **common)).total_w
        self.assertAlmostEqual(q_basement, u_value(basement) * 50 * 30 * 0.7)
        self.assertLess(u_value(basement), u_value(outdoor))

    def test_known_adjacent_temperature_replaces_boundary_factor(self) -> None:
        basement = OpaqueSurface(
            "Пол",
            50,
            (Layer("concrete", 0.2),),
            Boundary.UNHEATED,
            adjacent_temperature_c=5,
            kind=SurfaceKind.FLOOR,
        )
        building = Building(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=100,
            opaque_surfaces=(basement,),
            air_changes_per_hour=0,
        )
        result = calculate_heat_loss(building)
        self.assertEqual(result.lines[0].delta_t_k, 15)
        self.assertAlmostEqual(result.total_w, u_value(basement) * 50 * 15)

    def test_climate_scenario_loads_increase_as_weather_gets_colder(self) -> None:
        building = Building(
            indoor_temperature_c=24,
            outdoor_temperature_c=-14,
            volume_m3=100,
            opaque_surfaces=(OpaqueSurface("Стена", 30, (Layer("aerated_d500", 0.30),)),),
        )
        climate = replace(CLIMATES["tashkent"], design_c=-14)
        results = calculate_climate_scenarios(building, climate)
        loads = [results[key].recommended_kw for key in ("economy", "design", "future", "extreme")]
        self.assertEqual(loads, sorted(loads))

    def test_thermal_bridge_correction_is_separate_from_safety_factor(self) -> None:
        surface = OpaqueSurface("Стена", 20, (Layer("aerated_d500", 0.30),))
        base = Building(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=100,
            opaque_surfaces=(surface,),
            air_changes_per_hour=0,
            safety_factor=1,
        )
        corrected = Building(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=100,
            opaque_surfaces=(surface,),
            air_changes_per_hour=0,
            thermal_bridge_factor=0.10,
            safety_factor=1,
        )
        base_result = calculate_heat_loss(base)
        corrected_result = calculate_heat_loss(corrected)
        self.assertAlmostEqual(corrected_result.total_w, base_result.total_w * 1.10)
        self.assertTrue(
            any(line.name == "Мостики холода (оценка)" for line in corrected_result.lines)
        )

    def test_exact_linear_thermal_bridge_uses_psi_length_delta_t(self) -> None:
        building = Building(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=100,
            opaque_surfaces=(OpaqueSurface("Стена", 20, (Layer("aerated_d500", 0.30),)),),
            linear_thermal_bridges=(LinearThermalBridge("Балкон", 5, 0.3),),
            air_changes_per_hour=0,
            safety_factor=1,
        )
        result = calculate_heat_loss(building)
        bridge = next(line for line in result.lines if line.kind == "Линейный мостик")
        self.assertAlmostEqual(bridge.watts, 0.3 * 5 * 30)

    def test_percentage_and_exact_bridges_cannot_be_combined(self) -> None:
        with self.assertRaisesRegex(ValueError, "одновременно"):
            Building(
                indoor_temperature_c=20,
                outdoor_temperature_c=-10,
                volume_m3=100,
                opaque_surfaces=(),
                thermal_bridge_factor=0.1,
                linear_thermal_bridges=(LinearThermalBridge("Балкон", 5, 0.3),),
            )

    def test_normative_beta_and_position_factors_multiply_basic_transmission(self) -> None:
        base = OpaqueSurface("Стена", 20, (Layer("aerated_d500", 0.30),))
        factored = OpaqueSurface(
            "Стена",
            20,
            (Layer("aerated_d500", 0.30),),
            additional_heat_loss_factor=0.1,
            position_factor=0.9,
        )
        common = dict(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=100,
            air_changes_per_hour=0,
            safety_factor=1,
        )
        base_loss = calculate_heat_loss(Building(opaque_surfaces=(base,), **common)).total_w
        factored_loss = calculate_heat_loss(Building(opaque_surfaces=(factored,), **common)).total_w
        self.assertAlmostEqual(factored_loss, base_loss * 1.1 * 0.9)

    def test_orientation_factors_match_shnq_appendix_9_clause_2(self) -> None:
        from u_calc.calculator import orientation_heat_loss_factor

        expected = {
            Orientation.NORTH: 0.10,
            Orientation.NORTH_EAST: 0.10,
            Orientation.EAST: 0.10,
            Orientation.SOUTH_EAST: 0.05,
            Orientation.SOUTH: 0.0,
            Orientation.SOUTH_WEST: 0.0,
            Orientation.WEST: 0.05,
            Orientation.NORTH_WEST: 0.10,
        }
        self.assertEqual(
            {orientation: orientation_heat_loss_factor(orientation) for orientation in expected},
            expected,
        )
        self.assertEqual(orientation_heat_loss_factor(None), 0.0)


if __name__ == "__main__":
    unittest.main()
