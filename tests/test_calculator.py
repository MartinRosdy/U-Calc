import unittest

from u_calc.calculator import (
    calculate_climate_scenarios,
    calculate_heat_loss,
    ground_floor_zones,
    u_value,
)
from u_calc.catalog import CLIMATES
from u_calc.models import (
    Boundary,
    Building,
    Layer,
    LinearThermalBridge,
    OpaqueSurface,
    Opening,
    SurfaceKind,
)


class CalculatorTests(unittest.TestCase):
    def test_ground_floor_zones_count_exterior_corners_twice(self) -> None:
        zones = ground_floor_zones(30, 20)
        # Appendix 9 uses 2 m strips parallel to every exterior wall. The four
        # 2x2 m corner intersections belong to both adjoining strips (16 m² extra).
        self.assertEqual([zone.area_m2 for zone in zones], [200, 152, 120, 144])
        self.assertEqual(sum(zone.area_m2 for zone in zones), 616)
        self.assertEqual([zone.resistance_m2k_w for zone in zones], [2.1, 4.3, 8.5, 14.2])

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
        self.assertAlmostEqual(u_value(insulated), 0.579, delta=0.006)

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
        results = calculate_climate_scenarios(building, CLIMATES["tashkent"])
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


if __name__ == "__main__":
    unittest.main()
