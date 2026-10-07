import unittest

from u_calc.catalog import CLIMATES


class ClimateTests(unittest.TestCase):
    def test_future_scenario_adds_two_degree_risk_margin(self) -> None:
        tashkent = CLIMATES["tashkent"]
        self.assertEqual(tashkent.outdoor_temperature("future"), -16)

    def test_future_scenario_never_exceeds_observed_cold_record(self) -> None:
        profile = CLIMATES["nukus"]
        self.assertGreaterEqual(profile.outdoor_temperature("future"), profile.observed_extreme_c)
