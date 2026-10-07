import unittest

from u_calc.parsing import (
    parse_dimensions,
    parse_linear_thermal_bridges,
    parse_triplet,
    parse_wall_groups,
    parse_window_groups,
)


class ParsingTests(unittest.TestCase):
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

    def test_unknown_wall_material_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "неизвестный материал"):
            parse_wall_groups("Стена | 20 | солома | 30")

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
