import math
import unittest

from u_calc.calculator import calculate_heat_loss
from u_calc.handlers.common import bounded_text
from u_calc.models import HeatLossResult, Layer, LossLine
from u_calc.parsing import parse_door_groups, parse_number, parse_wall_groups
from u_calc.services.building_factory import (
    InvalidCalculationData,
    build_from_answers,
    climate_from_answers,
)
from u_calc.services.calculation_service import calculate_from_answers


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
    def test_bounded_ui_text_rejects_control_characters(self) -> None:
        self.assertEqual(
            bounded_text("  Ташкент  ", minimum=2, maximum=80, label="Город"),
            "Ташкент",
        )
        with self.assertRaisesRegex(ValueError, "управляющие"):
            bounded_text("Дом\u200b", minimum=1, maximum=120, label="Объект")

    def test_heat_loss_result_rejects_inconsistent_totals(self) -> None:
        line = LossLine("Стена", "Ограждение", 10, 1, 38, 380)
        with self.assertRaisesRegex(ValueError, "ограждений и воздухообмена"):
            HeatLossResult(380, 20, 380, 420, (line,))
        with self.assertRaisesRegex(ValueError, "сумме строк"):
            HeatLossResult(380, 0, 380, 420, (LossLine("Стена", "Ограждение", 10, 1, 38, 370),))
        with self.assertRaisesRegex(ValueError, "ниже расчётной"):
            HeatLossResult(380, 0, 380, 379, (line,))

    def test_loss_line_rejects_non_finite_or_negative_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "конечным"):
            LossLine("Стена", "Ограждение", 10, 1, 38, math.nan)
        with self.assertRaisesRegex(ValueError, "от 0"):
            LossLine("Стена", "Ограждение", 10, 1, 38, -1)

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

    def test_central_factory_rejects_malformed_collections(self) -> None:
        cases = (
            ("wall_groups", {"name": "Север"}),
            ("window_groups", "окна"),
            ("door_groups", ["дверь"]),
            ("linear_thermal_bridges", {"name": "Балкон"}),
            ("infiltration_paths", [42]),
        )
        for key, value in cases:
            with self.subTest(key=key):
                data = base_answers()
                data[key] = value
                with self.assertRaisesRegex(InvalidCalculationData, key):
                    build_from_answers(data)

    def test_opening_count_must_be_integer(self) -> None:
        data = base_answers()
        data.update(
            window_area=2,
            window_groups=[
                {
                    "name": "Окно",
                    "count": 1.5,
                    "area_m2": 2,
                    "u_value": 1.4,
                    "wall_name": None,
                }
            ],
        )
        with self.assertRaisesRegex(InvalidCalculationData, "целым числом"):
            build_from_answers(data)

        simple = base_answers()
        simple.update(window_count=1.5, window_area=2, window_type="double")
        with self.assertRaisesRegex(InvalidCalculationData, "целым числом"):
            build_from_answers(simple)

    def test_opening_group_area_must_match_dimensions_and_count(self) -> None:
        data = base_answers()
        data.update(
            window_area=2,
            window_groups=[
                {
                    "name": "Окно",
                    "count": 2,
                    "width_m": 1,
                    "height_m": 1,
                    "area_m2": 3,
                    "u_value": 1.4,
                    "wall_name": None,
                }
            ],
        )
        with self.assertRaisesRegex(InvalidCalculationData, "не совпадает"):
            build_from_answers(data)

    def test_ground_floor_flags_and_sides_are_strictly_typed(self) -> None:
        data = base_answers()
        data.update(
            floor_boundary="ground",
            floor_ground_method="zonal",
            ground_exterior_sides=["north", "east"],
            floor_on_joists="false",
        )
        with self.assertRaisesRegex(InvalidCalculationData, "floor_on_joists"):
            build_from_answers(data)

        data["floor_on_joists"] = False
        data["ground_exterior_sides"] = "north"
        with self.assertRaisesRegex(InvalidCalculationData, "ground_exterior_sides"):
            build_from_answers(data)

        data["ground_exterior_sides"] = ["north", "north"]
        with self.assertRaisesRegex(InvalidCalculationData, "повторяющиеся"):
            build_from_answers(data)

    def test_infiltration_paths_cannot_be_silently_ignored(self) -> None:
        data = base_answers()
        data["infiltration_paths"] = [
            {
                "pressure_pa": 10,
                "first_floor_pressure_pa": 10,
                "opening_area_m2": 0,
                "air_permeability_resistance_m2_h_pa_kg": 0,
                "envelope_area_m2": 0,
                "normative_air_permeability_kg_m2_h": 0,
                "gap_area_m2": 0.01,
                "panel_joint_length_m": 0,
            }
        ]
        with self.assertRaisesRegex(InvalidCalculationData, "отсутствуют поля расходов"):
            build_from_answers(data)

    def test_normative_infiltration_flow_matches_living_area(self) -> None:
        data = base_answers()
        data.update(
            airflow_input_basis="components_m3_h",
            mechanical_ventilation_m3_h=0,
            natural_ventilation_m3_h=0,
            infiltration_m3_h=90,
            infiltration_basis="appendix8_residential_exhaust",
            infiltration_living_area_m2=20,
        )
        with self.assertRaisesRegex(InvalidCalculationData, "3 м³/ч"):
            build_from_answers(data)

        data["infiltration_living_area_m2"] = 30
        self.assertEqual(build_from_answers(data).airflow.infiltration_m3_h, 90)

        data["infiltration_living_area_m2"] = 49
        data["infiltration_m3_h"] = 147
        with self.assertRaisesRegex(InvalidCalculationData, "от 0 до 48"):
            build_from_answers(data)

    def test_legacy_envelope_flow_reports_formula_two_comparison(self) -> None:
        data = base_answers()
        data.update(
            airflow_input_basis="components_m3_h",
            mechanical_ventilation_m3_h=0,
            natural_ventilation_m3_h=0,
            infiltration_m3_h=30,
            infiltration_basis="appendix8_envelope",
            infiltration_paths=[
                {
                    "pressure_pa": 10,
                    "first_floor_pressure_pa": 10,
                    "opening_area_m2": 0,
                    "air_permeability_resistance_m2_h_pa_kg": 0,
                    "envelope_area_m2": 0,
                    "normative_air_permeability_kg_m2_h": 0,
                    "gap_area_m2": 0.01,
                    "panel_joint_length_m": 0,
                }
            ],
        )
        building = build_from_answers(data)
        self.assertTrue(any("сопоставлен с формулой 2" in item for item in building.assumptions))

    def test_names_and_climate_sources_reject_control_characters(self) -> None:
        data = base_answers()
        data["wall_groups"] = [
            {
                "name": "Север\u200b",
                "gross_area_m2": 60,
                "material": "brick_solid",
                "thickness_m": 0.25,
            }
        ]
        with self.assertRaisesRegex(InvalidCalculationData, "название стены"):
            build_from_answers(data)

        climate = {
            "climate_key": "tashkent",
            "confirmed_design_c": -15,
            "confirmed_design_source": "СП\nтаблица 1",
        }
        with self.assertRaisesRegex(InvalidCalculationData, "confirmed_design_source"):
            climate_from_answers(climate)

    def test_climate_source_length_is_bounded_in_domain_factory(self) -> None:
        data = {
            "climate_key": "tashkent",
            "confirmed_design_c": -15,
            "confirmed_design_source": "x" * 301,
        }
        with self.assertRaisesRegex(InvalidCalculationData, "confirmed_design_source"):
            climate_from_answers(data)

    def test_climate_factory_rejects_impossible_temperature_order(self) -> None:
        confirmed = {
            "climate_key": "tashkent",
            "confirmed_design_c": 5,
            "confirmed_design_source": "Проектная справка",
        }
        with self.assertRaisesRegex(InvalidCalculationData, "холоднее"):
            climate_from_answers(confirmed)

        custom = {
            "climate_key": "custom",
            "custom_city_name": "Тестовый город",
            "custom_cold_mean": -5,
            "custom_design": -15,
            "custom_extreme": -10,
            "custom_hot_mean": 25,
            "custom_hot_max": 40,
            "custom_climate_source": "Метеостанция",
        }
        with self.assertRaisesRegex(InvalidCalculationData, "абсолютный минимум"):
            climate_from_answers(custom)

        custom.update(custom_extreme=-20, custom_hot_max=20)
        with self.assertRaisesRegex(InvalidCalculationData, "Абсолютный максимум"):
            climate_from_answers(custom)

    def test_calculation_scenario_must_match_outdoor_temperature(self) -> None:
        data = base_answers()
        data.update(
            locale="ru",
            climate_key="tashkent",
            confirmed_design_c=-15,
            confirmed_design_source="Проектная справка",
            scenario="design",
            outdoor=-14,
        )
        with self.assertRaisesRegex(InvalidCalculationData, "не соответствует"):
            calculate_from_answers(data)

        data["outdoor"] = -15
        self.assertEqual(calculate_from_answers(data).building.outdoor_temperature_c, -15)

        data["scenario"] = "unknown"
        with self.assertRaisesRegex(InvalidCalculationData, "сценарий"):
            calculate_from_answers(data)

        data["scenario"] = "design"
        data["locale"] = "xx"
        with self.assertRaisesRegex(InvalidCalculationData, "язык"):
            calculate_from_answers(data)

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

    def test_modern_surface_insulation_field_precedes_legacy_fallback(self) -> None:
        data = base_answers()
        data.update(
            floor_boundary="outdoor",
            floor_material="concrete",
            floor_thickness=0.2,
            floor_insulation_material="mineral_wool",
            floor_insulation_thickness=0.05,
            floor_insulation="повреждённое старое поле",
        )
        floor = next(
            surface for surface in build_from_answers(data).opaque_surfaces if surface.name == "Пол"
        )
        self.assertEqual(len(floor.layers), 2)

        del data["floor_insulation_thickness"]
        with self.assertRaisesRegex(InvalidCalculationData, "числом"):
            build_from_answers(data)

    def test_recovery_reduces_only_ventilation_loss(self) -> None:
        data = base_answers()
        data.update(
            mechanical_ventilation_m3_h=50,
            natural_ventilation_m3_h=20,
            infiltration_m3_h=10,
            airflow_input_basis="components_m3_h",
            infiltration_basis="manual_flow",
        )
        no_recovery = calculate_heat_loss(build_from_answers(data))
        data["heat_recovery_efficiency"] = 0.7
        recovery = calculate_heat_loss(build_from_answers(data))
        delta_t = data["indoor"] - data["outdoor"]
        self.assertAlmostEqual(no_recovery.ventilation_w, 0.33 * (50 + 20 + 10) * delta_t)
        self.assertAlmostEqual(recovery.ventilation_w, 0.33 * (50 * 0.3 + 20 + 10) * delta_t)
        self.assertAlmostEqual(recovery.transmission_w, no_recovery.transmission_w)


if __name__ == "__main__":
    unittest.main()
