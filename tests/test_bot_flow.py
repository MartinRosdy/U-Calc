import unittest

from u_calc.bot import (
    Survey,
    _advance_after_openings,
    _ask_adjacent_mode,
    _go_back,
    _send_long_message,
    climate,
    confirmation,
    safety_factor,
    wall_material,
)


class FakeState:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.state = None

    async def get_data(self) -> dict:
        return dict(self.data)

    async def update_data(self, **values) -> None:
        self.data.update(values)

    async def set_state(self, state) -> None:
        self.state = state

    async def set_data(self, data: dict) -> None:
        self.data = dict(data)


class FakeMessage:
    def __init__(self) -> None:
        self.answers = []

    async def answer(self, text, **kwargs) -> None:
        self.answers.append((text, kwargs))


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage) -> None:
        self.data = data
        self.message = message
        self.answers = []

    async def answer(self, text=None, **kwargs) -> None:
        self.answers.append((text, kwargs))


class ApartmentFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_safety_opens_confirmation_card_before_calculation(self) -> None:
        state = FakeState(
            {
                "building_type": "house",
                "climate_key": "manual",
                "outdoor": -15,
                "indoor": 24,
                "length": 10,
                "width": 8,
                "height": 3,
                "wall_gross_area": 80,
                "window_area": 8,
                "door_area": 2,
                "air_changes": 0.5,
            }
        )
        message = FakeMessage()
        callback = FakeCallback("safety:1.10", message)
        await safety_factor(callback, state)
        self.assertEqual(state.state, Survey.confirmation)
        self.assertIn("Проверьте исходные данные", message.answers[-1][0])
        buttons = [
            button.text
            for row in message.answers[-1][1]["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertEqual(
            buttons,
            [
                "Рассчитать",
                "Изменить климат",
                "Изменить стены",
                "Изменить проёмы",
                "Изменить пол/потолок",
                "Изменить вентиляцию",
                "✖️ Отменить",
            ],
        )

    async def test_confirmation_can_return_to_wall_editor(self) -> None:
        state = FakeState({})
        message = FakeMessage()
        await confirmation(FakeCallback("confirm:walls", message), state, None)
        self.assertEqual(state.state, Survey.wall_method)

    async def test_back_restores_previous_state_and_answers(self) -> None:
        state = FakeState(
            {
                "indoor": 24,
                "length": 10,
                "_back_stack": [{"state": Survey.indoor.state, "data": {"outdoor": -14}}],
            }
        )
        state.state = Survey.dimensions

        self.assertTrue(await _go_back(state))
        self.assertEqual(state.state, Survey.indoor.state)
        self.assertEqual(state.data, {"outdoor": -14, "_back_stack": []})

    async def test_unknown_callbacks_are_rejected_without_state_corruption(self) -> None:
        state = FakeState({})
        message = FakeMessage()
        climate_callback = FakeCallback("climate:not-real", message)
        await climate(climate_callback, state)
        self.assertEqual(state.data, {})
        self.assertTrue(climate_callback.answers[0][1]["show_alert"])

        material_callback = FakeCallback("mat:not-real", message)
        await wall_material(material_callback, state)
        self.assertNotIn("wall_material", state.data)
        self.assertTrue(material_callback.answers[0][1]["show_alert"])

    async def test_ground_floor_offers_normative_zonal_method_first(self) -> None:
        state = FakeState({})
        message = FakeMessage()
        await _ask_adjacent_mode(message, state, "floor", "ground")
        self.assertEqual(state.state, Survey.surface_adjacent_mode)
        keyboard = message.answers[0][1]["reply_markup"]
        buttons = [button for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(buttons[0].callback_data, "adjacent:floor:zonal")
        self.assertIn("ШНҚ", buttons[0].text)

    async def test_middle_floor_skips_both_envelope_questions(self) -> None:
        state = FakeState({"apartment_position": "middle"})
        message = FakeMessage()
        await _advance_after_openings(message, state)
        self.assertEqual(state.data["floor_boundary"], "heated")
        self.assertEqual(state.data["ceiling_boundary"], "heated")
        self.assertEqual(state.state, Survey.air_changes)

    async def test_first_floor_only_asks_about_floor(self) -> None:
        state = FakeState({"apartment_position": "first"})
        message = FakeMessage()
        await _advance_after_openings(message, state)
        self.assertEqual(state.data["ceiling_boundary"], "heated")
        self.assertEqual(state.state, Survey.floor_boundary)

    async def test_last_floor_only_asks_about_ceiling(self) -> None:
        state = FakeState({"apartment_position": "last"})
        message = FakeMessage()
        await _advance_after_openings(message, state)
        self.assertEqual(state.data["floor_boundary"], "heated")
        self.assertEqual(state.state, Survey.ceiling_boundary)

    async def test_long_reports_are_split_without_data_loss(self) -> None:
        message = FakeMessage()
        original = "\n".join(f"Строка {index}: " + "x" * 40 for index in range(30))
        await _send_long_message(message, original, limit=200)
        self.assertGreater(len(message.answers), 1)
        reconstructed = "\n".join(answer[0] for answer in message.answers)
        self.assertEqual(reconstructed, original)
        self.assertTrue(all(len(answer[0]) <= 200 for answer in message.answers))
