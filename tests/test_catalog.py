import tomllib
import unittest
from dataclasses import replace
from pathlib import Path

from u_calc.catalog import CLIMATES, ENGINE_VERSION, MATERIALS, SELECTABLE_MATERIALS


class ClimateTests(unittest.TestCase):
    def test_engine_version_matches_distribution_version(self) -> None:
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(ENGINE_VERSION, project["project"]["version"])

    def test_future_scenario_adds_two_degree_risk_margin(self) -> None:
        tashkent = replace(CLIMATES["tashkent"], design_c=-14)
        self.assertEqual(tashkent.outdoor_temperature("future"), -16)

    def test_future_scenario_never_exceeds_observed_cold_record(self) -> None:
        profile = replace(CLIMATES["nukus"], design_c=-19)
        self.assertGreaterEqual(profile.outdoor_temperature("future"), profile.observed_extreme_c)

    def test_builtin_design_temperatures_come_from_normative_parameter_b(self) -> None:
        self.assertEqual(
            {key: profile.design_c for key, profile in CLIMATES.items()},
            {"tashkent": -14.0, "samarkand": -12.0, "nukus": -20.0},
        )
        self.assertEqual(CLIMATES["tashkent"].outdoor_temperature("design"), -14.0)

    def test_climate_profile_rejects_impossible_temperature_order(self) -> None:
        with self.assertRaisesRegex(ValueError, "между абсолютным минимумом"):
            replace(CLIMATES["tashkent"], design_c=5)
        with self.assertRaisesRegex(ValueError, "максимум"):
            replace(CLIMATES["tashkent"], observed_maximum_c=20)

    def test_each_builtin_climate_value_has_its_own_source_record(self) -> None:
        parameters = {item.parameter for item in CLIMATES["tashkent"].provenance}
        self.assertEqual(
            parameters,
            {
                "cold_month_mean_c",
                "design_c",
                "observed_extreme_c",
                "hot_month_mean_c",
                "observed_maximum_c",
            },
        )
        design_source = next(
            item for item in CLIMATES["tashkent"].provenance if item.parameter == "design_c"
        )
        self.assertIn("таблица 4", design_source.location)
        self.assertIn("колонка 10", design_source.location)
        self.assertEqual(design_source.status, "normative")
        self.assertTrue(design_source.url.startswith("https://mc.uz/"))


class MaterialCatalogTests(unittest.TestCase):
    def test_selectable_materials_use_exact_normative_lambda_b_values(self) -> None:
        expected = {
            "brick_solid": 0.81,
            "brick_hollow": 0.52,
            "aerated_d500": 0.147,
            "concrete": 2.04,
            "wood": 0.18,
            "mineral_wool": 0.05,
            "eps": 0.05,
            "xps": 0.032,
        }
        self.assertEqual(
            {key: material.conductivity for key, material in SELECTABLE_MATERIALS.items()},
            expected,
        )

    def test_every_selectable_material_has_traceable_design_conditions(self) -> None:
        for material in SELECTABLE_MATERIALS.values():
            with self.subTest(material=material.key):
                self.assertEqual(material.value_status, "normative_design_b")
                self.assertIn("λБ", material.table_row)
                self.assertTrue(material.source_url.startswith("https://lex.uz/"))
                self.assertNotIn("сверить конкретную", material.standard)

    def test_unverified_legacy_material_is_reproducible_but_not_selectable(self) -> None:
        legacy = MATERIALS["pu_foam"]
        self.assertFalse(legacy.selectable)
        self.assertEqual(legacy.value_status, "legacy_reference_unverified")
        self.assertNotIn("pu_foam", SELECTABLE_MATERIALS)
