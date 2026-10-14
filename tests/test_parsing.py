import unittest

from u_calc.parsing import (
    parse_appendix8_infiltration_paths,
    parse_appendix8_pressure_globals,
    parse_appendix8_pressure_groups,
    parse_dimensions,
    parse_linear_thermal_bridges,
    parse_triplet,
    parse_wall_groups,
    parse_window_groups,
)


class ParsingTests(unittest.TestCase):
    def test_parse_appendix8_formula_four_inputs(self) -> None:
        common = parse_appendix8_pressure_globals("12 | 1,3 | 5 | 0,8 | -0,6 | 1 | 0")
        groups = parse_appendix8_pressure_groups("8 | 2,5 | 20 | 0,5 | 100 | 0,2 | 0 | 0")
        self.assertEqual(common["building_height_m"], 12)
        self.assertEqual(common["leeward_coefficient"], -0.6)
        self.assertEqual(groups[0]["first_floor_opening_height_m"], 2.5)

    def test_parse_appendix8_infiltration_pressure_groups(self) -> None:
        groups = parse_appendix8_infiltration_paths(
            "12 | 10 | 20 | 0,5 | 100 | 0,2 | 0 | 0\n18 | 10 | 0 | 0 | 0 | 0 | 0,01 | 25"
        )
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["air_permeability_resistance_m2_h_pa_kg"], 0.5)
        self.assertEqual(groups[1]["gap_area_m2"], 0.01)

    def test_appendix8_paths_reject_missing_resistance(self) -> None:
        with self.assertRaisesRegex(ValueError, "Ru"):
            parse_appendix8_infiltration_paths("12 | 10 | 20 | 0 | 0 | 0 | 0 | 0")

    def test_parse_dimensions_accepts_russian_x_and_comma_decimal(self) -> None:
        self.assertEqual(parse_dimensions("5х3; 4,5x2"), [(5.0, 3.0), (4.5, 2.0)])

    def test_parse_triplet(self) -> None:
        self.assertEqual(parse_triplet("10 8 3"), (10.0, 8.0, 3.0))

    def test_bad_dimensions_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_dimensions("пять на три")

    def test_non_text_input_is_rejected_cleanly(self) -> None:
        with self.assertRaisesRegex(ValueError, "текстовым"):
            parse_dimensions(None)
        with self.assertRaisesRegex(ValueError, "текстовым"):
            parse_wall_groups(None)

    def test_parse_different_wall_constructions(self) -> None:
        groups = parse_wall_groups(
            "Север | 10x3 | кирпич | 25 | минвата | 5\nТорец | 18 | газоблок | 30 | нет | 0"
        )
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["gross_area_m2"], 30)
        self.assertEqual(groups[0]["material"], "brick_solid")
        self.assertEqual(groups[0]["insulation_material"], "mineral_wool")
        self.assertEqual(groups[1]["material"], "aerated_d500")

    def test_parse_uzbek_material_aliases_and_no_insulation(self) -> None:
        groups = parse_wall_groups(
            "Shimol | 10x3 | g‘isht | 25 | mineral paxta | 5\n"
            "Yon devor | 18 | gazoblok | 30 | yo‘q | 0"
        )

        self.assertEqual(groups[0]["material"], "brick_solid")
        self.assertEqual(groups[0]["insulation_material"], "mineral_wool")
        self.assertEqual(groups[1]["material"], "aerated_d500")
        self.assertIsNone(groups[1]["insulation_material"])

    def test_unknown_wall_material_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "неизвестный материал"):
            parse_wall_groups("Стена | 20 | солома | 30")

    def test_legacy_pu_foam_alias_is_rejected_in_new_expert_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "неизвестный материал"):
            parse_wall_groups("Стена | 20 | кирпич | 25 | ппу | 5")

        groups = parse_wall_groups("Стена | 20 | кирпич | 25 | λ=0,028 | 5")
        self.assertEqual(groups[0]["insulation_material"], "custom")
        self.assertEqual(groups[0]["insulation_conductivity"], 0.028)

    def test_expert_labels_are_rejected_instead_of_silently_truncated(self) -> None:
        with self.assertRaisesRegex(ValueError, "от 1 до 60"):
            parse_linear_thermal_bridges(f"{'М' * 61} | 4 | 0,2")
        with self.assertRaisesRegex(ValueError, "управляющие"):
            parse_wall_groups("Се\tвер | 20 | кирпич | 25")
        with self.assertRaisesRegex(ValueError, "от 1 до 60"):
            parse_window_groups(f"Окно | 1 | 1x1 | 1,2 | {'С' * 61}")

    def test_passport_lambda_is_preserved_for_custom_layers(self) -> None:
        groups = parse_wall_groups("Новый блок | 20 | λ=0,11 | 30 | lambda=0.036 | 8")
        self.assertEqual(groups[0]["material"], "custom")
        self.assertEqual(groups[0]["material_conductivity"], 0.11)
        self.assertEqual(groups[0]["insulation_conductivity"], 0.036)

    def test_parse_exact_linear_thermal_bridges(self) -> None:
        bridges = parse_linear_thermal_bridges("Балкон | 4,5 | 0,35\nПеремычки | 8 | 0,12")
        self.assertEqual(bridges[0]["length_m"], 4.5)
        self.assertEqual(bridges[0]["psi_w_mk"], 0.35)
        self.assertEqual(len(bridges), 2)

    def test_exact_bridge_names_must_be_unique_case_insensitively(self) -> None:
        with self.assertRaisesRegex(ValueError, "уже использовано"):
            parse_linear_thermal_bridges("Балкон | 4 | 0,3\nбалкон | 2 | 0,2")

    def test_exact_bridge_import_rejects_psi_outside_editor_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "от 0 до 5"):
            parse_linear_thermal_bridges("Балкон | 4 | 5,1")

    def test_parse_window_groups_with_passport_u_and_wall(self) -> None:
        groups = parse_window_groups(
            "ПВХ север | 3 | 1,4x1,5 | 1,1 | Север\nКухня | 1 | 1,2x1,4 | 1,6"
        )
        self.assertEqual(sum(group["count"] for group in groups), 4)
        self.assertAlmostEqual(groups[0]["area_m2"], 6.3)
        self.assertEqual(groups[0]["wall_name"], "Север")
        self.assertEqual(groups[1]["u_value"], 1.6)


if __name__ == "__main__":
    unittest.main()
