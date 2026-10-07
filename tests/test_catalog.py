import unittest
from dataclasses import replace

from u_calc.catalog import CLIMATES


class ClimateTests(unittest.TestCase):
    def test_future_scenario_adds_two_degree_risk_margin(self) -> None:
        tashkent = replace(CLIMATES["tashkent"], design_c=-14)
        self.assertEqual(tashkent.outdoor_temperature("future"), -16)

    def test_future_scenario_never_exceeds_observed_cold_record(self) -> None:
        profile = replace(CLIMATES["nukus"], design_c=-19)
        self.assertGreaterEqual(profile.outdoor_temperature("future"), profile.observed_extreme_c)

    def test_builtin_design_temperature_requires_user_confirmation(self) -> None:
        profile = CLIMATES["tashkent"]
        self.assertIsNone(profile.design_c)
        with self.assertRaisesRegex(ValueError, "подтверждения"):
            profile.outdoor_temperature("design")

    def test_each_builtin_climate_value_has_its_own_source_record(self) -> None:
        parameters = {item.parameter for item in CLIMATES["tashkent"].provenance}
        self.assertEqual(
            parameters,
            {
                "cold_month_mean_c",
                "observed_extreme_c",
                "hot_month_mean_c",
                "observed_maximum_c",
            },
        )
        self.assertTrue(
            all(
                item.location.startswith("приложение, таблица 1")
                for item in CLIMATES["tashkent"].provenance
            )
        )
