import unittest

from u_calc.services.building_factory import (
    InvalidCalculationData,
    build_from_answers,
    climate_from_answers,
)

_build_from_answers = build_from_answers
_climate_from_answers = climate_from_answers


class BotMappingTests(unittest.TestCase):
    def test_complex_ground_plan_is_explicitly_rejected(self) -> None:
        data = {
            "wall_material": "brick_solid",
            "wall_thickness": 0.25,
            "wall_gross_area": 60,
            "window_area": 0,
            "door_area": 0,
            "length": 10,
            "width": 8,
            "floor_boundary": "ground",
            "floor_ground_method": "zonal",
            "ground_plan_shape": "complex",
            "ceiling_boundary": "heated",
            "indoor": 24,
            "outdoor": -14,
            "volume": 240,
        }
        with self.assertRaisesRegex(InvalidCalculationData, "только прямоугольный"):
            _build_from_answers(data)

    def test_normative_ground_floor_uses_zones_and_explicit_insulation(self) -> None:
        building = _build_from_answers(
            {
                "wall_material": "brick_solid",
                "wall_thickness": 0.25,
                "insulation_material": None,
                "insulation_thickness": 0,
                "wall_gross_area": 60,
                "window_count": 0,
                "window_area": 0,
                "window_type": "double",
                "door_area": 0,
                "length": 10,
                "width": 8,
                "floor_boundary": "ground",
                "floor_ground_method": "zonal",
                "floor_material": "concrete",
                "floor_thickness": 0.18,
                "floor_insulation_material": "xps",
                "floor_insulation_thickness": 0.08,
                "ceiling_boundary": "heated",
                "indoor": 24,
                "outdoor": -14,
                "volume": 240,
                "air_changes": 0.5,
            }
        )
        # 80 m² geometric area + four 2x2 m exterior-corner areas counted twice.
        self.assertEqual(sum(zone.area_m2 for zone in building.ground_floor_zones), 96)
        self.assertEqual(len(building.opaque_surfaces), 2)  # wall and heated ceiling
        self.assertAlmostEqual(
            building.ground_floor_zones[0].resistance_m2k_w,
            2.1 + 0.08 / 0.034,
        )
        self.assertTrue(any("ШНҚ 2.04.05-22" in item for item in building.assumptions))
        self.assertFalse(any("50%" in item for item in building.assumptions))

    def test_custom_city_answers_create_full_climate_profile(self) -> None:
        profile = _climate_from_answers(
            {
                "climate_key": "custom",
                "custom_city_name": "Бишкек",
                "custom_cold_mean": -3.0,
                "custom_design": -23.0,
                "custom_extreme": -34.0,
                "custom_hot_mean": 25.0,
                "custom_hot_max": 42.0,
            }
        )
        self.assertIsNotNone(profile)
        self.assertEqual(profile.name, "Бишкек")
        self.assertEqual(profile.outdoor_temperature("future"), -25)

    def test_answers_create_net_wall_area_and_heated_neighbors(self) -> None:
        building = _build_from_answers(
            {
                "wall_material": "brick_solid",
                "wall_thickness": 0.25,
                "insulation_material": "mineral_wool",
                "insulation_thickness": 0.05,
                "wall_gross_area": 100,
                "window_area": 12,
                "window_type": "double",
                "door_area": 3,
                "length": 10,
                "width": 8,
                "floor_boundary": "heated",
                "floor_insulation": 0,
                "ceiling_boundary": "heated",
                "ceiling_insulation": 0,
                "indoor": 24,
                "outdoor": -15,
                "volume": 240,
                "air_changes": 0.5,
            }
        )
        self.assertEqual(building.opaque_surfaces[0].area_m2, 85)
        self.assertEqual(len(building.opaque_surfaces[0].layers), 2)
        self.assertEqual(len(building.openings), 2)
        self.assertEqual(building.opaque_surfaces[1].boundary, "heated")

    def test_simple_flow_passport_lambdas_reach_all_layers(self) -> None:
        building = _build_from_answers(
            {
                "wall_material": "custom",
                "wall_conductivity": 0.11,
                "wall_thickness": 0.30,
                "insulation_material": "custom",
                "insulation_conductivity": 0.036,
                "insulation_thickness": 0.08,
                "wall_gross_area": 50,
                "window_count": 0,
                "window_area": 0,
                "window_type": "double",
                "door_area": 0,
                "length": 8,
                "width": 6,
                "floor_boundary": "ground",
                "floor_material": "custom",
                "floor_conductivity": 1.4,
                "floor_thickness": 0.18,
                "floor_insulation_material": "custom",
                "floor_insulation_conductivity": 0.032,
                "floor_insulation_thickness": 0.10,
                "ceiling_boundary": "heated",
                "indoor": 24,
                "outdoor": -14,
                "volume": 144,
                "air_changes": 0.5,
            }
        )
        wall = building.opaque_surfaces[0]
        floor = building.opaque_surfaces[1]
        self.assertEqual([layer.conductivity_w_mk for layer in wall.layers], [0.11, 0.036])
        self.assertEqual([layer.conductivity_w_mk for layer in floor.layers], [1.4, 0.032])

    def test_known_basement_and_attic_temperatures_reach_surfaces(self) -> None:
        building = _build_from_answers(
            {
                "wall_material": "brick_solid",
                "wall_thickness": 0.25,
                "insulation_material": None,
                "insulation_thickness": 0,
                "wall_gross_area": 50,
                "window_count": 0,
                "window_area": 0,
                "window_type": "double",
                "door_area": 0,
                "length": 8,
                "width": 6,
                "floor_boundary": "unheated",
                "floor_adjacent_temperature": 5,
                "floor_material": "concrete",
                "floor_thickness": 0.18,
                "floor_insulation_material": None,
                "floor_insulation_thickness": 0,
                "ceiling_boundary": "unheated",
                "ceiling_adjacent_temperature": 2,
                "ceiling_material": "wood",
                "ceiling_thickness": 0.05,
                "ceiling_insulation_material": "mineral_wool",
                "ceiling_insulation_thickness": 0.15,
                "indoor": 24,
                "outdoor": -14,
                "volume": 144,
                "air_changes": 0.5,
            }
        )
        self.assertEqual(building.opaque_surfaces[1].adjacent_temperature_c, 5)
        self.assertEqual(building.opaque_surfaces[2].adjacent_temperature_c, 2)
        self.assertFalse(any("70%" in assumption for assumption in building.assumptions))

    def test_selected_floor_and_roof_layers_and_window_count_are_preserved(self) -> None:
        building = _build_from_answers(
            {
                "wall_material": "aerated_d500",
                "wall_thickness": 0.30,
                "insulation_material": None,
                "insulation_thickness": 0,
                "wall_gross_area": 80,
                "window_count": 4,
                "window_area": 8,
                "window_type": "triple",
                "door_area": 0,
                "length": 8,
                "width": 6,
                "floor_boundary": "ground",
                "floor_material": "concrete",
                "floor_thickness": 0.18,
                "floor_insulation_material": "xps",
                "floor_insulation_thickness": 0.08,
                "ceiling_boundary": "unheated",
                "ceiling_material": "wood",
                "ceiling_thickness": 0.04,
                "ceiling_insulation_material": "mineral_wool",
                "ceiling_insulation_thickness": 0.15,
                "indoor": 24,
                "outdoor": -14,
                "volume": 144,
                "air_changes": 0.5,
            }
        )
        self.assertEqual(
            [layer.material_key for layer in building.opaque_surfaces[1].layers],
            ["concrete", "xps"],
        )
        self.assertEqual(
            [layer.material_key for layer in building.opaque_surfaces[2].layers],
            ["wood", "mineral_wool"],
        )
        self.assertEqual(building.openings[0].name, "Окна (4 шт.)")

    def test_different_wall_groups_keep_individual_constructions(self) -> None:
        data = {
            "wall_groups": [
                {
                    "name": "Север",
                    "gross_area_m2": 30,
                    "material": "brick_solid",
                    "thickness_m": 0.25,
                    "insulation_material": "mineral_wool",
                    "insulation_thickness_m": 0.05,
                },
                {
                    "name": "Торец",
                    "gross_area_m2": 20,
                    "material": "aerated_d500",
                    "thickness_m": 0.30,
                    "insulation_material": None,
                    "insulation_thickness_m": 0,
                },
            ],
            "wall_gross_area": 50,
            "window_count": 2,
            "window_area": 8,
            "window_type": "double",
            "door_area": 2,
            "length": 8,
            "width": 6,
            "floor_boundary": "heated",
            "ceiling_boundary": "heated",
            "indoor": 24,
            "outdoor": -14,
            "volume": 144,
            "air_changes": 0.5,
        }
        building = _build_from_answers(data)
        walls = building.opaque_surfaces[:2]
        self.assertEqual([wall.name for wall in walls], ["Стена: Север", "Стена: Торец"])
        self.assertAlmostEqual(sum(wall.area_m2 for wall in walls), 40)
        self.assertNotEqual(walls[0].layers, walls[1].layers)

    def test_window_groups_are_deducted_from_their_selected_walls(self) -> None:
        data = {
            "wall_groups": [
                {
                    "name": "Север",
                    "gross_area_m2": 30,
                    "material": "brick_solid",
                    "thickness_m": 0.25,
                    "insulation_material": None,
                    "insulation_thickness_m": 0,
                },
                {
                    "name": "Торец",
                    "gross_area_m2": 20,
                    "material": "aerated_d500",
                    "thickness_m": 0.30,
                    "insulation_material": None,
                    "insulation_thickness_m": 0,
                },
            ],
            "wall_gross_area": 50,
            "window_count": 2,
            "window_area": 6,
            "window_type": None,
            "window_groups": [
                {
                    "name": "Северные окна",
                    "count": 2,
                    "width_m": 1.5,
                    "height_m": 2,
                    "area_m2": 6,
                    "u_value": 1.1,
                    "wall_name": "Север",
                }
            ],
            "door_area": 0,
            "length": 8,
            "width": 6,
            "floor_boundary": "heated",
            "ceiling_boundary": "heated",
            "indoor": 24,
            "outdoor": -14,
            "volume": 144,
            "air_changes": 0.5,
        }
        building = _build_from_answers(data)
        walls = building.opaque_surfaces[:2]
        self.assertEqual(walls[0].area_m2, 24)
        self.assertEqual(walls[1].area_m2, 20)
        self.assertEqual(building.openings[0].u_value, 1.1)
        self.assertEqual(building.openings[0].name, "Северные окна (2 шт.)")
        self.assertFalse(building.assumptions)


if __name__ == "__main__":
    unittest.main()
