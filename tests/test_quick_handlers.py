import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from u_calc.handlers import openings, walls
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
    def __init__(self, data: str, message=None) -> None:
        self.data = data
        self.message = message or FakeMessage()
        self.from_user = self.message.from_user
        self.answers = []

    async def answer(self, text=None, **kwargs) -> None:
        self.answers.append((text, kwargs))


class QuickWallHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_wall_method_routes_supported_inputs_and_rejects_unknown_callback(self) -> None:
        base = {"locale": "ru", "length": 10.0, "width": 8.0, "height": 3.0}
        expected = {
            "area": Survey.wall_area,
            "dimensions": Survey.wall_dimensions,
            "groups": Survey.wall_groups,
        }
        for method, expected_state in expected.items():
            with self.subTest(method=method):
                state = FakeState(base)
                callback = FakeCallback(f"walls:{method}")
                await walls.wall_method(callback, state)
                self.assertEqual(state.state, expected_state)
                self.assertEqual(len(callback.answers), 1)

        state = FakeState(base)
        callback = FakeCallback("walls:perimeter")
        await walls.wall_method(callback, state)
        self.assertEqual(state.data["wall_gross_area"], 108.0)
        self.assertEqual(state.state, Survey.wall_material)

        invalid = FakeCallback("walls:unknown")
        await walls.wall_method(invalid, FakeState(base, Survey.wall_method))
        self.assertTrue(invalid.answers[-1][1]["show_alert"])

    async def test_wall_area_and_dimensions_validate_before_advancing(self) -> None:
        for handler, text in ((walls.wall_area, "bad"), (walls.wall_dimensions, "bad")):
            with self.subTest(handler=handler.__name__):
                state = FakeState({"locale": "ru"}, Survey.wall_area)
                message = FakeMessage(text)
                await handler(message, state)
                self.assertNotIn("wall_gross_area", state.data)
                self.assertIn("Попробуйте", message.answers[-1][0])

        area_state = FakeState({"locale": "ru"})
        await walls.wall_area(FakeMessage("45,5"), area_state)
        self.assertEqual(area_state.data["wall_gross_area"], 45.5)
        self.assertEqual(area_state.state, Survey.wall_material)

        dimensions_state = FakeState({"locale": "ru"})
        await walls.wall_dimensions(FakeMessage("5x3; 4x3"), dimensions_state)
        self.assertEqual(dimensions_state.data["wall_gross_area"], 27.0)
        self.assertEqual(dimensions_state.state, Survey.wall_material)

    async def test_custom_wall_and_insulation_flow_preserves_passport_lambdas(self) -> None:
        state = FakeState({"locale": "ru", "wall_gross_area": 60.0})
        custom = FakeCallback("mat:custom")
        await walls.wall_material(custom, state)
        self.assertEqual(state.state, Survey.wall_custom_lambda)

        invalid_lambda = FakeMessage("nan")
        await walls.wall_custom_lambda(invalid_lambda, state)
        self.assertEqual(state.state, Survey.wall_custom_lambda)
        self.assertIn("Попробуйте", invalid_lambda.answers[-1][0])

        await walls.wall_custom_lambda(FakeMessage("0,12"), state)
        self.assertEqual(state.data["wall_conductivity"], 0.12)
        self.assertEqual(state.state, Survey.wall_thickness)

        invalid_thickness = FakeMessage("bad")
        await walls.wall_thickness(invalid_thickness, state)
        self.assertEqual(state.state, Survey.wall_thickness)
        await walls.wall_thickness(FakeMessage("30"), state)
        self.assertEqual(state.data["wall_thickness"], 0.3)
        self.assertEqual(state.state, Survey.insulated)

        invalid_choice = FakeCallback("ins:maybe")
        await walls.insulated(invalid_choice, state)
        self.assertTrue(invalid_choice.answers[-1][1]["show_alert"])

        await walls.insulated(FakeCallback("ins:yes"), state)
        self.assertEqual(state.state, Survey.insulation_material)
        await walls.insulation_material(FakeCallback("imat:custom"), state)
        self.assertEqual(state.state, Survey.insulation_custom_lambda)

        invalid_insulation = FakeMessage("inf")
        await walls.insulation_custom_lambda(invalid_insulation, state)
        self.assertEqual(state.state, Survey.insulation_custom_lambda)
        await walls.insulation_custom_lambda(FakeMessage("0,036"), state)
        self.assertEqual(state.data["insulation_conductivity"], 0.036)

        invalid_insulation_thickness = FakeMessage("bad")
        await walls.insulation_thickness(invalid_insulation_thickness, state)
        self.assertEqual(state.state, Survey.insulation_thickness)
        await walls.insulation_thickness(FakeMessage("8"), state)
        self.assertEqual(state.data["insulation_thickness"], 0.08)
        self.assertEqual(state.state, Survey.window_count)

    async def test_catalog_wall_paths_and_invalid_materials(self) -> None:
        state = FakeState({"locale": "ru"})
        invalid = FakeCallback("mat:missing")
        await walls.wall_material(invalid, state)
        self.assertTrue(invalid.answers[-1][1]["show_alert"])

        await walls.wall_material(FakeCallback("mat:aerated_d500"), state)
        self.assertEqual(state.data["wall_material"], "aerated_d500")
        self.assertEqual(state.state, Survey.wall_thickness)

        legacy_material = FakeCallback("mat:pu_foam")
        await walls.wall_material(legacy_material, state)
        self.assertTrue(legacy_material.answers[-1][1]["show_alert"])

        await walls.wall_thickness(FakeMessage("30"), state)
        await walls.insulated(FakeCallback("ins:yes"), state)
        invalid_insulation = FakeCallback("imat:brick_solid")
        await walls.insulation_material(invalid_insulation, state)
        self.assertTrue(invalid_insulation.answers[-1][1]["show_alert"])

        legacy_insulation = FakeCallback("imat:pu_foam")
        await walls.insulation_material(legacy_insulation, state)
        self.assertTrue(legacy_insulation.answers[-1][1]["show_alert"])

        await walls.insulation_material(FakeCallback("imat:mineral_wool"), state)
        self.assertEqual(state.data["insulation_material"], "mineral_wool")
        self.assertEqual(state.state, Survey.insulation_thickness)


class QuickOpeningHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_expert_window_groups_validate_counts_walls_and_wall_capacity(self) -> None:
        base = {
            "locale": "ru",
            "window_count": 2,
            "wall_gross_area": 20.0,
            "wall_groups": [{"name": "Север", "gross_area_m2": 10.0}],
        }
        for text, expected_fragment in (
            ("Окна | 1 | 1x1 | 1,2 | Север", "не совпадает"),
            ("Окна | 2 | 1x1 | 1,2 | Юг", "не найдена"),
            ("Окна | 2 | 3x2 | 1,2 | Север", "больше площади"),
        ):
            with self.subTest(text=text):
                state = FakeState(base, Survey.window_groups)
                message = FakeMessage(text)
                await openings.window_groups(message, state)
                self.assertNotIn("window_groups", state.data)
                self.assertIn(expected_fragment, message.answers[-1][0])

        state = FakeState(base, Survey.window_groups)
        message = FakeMessage("Окна | 2 | 1,5x1,4 | 1,1 | север")
        await openings.window_groups(message, state)
        self.assertAlmostEqual(state.data["window_area"], 4.2)
        self.assertEqual(state.data["window_groups"][0]["wall_name"], "Север")
        self.assertIsNone(state.data["window_type"])
        self.assertEqual(state.state, Survey.door_count)

    async def test_expert_door_groups_validate_combined_openings_per_wall(self) -> None:
        base = {
            "locale": "ru",
            "door_count": 1,
            "window_area": 6.0,
            "wall_gross_area": 20.0,
            "wall_groups": [{"name": "Север", "gross_area_m2": 10.0}],
            "window_groups": [
                {"name": "Окна", "area_m2": 6.0, "wall_name": "Север"}
            ],
        }
        for text, expected_fragment in (
            ("Дверь | 2 | 1x2 | 1,5 | Север", "не совпадает"),
            ("Дверь | 1 | 1x2 | 1,5 | Юг", "не найдена"),
            ("Дверь | 1 | 2,5x2 | 1,5 | Север", "больше её площади"),
        ):
            with self.subTest(text=text):
                state = FakeState(base, Survey.door_groups)
                message = FakeMessage(text)
                await openings.door_groups(message, state)
                self.assertNotIn("door_groups", state.data)
                self.assertIn(expected_fragment, message.answers[-1][0])

        state = FakeState(base, Survey.door_groups)
        message = FakeMessage("Дверь | 1 | 0,9x2 | 1,4 | север")
        with patch.object(openings, "_advance_after_openings", new=AsyncMock()) as advance:
            await openings.door_groups(message, state)
        self.assertAlmostEqual(state.data["door_area"], 1.8)
        self.assertEqual(state.data["door_groups"][0]["wall_name"], "Север")
        self.assertIsNone(state.data["door_u_value"])
        advance.assert_awaited_once()

    async def test_window_count_and_method_handle_zero_invalid_and_dimensions(self) -> None:
        invalid_state = FakeState({"locale": "ru"}, Survey.window_count)
        invalid_message = FakeMessage("501")
        await openings.window_count(invalid_message, invalid_state)
        self.assertEqual(invalid_state.state, Survey.window_count)
        self.assertIn("Попробуйте", invalid_message.answers[-1][0])

        zero_state = FakeState({"locale": "ru"})
        await openings.window_count(FakeMessage("0"), zero_state)
        self.assertEqual(zero_state.data["window_area"], 0.0)
        self.assertEqual(zero_state.state, Survey.door_count)

        state = FakeState({"locale": "ru", "wall_gross_area": 80.0})
        await openings.window_count(FakeMessage("2"), state)
        self.assertEqual(state.state, Survey.window_method)
        invalid = FakeCallback("window_method:unknown")
        await openings.window_method(invalid, state)
        self.assertTrue(invalid.answers[-1][1]["show_alert"])

        await openings.window_method(FakeCallback("window_method:dimensions"), state)
        self.assertEqual(state.state, Survey.window_dimensions)
        await openings.window_dimensions(FakeMessage("1,5x1,4"), state)
        self.assertAlmostEqual(state.data["window_area"], 4.2)
        self.assertEqual(state.state, Survey.window_type)

    async def test_window_area_dimensions_and_type_reject_invalid_values(self) -> None:
        for text in ("0", "51"):
            with self.subTest(text=text):
                state = FakeState(
                    {"locale": "ru", "wall_gross_area": 50.0, "window_count": 2},
                    Survey.window_area,
                )
                message = FakeMessage(text)
                await openings.window_area(message, state)
                self.assertNotIn("window_area", state.data)
                self.assertIn("Попробуйте", message.answers[-1][0])

        state = FakeState(
            {"locale": "ru", "wall_gross_area": 50.0, "window_count": 2},
            Survey.window_dimensions,
        )
        multiple = FakeMessage("1x1; 2x2")
        await openings.window_dimensions(multiple, state)
        self.assertNotIn("window_area", state.data)

        invalid_type = FakeCallback("window:missing")
        await openings.window_type(invalid_type, state)
        self.assertTrue(invalid_type.answers[-1][1]["show_alert"])

        state.data["window_area"] = 4.0
        await openings.window_type(FakeCallback("window:triple"), state)
        self.assertEqual(state.data["window_type"], "triple")
        self.assertEqual(state.state, Survey.door_count)

    async def test_door_count_methods_area_dimensions_and_type(self) -> None:
        invalid_state = FakeState({"locale": "ru"}, Survey.door_count)
        invalid_message = FakeMessage("101")
        await openings.door_count(invalid_message, invalid_state)
        self.assertNotIn("door_count", invalid_state.data)

        state = FakeState(
            {
                "locale": "ru",
                "wall_gross_area": 40.0,
                "window_area": 5.0,
                "calculation_mode": "quick",
                "apartment_position": "middle",
            }
        )
        await openings.door_count(FakeMessage("2"), state)
        self.assertEqual(state.state, Survey.door_method)
        invalid_method = FakeCallback("door_method:unknown")
        await openings.door_method(invalid_method, state)
        self.assertTrue(invalid_method.answers[-1][1]["show_alert"])

        await openings.door_method(FakeCallback("door_method:area"), state)
        for text in ("0", "36"):
            message = FakeMessage(text)
            await openings.door_area(message, state)
            self.assertIn("Попробуйте", message.answers[-1][0])
        await openings.door_area(FakeMessage("4"), state)
        self.assertEqual(state.data["door_area"], 4.0)
        self.assertEqual(state.state, Survey.door_type)

        invalid_type = FakeCallback("door_type:missing")
        await openings.door_type(invalid_type, state)
        self.assertTrue(invalid_type.answers[-1][1]["show_alert"])

        with patch.object(openings, "_advance_after_openings", new=AsyncMock()) as advance:
            await openings.door_type(FakeCallback("door_type:insulated"), state)
        self.assertEqual(state.data["door_u_value"], openings.DOORS["insulated"].u_value)
        advance.assert_awaited_once()

        dimensions_state = FakeState(
            {"locale": "ru", "wall_gross_area": 40.0, "window_area": 5.0, "door_count": 2}
        )
        multiple = FakeMessage("1x2; 1x2")
        await openings.door_dimensions(multiple, dimensions_state)
        self.assertNotIn("door_area", dimensions_state.data)
        await openings.door_dimensions(FakeMessage("0,9x2"), dimensions_state)
        self.assertAlmostEqual(dimensions_state.data["door_area"], 3.6)
        self.assertEqual(dimensions_state.state, Survey.door_type)

    async def test_zero_doors_advances_with_clean_opening_state(self) -> None:
        state = FakeState({"locale": "ru"})
        with patch.object(openings, "_advance_after_openings", new=AsyncMock()) as advance:
            await openings.door_count(FakeMessage("0"), state)

        self.assertEqual(state.data["door_area"], 0.0)
        self.assertEqual(state.data["door_groups"], [])
        self.assertIsNone(state.data["door_u_value"])
        advance.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
