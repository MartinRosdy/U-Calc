import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from u_calc.handlers import boundaries
from u_calc.services.building_factory import InvalidCalculationData, _surface_layers
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

    async def get_state(self):
        return self.state.state if hasattr(self.state, "state") else self.state


class FakeMessage:
    def __init__(self, text=None) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=77)
        self.answers = []

    async def answer(self, text, **kwargs) -> None:
        self.answers.append((text, kwargs))


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage) -> None:
        self.data = data
        self.message = message
        self.from_user = message.from_user
        self.answers = []

    async def answer(self, text=None, **kwargs) -> None:
        self.answers.append((text, kwargs))


class BoundaryEditorTests(unittest.IsolatedAsyncioTestCase):
    async def test_apartment_position_routes_floor_and_ceiling_without_false_losses(self) -> None:
        message = FakeMessage()

        middle = FakeState(
            {"locale": "ru", "calculation_mode": "quick", "apartment_position": "middle"}
        )
        await boundaries._advance_after_openings(message, middle)
        self.assertEqual(middle.data["floor_boundary"], "heated")
        self.assertEqual(middle.data["ceiling_boundary"], "heated")
        self.assertEqual(middle.state, Survey.air_changes)

        last = FakeState(
            {"locale": "ru", "calculation_mode": "quick", "apartment_position": "last"}
        )
        await boundaries._advance_after_openings(message, last)
        self.assertEqual(last.data["floor_boundary"], "heated")
        self.assertEqual(last.state, Survey.ceiling_boundary)

        first = FakeState(
            {"locale": "ru", "calculation_mode": "quick", "apartment_position": "first"}
        )
        await boundaries._advance_after_openings(message, first)
        self.assertEqual(first.data["ceiling_boundary"], "heated")
        self.assertEqual(first.state, Survey.floor_boundary)

        advanced = FakeState(
            {"locale": "ru", "calculation_mode": "advanced", "apartment_position": "middle"}
        )
        await boundaries._advance_after_openings(message, advanced)
        self.assertEqual(advanced.data["active_surface"], "floor")
        self.assertEqual(advanced.data["active_boundary"], "heated")
        self.assertEqual(advanced.state, Survey.surface_adjacent_mode)

    async def test_boundary_callbacks_reject_unknown_values_and_route_valid_choices(self) -> None:
        message = FakeMessage()
        state = FakeState({"locale": "ru", "calculation_mode": "quick"})

        invalid_floor = FakeCallback("floor:void", message)
        await boundaries.floor_boundary(invalid_floor, state)
        self.assertTrue(invalid_floor.answers[-1][1]["show_alert"])

        await boundaries.floor_boundary(FakeCallback("floor:heated", message), state)
        self.assertEqual(state.data["active_boundary"], "heated")
        self.assertEqual(state.state, Survey.surface_adjacent_mode)

        invalid_ceiling = FakeCallback("ceiling:ground", message)
        await boundaries.ceiling_boundary(invalid_ceiling, state)
        self.assertTrue(invalid_ceiling.answers[-1][1]["show_alert"])

        await boundaries.ceiling_boundary(FakeCallback("ceiling:unheated", message), state)
        self.assertEqual(state.data["active_surface"], "ceiling")
        self.assertEqual(state.data["active_boundary"], "unheated")

    async def test_adjacent_modes_validate_surface_mode_and_manual_temperature(self) -> None:
        message = FakeMessage()
        state = FakeState(
            {
                "locale": "ru",
                "indoor": 24.0,
                "active_surface": "floor",
                "active_boundary": "heated",
                "calculation_mode": "advanced",
            }
        )
        for data in ("adjacent:broken", "adjacent:ceiling:same", "adjacent:floor:zonal"):
            with self.subTest(data=data):
                callback = FakeCallback(data, message)
                await boundaries.surface_adjacent_mode(callback, state)
                self.assertTrue(callback.answers[-1][1]["show_alert"])

        with patch.object(boundaries, "_finish_surface", new=AsyncMock()) as finish:
            await boundaries.surface_adjacent_mode(
                FakeCallback("adjacent:floor:same", message), state
            )
        self.assertTrue(state.data["floor_neighbor_done"])
        self.assertIsNone(state.data["floor_adjacent_temperature"])
        finish.assert_awaited_once_with(message, state, "floor")

        await boundaries.surface_adjacent_mode(
            FakeCallback("adjacent:floor:manual", message), state
        )
        self.assertEqual(state.state, Survey.surface_adjacent_temperature)
        self.assertEqual(state.data["floor_ground_method"], "temperature")

        for value in ("nan", "24", "30"):
            with self.subTest(value=value):
                invalid = FakeMessage(value)
                await boundaries.surface_adjacent_temperature(invalid, state)
                self.assertEqual(state.state, Survey.surface_adjacent_temperature)
                self.assertIn("Попробуйте", invalid.answers[-1][0])

        valid = FakeMessage("18")
        await boundaries.surface_adjacent_temperature(valid, state)
        self.assertEqual(state.data["floor_adjacent_temperature"], 18.0)
        self.assertTrue(state.data["floor_neighbor_done"])
        self.assertEqual(state.state, Survey.surface_material)

    async def test_ground_geometry_and_construction_reject_stale_callbacks(self) -> None:
        message = FakeMessage()
        state = FakeState({"locale": "ru"})
        for data in ("gsides:q", "gsides:n,n"):
            with self.subTest(data=data):
                callback = FakeCallback(data, message)
                await boundaries.ground_exterior_sides(callback, state)
                self.assertTrue(callback.answers[-1][1]["show_alert"])

        invalid_construction = FakeCallback("ground_floor:floating", message)
        await boundaries.ground_floor_construction(invalid_construction, state)
        self.assertTrue(invalid_construction.answers[-1][1]["show_alert"])

        await boundaries.ground_exterior_sides(FakeCallback("gsides:n,w", message), state)
        self.assertEqual(state.data["ground_exterior_sides"], ["north", "west"])
        self.assertEqual(state.state, Survey.ground_floor_construction)
        await boundaries.ground_floor_construction(
            FakeCallback("ground_floor:joists", message), state
        )
        self.assertTrue(state.data["floor_on_joists"])
        self.assertEqual(state.state, Survey.surface_insulated)

    async def test_quick_custom_surface_and_insulation_validate_each_numeric_input(self) -> None:
        message = FakeMessage()
        state = FakeState(
            {"locale": "ru", "calculation_mode": "quick", "active_surface": "floor"}
        )

        invalid_material = FakeCallback("smat:missing", message)
        await boundaries.surface_material(invalid_material, state)
        self.assertTrue(invalid_material.answers[-1][1]["show_alert"])

        await boundaries.surface_material(FakeCallback("smat:custom", message), state)
        self.assertEqual(state.state, Survey.surface_custom_lambda)
        for value in ("nan", "0,001"):
            invalid = FakeMessage(value)
            await boundaries.surface_custom_lambda(invalid, state)
            self.assertIn("Попробуйте", invalid.answers[-1][0])
        await boundaries.surface_custom_lambda(FakeMessage("0,16"), state)
        self.assertEqual(state.data["floor_conductivity"], 0.16)

        for value in ("0", "201"):
            invalid = FakeMessage(value)
            await boundaries.surface_thickness(invalid, state)
            self.assertIn("Попробуйте", invalid.answers[-1][0])
        await boundaries.surface_thickness(FakeMessage("20"), state)
        self.assertEqual(state.data["floor_thickness"], 0.2)
        self.assertEqual(state.state, Survey.surface_insulated)

        invalid_choice = FakeCallback("sins:maybe", message)
        await boundaries.surface_insulated(invalid_choice, state)
        self.assertTrue(invalid_choice.answers[-1][1]["show_alert"])
        await boundaries.surface_insulated(FakeCallback("sins:yes", message), state)

        invalid_insulation = FakeCallback("simat:brick_solid", message)
        await boundaries.surface_insulation_material(invalid_insulation, state)
        self.assertTrue(invalid_insulation.answers[-1][1]["show_alert"])
        await boundaries.surface_insulation_material(FakeCallback("simat:custom", message), state)
        self.assertEqual(state.state, Survey.surface_insulation_custom_lambda)
        await boundaries.surface_insulation_custom_lambda(FakeMessage("0,035"), state)
        self.assertEqual(state.data["floor_insulation_conductivity"], 0.035)

        invalid_thickness = FakeMessage("bad")
        await boundaries.surface_insulation_thickness(invalid_thickness, state)
        self.assertIn("Попробуйте", invalid_thickness.answers[-1][0])
        with patch.object(boundaries, "_finish_surface", new=AsyncMock()) as finish:
            await boundaries.surface_insulation_thickness(FakeMessage("10"), state)
        self.assertEqual(state.data["floor_insulation_thickness"], 0.1)
        finish.assert_awaited_once()

    async def test_multilayer_editor_rejects_unknown_and_corrupt_pending_layer(self) -> None:
        message = FakeMessage()
        state = FakeState(
            {
                "locale": "ru",
                "calculation_mode": "advanced",
                "active_surface": "floor",
                "floor_layers": [{"material": "concrete", "thickness_m": 0.2}],
            }
        )
        invalid_action = FakeCallback("slayer:replace", message)
        await boundaries.surface_layer_action(invalid_action, state)
        self.assertTrue(invalid_action.answers[-1][1]["show_alert"])

        invalid_material = FakeCallback("slmat:missing", message)
        await boundaries.surface_layer_material(invalid_material, state)
        self.assertTrue(invalid_material.answers[-1][1]["show_alert"])

        legacy_material = FakeCallback("slmat:pu_foam", message)
        await boundaries.surface_layer_material(legacy_material, state)
        self.assertTrue(legacy_material.answers[-1][1]["show_alert"])

        invalid_lambda = FakeMessage("inf")
        await boundaries.surface_layer_custom_lambda(invalid_lambda, state)
        self.assertIn("Попробуйте", invalid_lambda.answers[-1][0])

        state.data["surface_pending_material"] = "missing"
        corrupt = FakeMessage("5")
        await boundaries.surface_layer_thickness(corrupt, state)
        self.assertIn("повреждены", corrupt.answers[-1][0])

        state.data["surface_pending_material"] = "wood"
        state.data["floor_layers"] = [
            {"material": "concrete", "thickness_m": 0.1} for _ in range(10)
        ]
        over_limit = FakeMessage("5")
        await boundaries.surface_layer_thickness(over_limit, state)
        self.assertIn("10 слоёв", over_limit.answers[-1][0])

    async def test_advanced_floor_builds_multiple_layers_with_buttons(self) -> None:
        message = FakeMessage()
        state = FakeState({"locale": "ru", "calculation_mode": "advanced"})

        await boundaries.floor_boundary(FakeCallback("floor:outdoor", message), state)
        self.assertEqual(state.state, Survey.surface_material)
        await boundaries.surface_material(FakeCallback("smat:concrete", message), state)
        await boundaries.surface_thickness(FakeMessage("20"), state)

        self.assertEqual(state.state, Survey.surface_layer_action)
        self.assertEqual(
            state.data["floor_layers"],
            [
                {
                    "material": "concrete",
                    "material_conductivity": None,
                    "thickness_m": 0.2,
                }
            ],
        )

        await boundaries.surface_layer_action(FakeCallback("slayer:add", message), state)
        self.assertEqual(state.state, Survey.surface_layer_material)
        await boundaries.surface_layer_material(
            FakeCallback("slmat:mineral_wool", message), state
        )
        await boundaries.surface_layer_thickness(FakeMessage("12"), state)
        self.assertEqual(len(state.data["floor_layers"]), 2)
        self.assertEqual(state.data["floor_layers"][1]["material"], "mineral_wool")

        await boundaries.surface_layer_action(FakeCallback("slayer:finish", message), state)
        self.assertEqual(state.state, Survey.ceiling_boundary)

        await boundaries.ceiling_boundary(FakeCallback("ceiling:outdoor", message), state)
        await boundaries.surface_material(FakeCallback("smat:wood", message), state)
        await boundaries.surface_thickness(FakeMessage("5"), state)
        await boundaries.surface_layer_action(FakeCallback("slayer:finish", message), state)
        self.assertEqual(state.state, Survey.air_changes)
        self.assertEqual(state.data["ceiling_layers"][0]["material"], "wood")

    async def test_custom_layer_and_resume_are_localized(self) -> None:
        message = FakeMessage()
        state = FakeState(
            {
                "locale": "uz",
                "calculation_mode": "advanced",
                "active_surface": "ceiling",
                "ceiling_layers": [
                    {
                        "material": "wood",
                        "material_conductivity": None,
                        "thickness_m": 0.05,
                    }
                ],
            },
            Survey.surface_layer_material,
        )
        self.assertTrue(await boundaries.render_boundary_step(message, state))
        self.assertIn("Keyingi qatlam materiali", message.answers[-1][0])

        await boundaries.surface_layer_material(FakeCallback("slmat:custom", message), state)
        custom_lambda = FakeMessage("0,037")
        await boundaries.surface_layer_custom_lambda(custom_lambda, state)
        self.assertEqual(state.state, Survey.surface_layer_thickness)
        thickness = FakeMessage("7,5")
        await boundaries.surface_layer_thickness(thickness, state)
        layer = state.data["ceiling_layers"][-1]
        self.assertEqual(layer["material"], "custom")
        self.assertAlmostEqual(layer["material_conductivity"], 0.037)
        self.assertAlmostEqual(layer["thickness_m"], 0.075)
        self.assertIn("2 ta qatlam", thickness.answers[-1][0])

    async def test_quick_mode_keeps_simple_insulation_flow(self) -> None:
        message = FakeMessage()
        state = FakeState({"locale": "ru", "calculation_mode": "quick"})
        await boundaries.floor_boundary(FakeCallback("floor:outdoor", message), state)
        await boundaries.surface_material(FakeCallback("smat:concrete", message), state)
        await boundaries.surface_thickness(FakeMessage("18"), state)
        self.assertEqual(state.state, Survey.surface_insulated)
        self.assertIsNone(state.data["floor_layers"])

    async def test_boundary_change_clears_stale_adjacent_temperature(self) -> None:
        message = FakeMessage()
        state = FakeState(
            {
                "locale": "ru",
                "floor_adjacent_temperature": 8.0,
                "floor_neighbor_done": True,
                "floor_ground_method": "zonal",
                "ground_exterior_sides": ["north"],
                "floor_on_joists": True,
                "ceiling_adjacent_temperature": 5.0,
                "ceiling_neighbor_done": True,
            }
        )
        await boundaries.floor_boundary(FakeCallback("floor:outdoor", message), state)
        self.assertIsNone(state.data["floor_adjacent_temperature"])
        self.assertIsNone(state.data["floor_ground_method"])
        self.assertIsNone(state.data["ground_exterior_sides"])
        self.assertFalse(state.data["floor_neighbor_done"])
        self.assertFalse(state.data["floor_on_joists"])

        await boundaries.ceiling_boundary(FakeCallback("ceiling:outdoor", message), state)
        self.assertIsNone(state.data["ceiling_adjacent_temperature"])
        self.assertFalse(state.data["ceiling_neighbor_done"])

    async def test_editor_rejects_stale_action_and_eleventh_layer(self) -> None:
        message = FakeMessage()
        state = FakeState({"locale": "ru", "calculation_mode": "quick"})
        stale = FakeCallback("slayer:add", message)
        await boundaries.surface_layer_action(stale, state)
        self.assertTrue(stale.answers[-1][1]["show_alert"])

        state.data.update(
            {
                "calculation_mode": "advanced",
                "active_surface": "floor",
                "floor_layers": [
                    {"material": "concrete", "thickness_m": 0.1}
                    for _ in range(10)
                ],
            }
        )
        limit = FakeCallback("slayer:add", message)
        await boundaries.surface_layer_action(limit, state)
        self.assertTrue(limit.answers[-1][1]["show_alert"])
        self.assertIn("10", limit.answers[-1][0])


class BoundaryLayerMappingTests(unittest.TestCase):
    def test_explicit_layers_override_legacy_surface_fields(self) -> None:
        layers = _surface_layers(
            {
                "floor_material": "concrete",
                "floor_thickness": 0.5,
                "floor_layers": [
                    {"material": "wood", "thickness_m": 0.04},
                    {
                        "material": "custom",
                        "material_conductivity": 0.031,
                        "thickness_m": 0.12,
                    },
                ],
            },
            "floor",
        )
        self.assertEqual([layer.material_key for layer in layers], ["wood", "custom"])
        self.assertAlmostEqual(layers[1].conductivity_w_mk, 0.031)

    def test_explicit_layer_payload_is_strictly_validated(self) -> None:
        with self.assertRaisesRegex(InvalidCalculationData, "от 1 до 10"):
            _surface_layers({"ceiling_layers": []}, "ceiling")
        with self.assertRaisesRegex(InvalidCalculationData, "должен быть объектом"):
            _surface_layers({"ceiling_layers": ["concrete"]}, "ceiling")


if __name__ == "__main__":
    unittest.main()
