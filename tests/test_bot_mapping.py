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
            2.1 + 0.08 / 0.032,
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
                "custom_climate_source": "Кыргызгидромет, 1991–2020",
            }
        )
        self.assertIsNotNone(profile)
        self.assertEqual(profile.name, "Бишкек")
        self.assertEqual(profile.outdoor_temperature("future"), -25)
        self.assertEqual(len(profile.provenance), 5)
        self.assertTrue(
            all(item.status == "user_supplied_unverified" for item in profile.provenance)
        )
        self.assertTrue(all("Кыргызгидромет" in item.document for item in profile.provenance))

    def test_user_confirmed_design_temperature_is_not_mislabelled_as_normative(self) -> None:
        profile = _climate_from_answers(
            {
                "climate_key": "tashkent",
                "confirmed_design_c": -14.0,
                "confirmed_design_source": "Проект ОВ, лист 3",
            }
        )
        design_source = profile.provenance[-1]
        self.assertEqual(
            sum(item.parameter == "design_c" for item in profile.provenance),
            1,
        )
        self.assertEqual(design_source.parameter, "design_c")
        self.assertEqual(design_source.document, "Проект ОВ, лист 3")
        self.assertEqual(design_source.status, "user_supplied_unverified")
        self.assertIn("определение параметра Б", design_source.location)
        self.assertIn("ШНҚ 2.01.18-24, п. 16", design_source.location)
        self.assertIn("пятидневка 0,92", profile.source_note)

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

    def test_advanced_floor_and_roof_keep_every_explicit_layer(self) -> None:
        building = _build_from_answers(
            {
                "wall_material": "brick_solid",
                "wall_thickness": 0.25,
                "wall_gross_area": 50,
                "window_area": 0,
                "door_area": 0,
                "length": 8,
                "width": 6,
                "floor_boundary": "unheated",
                "floor_layers": [
                    {"material": "concrete", "thickness_m": 0.18},
                    {"material": "xps", "thickness_m": 0.08},
                    {"material": "wood", "thickness_m": 0.02},
                ],
                "ceiling_boundary": "outdoor",
                "ceiling_layers": [
                    {"material": "wood", "thickness_m": 0.04},
                    {
                        "material": "custom",
                        "material_conductivity": 0.033,
                        "thickness_m": 0.2,
                    },
                ],
                "indoor": 24,
                "outdoor": -14,
                "volume": 144,
                "air_changes": 0.5,
            }
        )
        floor, roof = building.opaque_surfaces[1:]
        self.assertEqual(
            [layer.material_key for layer in floor.layers],
            ["concrete", "xps", "wood"],
        )
        self.assertEqual([layer.material_key for layer in roof.layers], ["wood", "custom"])
        self.assertAlmostEqual(roof.layers[1].conductivity_w_mk, 0.033)

    def test_appendix8_infiltration_basis_reaches_model_and_assumptions(self) -> None:
        building = _build_from_answers(
            {
                "wall_material": "brick_solid",
                "wall_thickness": 0.25,
                "wall_gross_area": 50,
                "window_area": 0,
                "door_area": 0,
                "length": 8,
                "width": 6,
                "floor_boundary": "heated",
                "ceiling_boundary": "heated",
                "indoor": 24,
                "outdoor": -14,
                "volume": 144,
                "airflow_input_basis": "components_m3h",
                "mechanical_ventilation_m3_h": 0,
                "natural_ventilation_m3_h": 0,
                "infiltration_m3_h": 90,
                "infiltration_basis": "appendix8_residential_exhaust",
            }
        )
        self.assertEqual(
            building.airflow.infiltration_basis,
            "appendix8_residential_exhaust",
        )
        self.assertEqual(building.airflow.input_basis, "components_m3_h")
        self.assertTrue(any("формуле 2 приложения 8" in item for item in building.assumptions))

    def test_appendix8_envelope_paths_reach_domain_model(self) -> None:
        building = _build_from_answers(
            {
                "wall_material": "brick_solid",
                "wall_thickness": 0.25,
                "wall_gross_area": 50,
                "window_area": 0,
                "door_area": 0,
                "length": 8,
                "width": 6,
                "floor_boundary": "heated",
                "ceiling_boundary": "heated",
                "indoor": 24,
                "outdoor": -14,
                "volume": 144,
                "airflow_input_basis": "components_m3_h",
                "mechanical_ventilation_m3_h": 0,
                "natural_ventilation_m3_h": 0,
                "infiltration_m3_h": 0,
                "infiltration_basis": "appendix8_envelope",
                "infiltration_paths": [
                    {
                        "pressure_pa": 12,
                        "first_floor_pressure_pa": 10,
                        "opening_area_m2": 20,
                        "air_permeability_resistance_m2_h_pa_kg": 0.5,
                        "envelope_area_m2": 0,
                        "normative_air_permeability_kg_m2_h": 0,
                        "gap_area_m2": 0,
                        "panel_joint_length_m": 0,
                    }
                ],
            }
        )
        self.assertEqual(building.airflow.infiltration_basis, "appendix8_envelope")
        self.assertEqual(building.airflow.infiltration_paths[0].pressure_pa, 12)
        self.assertTrue(any("формуле 3 приложения 8" in item for item in building.assumptions))

    def test_different_wall_groups_keep_individual_constructions(self) -> None:
        data = {
            "wall_groups": [
                {
                    "name": "Север",
                    "orientation": "north",
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
                    "layers": [
                        {"material": "brick_hollow", "thickness_m": 0.12},
                        {
                            "material": "custom",
                            "material_conductivity": 0.04,
                            "thickness_m": 0.08,
                        },
                        {"material": "aerated_d500", "thickness_m": 0.20},
                    ],
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
        self.assertEqual(
            [layer.material_key for layer in walls[1].layers],
            ["brick_hollow", "custom", "aerated_d500"],
        )

    def test_window_groups_are_deducted_from_their_selected_walls(self) -> None:
        data = {
            "wall_groups": [
                {
                    "name": "Север",
                    "orientation": "north",
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
        self.assertEqual(walls[0].orientation, "north")
        self.assertEqual(walls[0].additional_heat_loss_factor, 0.1)
        self.assertEqual(building.openings[0].orientation, "north")
        self.assertEqual(building.openings[0].additional_heat_loss_factor, 0.1)
        self.assertFalse(building.assumptions)

    def test_unassigned_opening_discloses_distribution_and_zero_orientation_factor(self) -> None:
        data = {
            "wall_groups": [
                {
                    "name": "Север",
                    "orientation": "north",
                    "gross_area_m2": 30,
                    "material": "brick_solid",
                    "thickness_m": 0.25,
                    "insulation_material": None,
                    "insulation_thickness_m": 0,
                }
            ],
            "wall_gross_area": 30,
            "window_count": 1,
            "window_area": 3,
            "window_type": "double",
            "door_area": 0,
            "length": 5,
            "width": 4,
            "floor_boundary": "heated",
            "ceiling_boundary": "heated",
            "indoor": 24,
            "outdoor": -14,
            "volume": 60,
            "air_changes": 0.5,
        }

        building = _build_from_answers(data)

        self.assertEqual(building.openings[0].additional_heat_loss_factor, 0)
        self.assertIsNone(building.openings[0].orientation)
        self.assertTrue(any("β=0" in item for item in building.assumptions))

    def test_wall_groups_without_openings_do_not_create_distribution_assumption(self) -> None:
        data = {
            "wall_groups": [
                {
                    "name": "Север",
                    "orientation": "north",
                    "gross_area_m2": 30,
                    "material": "brick_solid",
                    "thickness_m": 0.25,
                    "insulation_material": None,
                    "insulation_thickness_m": 0,
                }
            ],
            "wall_gross_area": 30,
            "window_count": 0,
            "window_area": 0,
            "door_area": 0,
            "length": 5,
            "width": 4,
            "floor_boundary": "heated",
            "ceiling_boundary": "heated",
            "indoor": 24,
            "outdoor": -14,
            "volume": 60,
            "air_changes": 0.5,
        }

        building = _build_from_answers(data)

        self.assertFalse(building.assumptions)


if __name__ == "__main__":
    unittest.main()
