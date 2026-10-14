import unittest
from types import SimpleNamespace

from u_calc.handlers import climate
from u_calc.states import Survey


class FakeState:
    def __init__(self, data=None, state=None) -> None:
        self.data = dict(data or {})
        self.state = state

    async def get_data(self) -> dict:
        return dict(self.data)

    async def update_data(self, **values) -> None:
        self.data.update(values)

    async def set_state(self, state) -> None:
        self.state = state


class FakeMessage:
    def __init__(self, text=None) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=77)
        self.answers = []

    async def answer(self, text, **kwargs) -> None:
        self.answers.append((text, kwargs))


class FakeCallback:
    def __init__(self, data: str) -> None:
        self.data = data
        self.message = FakeMessage()
        self.from_user = self.message.from_user
        self.answers = []

    async def answer(self, text=None, **kwargs) -> None:
        self.answers.append((text, kwargs))


class ClimateHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_hot_month_mean_is_checked_on_its_own_step(self) -> None:
        state = FakeState(
            {
                "locale": "ru",
                "custom_cold_mean": 10.0,
                "custom_design": -5.0,
                "custom_extreme": -15.0,
            },
            Survey.custom_hot_mean,
        )
        invalid = FakeMessage("5")
        await climate.custom_hot_mean(invalid, state)

        self.assertEqual(state.state, Survey.custom_hot_mean)
        self.assertNotIn("custom_hot_mean", state.data)
        self.assertIn("жаркий месяц", invalid.answers[-1][0])

        valid = FakeMessage("25")
        await climate.custom_hot_mean(valid, state)
        self.assertEqual(state.data["custom_hot_mean"], 25.0)
        self.assertEqual(state.state, Survey.custom_hot_max)

    async def test_manual_source_revalidates_temperature_from_restored_draft(self) -> None:
        for outdoor in (float("nan"), 20.0, "broken"):
            with self.subTest(outdoor=outdoor):
                state = FakeState(
                    {"locale": "ru", "outdoor": outdoor},
                    Survey.manual_climate_source,
                )
                message = FakeMessage("Проект ОВ")
                await climate.manual_climate_source(message, state)

                self.assertEqual(state.state, Survey.manual_climate_source)
                self.assertNotIn("manual_climate_source", state.data)
                self.assertIn("Попробуйте", message.answers[-1][0])

    async def test_builtin_source_rejects_corrupt_confirmed_temperature(self) -> None:
        state = FakeState(
            {
                "locale": "ru",
                "climate_key": "tashkent",
                "confirmed_design_c": 20.0,
            },
            Survey.profile_design_source,
        )
        message = FakeMessage("Проект ОВ")
        await climate.profile_design_source(message, state)

        self.assertEqual(state.state, Survey.profile_design_source)
        self.assertNotIn("confirmed_design_source", state.data)
        self.assertIn("Попробуйте", message.answers[-1][0])

    async def test_custom_source_rejects_corrupt_profile_without_partial_save(self) -> None:
        state = FakeState(
            {
                "locale": "ru",
                "climate_key": "custom",
                "custom_city_name": "Тест",
                "custom_cold_mean": -5.0,
                "custom_design": -15.0,
                "custom_extreme": -10.0,
                "custom_hot_mean": 25.0,
                "custom_hot_max": 40.0,
            },
            Survey.custom_source,
        )
        message = FakeMessage("Метеостанция")
        await climate.custom_source(message, state)

        self.assertEqual(state.state, Survey.custom_source)
        self.assertNotIn("custom_climate_source", state.data)
        self.assertIn("абсолютный минимум", message.answers[-1][0].lower())

    async def test_scenario_rejects_corrupt_or_unknown_profile_and_callback(self) -> None:
        for data, callback_data in (
            ({"locale": "ru", "climate_key": "missing"}, "scenario:design"),
            ({"locale": "ru", "climate_key": "manual"}, "scenario:design"),
            (
                {
                    "locale": "ru",
                    "climate_key": "tashkent",
                    "confirmed_design_c": -14.0,
                    "confirmed_design_source": "Проект ОВ",
                },
                "scenario:unknown",
            ),
        ):
            with self.subTest(data=data, callback=callback_data):
                state = FakeState(data, Survey.scenario)
                callback = FakeCallback(callback_data)
                await climate.scenario(callback, state)

                self.assertTrue(callback.answers[-1][1]["show_alert"])
                self.assertNotIn("outdoor", state.data)

    async def test_climate_callback_rejects_unknown_value(self) -> None:
        state = FakeState({"locale": "ru"}, Survey.climate)
        callback = FakeCallback("climate:missing")
        await climate.climate(callback, state)

        self.assertTrue(callback.answers[-1][1]["show_alert"])
        self.assertNotIn("climate_key", state.data)


if __name__ == "__main__":
    unittest.main()
