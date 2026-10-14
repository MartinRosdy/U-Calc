import unittest
from types import SimpleNamespace

from u_calc.handlers import opening_editor
from u_calc.states import Survey


class FakeState:
    def __init__(self, data=None) -> None:
        self.data = dict(data or {})
        self.state = None

    async def get_data(self) -> dict:
        return dict(self.data)

    async def update_data(self, **values) -> None:
        self.data.update(values)

    async def set_state(self, state) -> None:
        self.state = state

    async def get_state(self):
        return getattr(self.state, "state", self.state)


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


class OpeningEditorTests(unittest.IsolatedAsyncioTestCase):
    async def test_uzbek_editor_happy_path_and_navigation_are_localized(self) -> None:
        state = FakeState(
            {
                "locale": "uz",
                "window_count": 1,
                "wall_gross_area": 10.0,
                "wall_groups": [],
            }
        )
        first = FakeMessage()
        await opening_editor.start_editor(first, state, "window")
        self.assertIn("derazalar guruhi nomi", first.answers[-1][0])

        invalid = FakeMessage("")
        await opening_editor.opening_name(invalid, state)
        self.assertIn("1 dan 60", invalid.answers[-1][0])
        self.assertIn("Qayta urinib", invalid.answers[-1][0])

        name = FakeMessage("Oyna")
        await opening_editor.opening_name(name, state)
        self.assertIn("bir xil tirqishlar", name.answers[-1][0])
        count = FakeMessage("1")
        await opening_editor.opening_count(count, state)
        self.assertIn("eni × balandligi", count.answers[-1][0])
        dimensions = FakeMessage("1x1,5")
        await opening_editor.opening_dimensions(dimensions, state)
        self.assertIn("pasportdagi U", dimensions.answers[-1][0])
        u_value = FakeMessage("1,1")
        await opening_editor.opening_u_value(u_value, state)
        text, kwargs = u_value.answers[-1]
        self.assertIn("Saqlangan derazalar guruhlari", text)
        button_texts = [
            button.text for row in kwargs["reply_markup"].inline_keyboard for button in row
        ]
        self.assertIn("⬅️ Orqaga", button_texts)
        self.assertIn("✖️ Bekor qilish", button_texts)

    async def test_window_groups_are_built_without_pipe_syntax(self) -> None:
        state = FakeState(
            {
                "window_count": 3,
                "wall_gross_area": 30.0,
                "wall_groups": [
                    {"name": "Север", "gross_area_m2": 18.0},
                    {"name": "Торец", "gross_area_m2": 12.0},
                ],
            }
        )
        message = FakeMessage()
        await opening_editor.start_editor(message, state, "window")
        await opening_editor.opening_name(FakeMessage("ПВХ"), state)
        await opening_editor.opening_count(FakeMessage("2"), state)
        await opening_editor.opening_dimensions(FakeMessage("1x1,5"), state)
        await opening_editor.opening_u_value(FakeMessage("1,1"), state)
        await opening_editor.opening_wall(FakeCallback("oewall:0", message), state)
        await opening_editor.opening_action(FakeCallback("oedit:add", message), state)
        await opening_editor.opening_name(FakeMessage("Кухня"), state)
        await opening_editor.opening_count(FakeMessage("1"), state)
        await opening_editor.opening_dimensions(FakeMessage("1,2x1,4"), state)
        await opening_editor.opening_u_value(FakeMessage("1,4"), state)
        await opening_editor.opening_wall(FakeCallback("oewall:none", message), state)
        await opening_editor.opening_action(FakeCallback("oedit:finish", message), state)

        self.assertEqual(state.state, Survey.door_count)
        self.assertEqual(len(state.data["window_groups"]), 2)
        self.assertEqual(state.data["window_groups"][0]["wall_name"], "Север")
        self.assertAlmostEqual(state.data["window_area"], 4.68)

    async def test_specific_opening_group_can_be_replaced_and_deleted(self) -> None:
        groups = [
            {
                "name": "Север",
                "count": 1,
                "width_m": 1.0,
                "height_m": 1.0,
                "area_m2": 1.0,
                "u_value": 1.2,
                "wall_name": None,
            },
            {
                "name": "Юг",
                "count": 1,
                "width_m": 1.0,
                "height_m": 1.0,
                "area_m2": 1.0,
                "u_value": 1.4,
                "wall_name": None,
            },
        ]
        state = FakeState(
            {
                "opening_editor_kind": "window",
                "opening_editor_edit_index": None,
                "window_count": 2,
                "window_groups": groups,
                "wall_groups": [],
                "wall_gross_area": 20.0,
            }
        )
        message = FakeMessage()

        await opening_editor.opening_action(FakeCallback("oedit:edit:0", message), state)
        self.assertEqual(
            [item["name"] for item in state.data["window_groups"]],
            ["Север", "Юг"],
        )
        duplicate = FakeMessage("юг")
        await opening_editor.opening_name(duplicate, state)
        self.assertIn("уже", duplicate.answers[-1][0])
        self.assertEqual(state.state, Survey.opening_editor_name)
        await opening_editor.opening_name(FakeMessage("Север новый"), state)
        await opening_editor.opening_count(FakeMessage("1"), state)
        await opening_editor.opening_dimensions(FakeMessage("1,2x1"), state)
        await opening_editor.opening_u_value(FakeMessage("1,1"), state)
        self.assertEqual(
            [item["name"] for item in state.data["window_groups"]],
            ["Север новый", "Юг"],
        )

        await opening_editor.opening_action(FakeCallback("oedit:delete:1", message), state)
        self.assertEqual(
            [item["name"] for item in state.data["window_groups"]], ["Север новый"]
        )

        stale = FakeCallback("oedit:edit:9", message)
        await opening_editor.opening_action(stale, state)
        self.assertTrue(stale.answers[-1][1]["show_alert"])

    async def test_opening_editor_rejects_negative_indexes_without_mutation(self) -> None:
        original = [
            {
                "name": "Север",
                "count": 1,
                "width_m": 1.0,
                "height_m": 1.0,
                "area_m2": 1.0,
                "u_value": 1.2,
                "wall_name": None,
            }
        ]
        state = FakeState(
            {
                "opening_editor_kind": "window",
                "window_count": 1,
                "window_groups": list(original),
            }
        )
        message = FakeMessage()

        for action in ("oedit:edit:-1", "oedit:delete:-1"):
            callback = FakeCallback(action, message)
            await opening_editor.opening_action(callback, state)
            self.assertTrue(callback.answers[-1][1]["show_alert"])
            self.assertEqual(state.data["window_groups"], original)

    async def test_unassigned_opening_area_error_is_shown_inline(self) -> None:
        state = FakeState(
            {
                "locale": "ru",
                "opening_editor_kind": "window",
                "opening_editor_edit_index": None,
                "window_count": 1,
                "window_groups": [],
                "wall_groups": [],
                "wall_gross_area": 1.0,
                "opening_editor_name": "Большое окно",
                "opening_editor_count": 1,
                "opening_editor_width": 2.0,
                "opening_editor_height": 1.0,
            }
        )
        message = FakeMessage("1,2")
        await opening_editor.opening_u_value(message, state)

        self.assertIn("площадь проёмов", message.answers[-1][0])
        self.assertEqual(state.state, None)
        self.assertEqual(state.data["window_groups"], [])

    async def test_door_editor_checks_capacity_of_selected_wall(self) -> None:
        state = FakeState(
            {
                "door_count": 1,
                "window_area": 2.0,
                "wall_gross_area": 10.0,
                "wall_groups": [
                    {"name": "Север", "gross_area_m2": 3.0},
                    {"name": "Юг", "gross_area_m2": 7.0},
                ],
                "window_groups": [
                    {"name": "Окно", "count": 1, "area_m2": 2.0, "wall_name": "Север"}
                ],
                "calculation_mode": "quick",
                "apartment_position": None,
            }
        )
        message = FakeMessage()
        await opening_editor.start_editor(message, state, "door")
        await opening_editor.opening_name(FakeMessage("Входная"), state)
        await opening_editor.opening_count(FakeMessage("1"), state)
        await opening_editor.opening_dimensions(FakeMessage("1x2"), state)
        await opening_editor.opening_u_value(FakeMessage("1,4"), state)
        too_small = FakeCallback("oewall:0", message)
        await opening_editor.opening_wall(too_small, state)
        self.assertTrue(too_small.answers[-1][1]["show_alert"])
        await opening_editor.opening_wall(FakeCallback("oewall:1", message), state)
        await opening_editor.opening_action(FakeCallback("oedit:finish", message), state)

        self.assertEqual(state.state, Survey.floor_boundary)
        self.assertEqual(state.data["door_groups"][0]["wall_name"], "Юг")

    async def test_editor_rejects_invalid_input_and_incomplete_groups(self) -> None:
        state = FakeState({"window_count": 2, "wall_gross_area": 10.0})
        message = FakeMessage()
        with self.assertRaises(ValueError):
            await opening_editor.start_editor(message, state, "rooflight")
        await opening_editor.start_editor(message, state, "window")

        invalid_name = FakeMessage("")
        await opening_editor.opening_name(invalid_name, state)
        self.assertIn("Название", invalid_name.answers[-1][0])
        await opening_editor.opening_name(FakeMessage("Окна"), state)
        invalid_count = FakeMessage("два")
        await opening_editor.opening_count(invalid_count, state)
        self.assertIn("целое", invalid_count.answers[-1][0])
        too_many = FakeMessage("3")
        await opening_editor.opening_count(too_many, state)
        self.assertIn("от 1 до 2", too_many.answers[-1][0])
        await opening_editor.opening_count(FakeMessage("1"), state)
        invalid_dimensions = FakeMessage("широкое")
        await opening_editor.opening_dimensions(invalid_dimensions, state)
        self.assertIn("пару размеров", invalid_dimensions.answers[-1][0])
        await opening_editor.opening_dimensions(FakeMessage("1x1"), state)
        invalid_u = FakeMessage("9")
        await opening_editor.opening_u_value(invalid_u, state)
        self.assertIn("от 0,1 до 8", invalid_u.answers[-1][0])
        await opening_editor.opening_u_value(FakeMessage("1"), state)

        incomplete = FakeCallback("oedit:finish", message)
        await opening_editor.opening_action(incomplete, state)
        self.assertTrue(incomplete.answers[-1][1]["show_alert"])
        await opening_editor.opening_action(FakeCallback("oedit:delete", message), state)
        self.assertEqual(state.state, Survey.opening_editor_name)

    async def test_editor_handles_stale_wall_and_renders_restored_steps(self) -> None:
        state = FakeState(
            {
                "window_count": 1,
                "wall_gross_area": 10.0,
                "wall_groups": [{"name": "Стена", "gross_area_m2": 10.0}],
                "opening_editor_kind": "window",
                "window_groups": [],
            }
        )
        message = FakeMessage()
        await opening_editor._ask_name(message, state)
        await opening_editor.opening_name(FakeMessage("Окно"), state)
        await opening_editor.opening_count(FakeMessage("1"), state)
        await opening_editor.opening_dimensions(FakeMessage("1x1"), state)
        await opening_editor.opening_u_value(FakeMessage("1"), state)
        stale = FakeCallback("oewall:99", message)
        await opening_editor.opening_wall(stale, state)
        self.assertTrue(stale.answers[-1][1]["show_alert"])

        for editor_state in (
            Survey.opening_editor_name,
            Survey.opening_editor_count,
            Survey.opening_editor_dimensions,
            Survey.opening_editor_u_value,
            Survey.opening_editor_wall,
        ):
            await state.set_state(editor_state)
            self.assertTrue(await opening_editor.render_editor_step(message, state))
        await state.set_state(Survey.indoor)
        self.assertFalse(await opening_editor.render_editor_step(message, state))


if __name__ == "__main__":
    unittest.main()
