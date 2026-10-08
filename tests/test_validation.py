import math
import unittest

from u_calc.calculator import calculate_heat_loss
from u_calc.models import Layer
from u_calc.parsing import parse_door_groups, parse_number, parse_wall_groups
from u_calc.services.building_factory import InvalidCalculationData, build_from_answers


def base_answers() -> dict:
    return {
        "wall_material": "brick_solid",
        "wall_thickness": 0.25,
        "insulation_material": None,
        "insulation_thickness": 0,
        "wall_gross_area": 60,
        "window_count": 0,
        "window_area": 0,
        "window_type": "double",
        "door_area": 0,
        "length": 8,
        "width": 6,
        "height": 3,
        "volume": 144,
        "floor_boundary": "heated",
        "ceiling_boundary": "heated",
        "indoor": 24,
        "outdoor": -14,
        "air_changes": 0.5,
    }


class ValidationTests(unittest.TestCase):
    def test_nan_and_infinity_are_rejected(self) -> None:
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "конечным"):
                parse_number(value)
        with self.assertRaisesRegex(ValueError, "конечным"):
            Layer("custom", 0.2, math.nan)

    def test_central_factory_rejects_corrupted_fsm_payload(self) -> None:
        data = base_answers()
        data["volume"] = float("inf")
        with self.assertRaisesRegex(InvalidCalculationData, "конечным"):
            build_from_answers(data)
        del data["floor_boundary"]
        data["volume"] = 144
        with self.assertRaisesRegex(InvalidCalculationData, "floor_boundary"):
            build_from_answers(data)

    def test_volume_must_match_dimensions_within_two_percent(self) -> None:
        data = base_answers()
        data["volume"] = 180
        with self.assertRaisesRegex(InvalidCalculationData, "Объём не согласован"):
            build_from_answers(data)

        data["volume"] = 146
        self.assertEqual(build_from_answers(data).volume_m3, 146)

    def test_duplicate_wall_names_are_case_insensitive(self) -> None:
        with self.assertRaisesRegex(ValueError, "уже использовано"):
            parse_wall_groups("Север | 20 | кирпич | 25\nсЕвЕр | 15 | газоблок | 30")

    def test_explicit_wall_layers_are_strictly_validated(self) -> None:
        data = base_answers()
        data["wall_groups"] = [
            {
                "name": "Север",
                "gross_area_m2": 60,
                "layers": ["повреждённый слой"],
            }
        ]
        with self.assertRaisesRegex(InvalidCalculationData, "слой стены"):
            build_from_answers(data)
        data["wall_groups"][0]["layers"] = [{"material": "brick_solid", "thickness_m": 0.1}] * 11
        with self.assertRaisesRegex(InvalidCalculationData, "от 1 до 10"):
            build_from_answers(data)

    def test_door_groups_preserve_count_area_u_and_wall(self) -> None:
        groups = parse_door_groups("Входная | 2 | 0,9x2,1 | 1,4 | Север")
        self.assertEqual(groups[0]["count"], 2)
        self.assertAlmostEqual(groups[0]["area_m2"], 3.78)
        self.assertEqual(groups[0]["u_value"], 1.4)
        self.assertEqual(groups[0]["wall_name"], "Север")

    def test_door_group_u_is_used_and_cannot_exceed_bound_wall(self) -> None:
        data = base_answers()
        data.update(
            wall_groups=[
                {
                    "name": "Север",
                    "gross_area_m2": 10,
                    "material": "brick_solid",
                    "thickness_m": 0.25,
                    "insulation_material": None,
                    "insulation_thickness_m": 0,
                }
            ],
            door_area=2,
            door_groups=[
                {
                    "name": "Входная",
                    "count": 1,
                    "area_m2": 2,
                    "u_value": 1.4,
                    "wall_name": "Север",
                }
            ],
        )
        building = build_from_answers(data)
        self.assertEqual(building.openings[0].u_value, 1.4)
        self.assertEqual(building.opaque_surfaces[0].area_m2, 8)

        data["door_groups"][0]["area_m2"] = 11
        with self.assertRaisesRegex(InvalidCalculationData, "больше её площади"):
            build_from_answers(data)

    def test_heated_neighbor_temperature_uses_real_floor_construction(self) -> None:
        data = base_answers()
        data.update(
            floor_adjacent_temperature=18,
            floor_material="concrete",
            floor_thickness=0.2,
            floor_insulation_material="mineral_wool",
            floor_insulation_thickness=0.05,
        )
        building = build_from_answers(data)
        floor = next(surface for surface in building.opaque_surfaces if surface.name == "Пол")
        self.assertEqual(floor.adjacent_temperature_c, 18)
        self.assertEqual(len(floor.layers), 2)
        self.assertGreater(calculate_heat_loss(building).transmission_w, 0)

    def test_recovery_reduces_only_ventilation_loss(self) -> None:
        data = base_answers()
        no_recovery = calculate_heat_loss(build_from_answers(data))
        data["heat_recovery_efficiency"] = 0.7
        recovery = calculate_heat_loss(build_from_answers(data))
        self.assertAlmostEqual(recovery.ventilation_w, no_recovery.ventilation_w * 0.3)
        self.assertAlmostEqual(recovery.transmission_w, no_recovery.transmission_w)


if __name__ == "__main__":
    unittest.main()
