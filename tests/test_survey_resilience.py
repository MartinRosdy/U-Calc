import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from u_calc.calculator import calculate_heat_loss
from u_calc.config import Settings
from u_calc.handlers import bridge_editor, survey, wall_editor
from u_calc.handlers import history as history_handlers
from u_calc.models import Building, Layer, OpaqueSurface
from u_calc.report import format_report
from u_calc.services.building_factory import InvalidCalculationData
from u_calc.services.calculation_service import CalculationBundle
from u_calc.states import Survey
from u_calc.storage import CalculationRepository


class FakeState:
    def __init__(self, data=None, state=None) -> None:
        self.data = dict(data or {})
        self.state = state

    async def get_data(self) -> dict:
        return dict(self.data)

    async def set_data(self, data: dict) -> None:
        self.data = dict(data)

    async def update_data(self, **values) -> None:
        self.data.update(values)

    async def set_state(self, state) -> None:
        self.state = state

    async def clear(self) -> None:
        self.data.clear()
        self.state = None


class FakeMessage:
    def __init__(self, text=None, user_id=77) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []
        self.documents = []

    async def answer(self, text, **kwargs) -> None:
        self.answers.append((text, kwargs))

    async def answer_document(self, document, **kwargs) -> None:
        self.documents.append((document, kwargs))


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage) -> None:
        self.data = data
        self.message = message
        self.from_user = message.from_user
        self.answers = []

    async def answer(self, text=None, **kwargs) -> None:
        self.answers.append((text, kwargs))


def sample_bundle() -> CalculationBundle:
    building = Building(
        indoor_temperature_c=24,
        outdoor_temperature_c=-14,
        volume_m3=100,
        opaque_surfaces=(OpaqueSurface("Стена", 20, (Layer("aerated_d500", 0.3),)),),
        air_changes_per_hour=0.5,
    )
    result = calculate_heat_loss(building)
    return CalculationBundle(building, result, None, None, format_report(building, result))


class SurveyCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = CalculationRepository(Path(self.temp.name) / "survey.db")
        self.repository.initialize()
        self.state = FakeState()
        self.message = FakeMessage()

    def tearDown(self) -> None:
        self.temp.cleanup()

    async def test_uzbek_primary_wizard_path_is_localized(self) -> None:
        self.repository.set_locale(77, "uz")
        await survey.start(self.message, self.state, self.repository)
        self.assertIn("tafsi", self.message.answers[-1][0])
        await survey.calculation_mode(FakeCallback("mode:quick", self.message), self.state)
        self.assertIn("Nimani", self.message.answers[-1][0])
        await survey.building_type(FakeCallback("type:house", self.message), self.state)
        self.assertIn("obyekt nomi", self.message.answers[-1][0])
        object_message = FakeMessage("Yunusobod", 77)
        await survey.object_name(object_message, self.state)
        self.assertIn("iqlim", object_message.answers[-1][0])
        await survey.climate(FakeCallback("climate:manual", self.message), self.state)
        self.assertIn("tashqi harorat", self.message.answers[-1][0])
        outdoor_message = FakeMessage("-10", 77)
        await survey.custom_outdoor(outdoor_message, self.state)
        self.assertIn("Ichkarida", outdoor_message.answers[-1][0])
        indoor_message = FakeMessage("24", 77)
        await survey.indoor(indoor_message, self.state)
        self.assertIn("geometriya", indoor_message.answers[-1][0])
        dimensions_message = FakeMessage("10 8 3", 77)
        await survey.dimensions(dimensions_message, self.state)
        self.assertIn("devorlar", dimensions_message.answers[-1][0])
        navigation = [
            button.text
            for row in dimensions_message.answers[-1][1]["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("⬅️ Orqaga", navigation)
        self.assertIn("✖️ Bekor qilish", navigation)

    async def test_uzbek_quick_path_reaches_localized_confirmation(self) -> None:
        self.state.data = {
            "locale": "uz",
            "calculation_mode": "quick",
            "building_type": "apartment",
            "apartment_position": "middle",
            "climate_key": "manual",
            "outdoor": -10.0,
            "indoor": 24.0,
            "length": 10.0,
            "width": 8.0,
            "height": 3.0,
            "volume": 240.0,
            "wall_gross_area": 100.0,
            "profile_defaults": {},
        }
        await survey._ask_wall_material(self.message, self.state)
        self.assertIn("asosiy materiali", self.message.answers[-1][0])

        await survey.wall_material(FakeCallback("mat:brick_solid", self.message), self.state)
        self.assertIn("qalinligi", self.message.answers[-1][0])
        await survey.wall_thickness(FakeMessage("25", 77), self.state)
        await survey.insulated(FakeCallback("ins:no", self.message), self.state)
        self.assertIn("derazalar", self.message.answers[-1][0])

        windows = FakeMessage("0", 77)
        await survey.window_count(windows, self.state)
        self.assertIn("eshiklar", windows.answers[-1][0])
        doors = FakeMessage("0", 77)
        await survey.door_count(doors, self.state)
        self.assertIn("ventilyatsiya", doors.answers[-1][0])

        await survey.air_changes(FakeCallback("ach:0.5", self.message), self.state)
        self.assertIn("Rekuperator", self.message.answers[-1][0])
        await survey.heat_recovery(FakeCallback("recovery:no", self.message), self.state)
        self.assertIn("sovuq ko‘priklari", self.message.answers[-1][0])
        await survey.thermal_bridges(FakeCallback("bridges:0.10", self.message), self.state)
        self.assertIn("ekspluatatsion zaxira", self.message.answers[-1][0])
        await survey.safety_factor(FakeCallback("safety:1.10", self.message), self.state)
        self.assertIn("Hisoblashdan oldin", self.message.answers[-1][0])
        self.assertIn("Obyekt: Kvartira", self.message.answers[-1][0])
        self.assertIn("Iqlim: Harorat qo‘lda kiritilgan", self.message.answers[-1][0])

    async def test_uzbek_house_boundaries_reach_airflow_without_language_leak(self) -> None:
        self.state.data = {
            "locale": "uz",
            "calculation_mode": "quick",
            "building_type": "house",
            "apartment_position": None,
            "indoor": 24.0,
            "outdoor": -10.0,
            "length": 10.0,
            "width": 8.0,
            "height": 3.0,
            "volume": 240.0,
            "profile_defaults": {},
        }
        await survey._advance_after_openings(self.message, self.state)
        self.assertIn("Pol ostida", self.message.answers[-1][0])

        await survey.floor_boundary(FakeCallback("floor:unheated", self.message), self.state)
        self.assertIn("harorati ma’lummi", self.message.answers[-1][0])
        await survey.surface_adjacent_mode(
            FakeCallback("adjacent:floor:estimate", self.message), self.state
        )
        self.assertIn("polning asosiy materiali", self.message.answers[-1][0])
        await survey.surface_material(FakeCallback("smat:concrete", self.message), self.state)
        self.assertIn("qalinligi", self.message.answers[-1][0])
        await survey.surface_thickness(FakeMessage("20", 77), self.state)
        await survey.surface_insulated(FakeCallback("sins:no", self.message), self.state)
        self.assertIn("Shift ustida", self.message.answers[-1][0])

        await survey.ceiling_boundary(FakeCallback("ceiling:unheated", self.message), self.state)
        await survey.surface_adjacent_mode(
            FakeCallback("adjacent:ceiling:estimate", self.message), self.state
        )
        self.assertIn("orayopma/tomning", self.message.answers[-1][0])
        await survey.surface_material(FakeCallback("smat:wood", self.message), self.state)
        await survey.surface_thickness(FakeMessage("15", 77), self.state)
        await survey.surface_insulated(FakeCallback("sins:no", self.message), self.state)
        self.assertIn("ventilyatsiya", self.message.answers[-1][0])

    async def test_uzbek_advanced_airflow_is_localized_and_keeps_flows_separate(self) -> None:
        self.state.data = {
            "locale": "uz",
            "calculation_mode": "advanced",
            "volume": 200.0,
        }
        await survey._ask_air_changes(self.message, self.state)
        self.assertIn("Alohida hisobiy oqimlar", self.message.answers[-1][0])
        buttons = [
            button.text
            for row in self.message.answers[-1][1]["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("Karralilik, 1/soat", buttons)

        await survey.airflow_unit(
            FakeCallback("airflow_unit:ach", self.message), self.state
        )
        self.assertIn("mexanik ventilyatsiya", self.message.answers[-1][0])
        self.assertIn("1/soat", self.message.answers[-1][0])

        mechanical = FakeMessage("0,5", 77)
        await survey.mechanical_ventilation(mechanical, self.state)
        self.assertIn("tabiiy ventilyatsiya", mechanical.answers[-1][0])
        natural = FakeMessage("0,1", 77)
        await survey.natural_ventilation(natural, self.state)
        self.assertIn("infiltratsiya", natural.answers[-1][0])
        infiltration = FakeMessage("0,2", 77)
        await survey.infiltration(infiltration, self.state)
        self.assertIn("rekuperatsiya", infiltration.answers[-1][0])

        await survey.heat_recovery(
            FakeCallback("recovery:yes", self.message), self.state
        )
        self.assertIn("pasportdagi FIK", self.message.answers[-1][0])
        efficiency = FakeMessage("70", 77)
        await survey.heat_recovery_efficiency(efficiency, self.state)
        self.assertIn("sovuq ko‘priklari", efficiency.answers[-1][0])
        self.assertEqual(self.state.data["mechanical_ventilation_m3_h"], 100.0)
        self.assertEqual(self.state.data["natural_ventilation_m3_h"], 20.0)
        self.assertEqual(self.state.data["infiltration_m3_h"], 40.0)
        self.assertEqual(self.state.data["heat_recovery_efficiency"], 0.7)

    async def test_uzbek_neighbor_ground_zoning_and_validation_are_localized(self) -> None:
        self.state.data = {"locale": "uz", "active_boundary": "ground"}
        await survey._ask_heated_neighbor_mode(self.message, self.state, "floor")
        self.assertIn("pastdagi qo‘shni", self.message.answers[-1][0])
        neighbor_buttons = [
            button.text
            for row in self.message.answers[-1][1]["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("Bir xil — yo‘qotish yo‘q", neighbor_buttons)

        await survey._ask_ground_exterior_sides(self.message, self.state)
        self.assertIn("qaysi tomonlari", self.message.answers[-1][0])
        side_buttons = [
            button.text
            for row in self.message.answers[-1][1]["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("Barcha 4 tomon", side_buttons)
        self.assertIn("Murakkab reja", side_buttons)

        complex_callback = FakeCallback("gsides:complex", self.message)
        await survey.ground_exterior_sides(complex_callback, self.state)
        self.assertIn("murakkab konturni", self.message.answers[-1][0])

        await survey.ground_exterior_sides(
            FakeCallback("gsides:n,e", self.message), self.state
        )
        self.assertIn("Grunt ustidagi pol konstruksiyasi", self.message.answers[-1][0])
        await survey.ground_floor_construction(
            FakeCallback("ground_floor:solid", self.message), self.state
        )
        self.assertIn("izolyatsiya qatlami", self.message.answers[-1][0])

        invalid = FakeMessage("not-a-number", 77)
        await survey.surface_insulation_thickness(invalid, self.state)
        self.assertIn("Kiritilgan qiymatni tekshiring", invalid.answers[-1][0])
        self.assertNotIn("Введите", invalid.answers[-1][0])

    async def test_uzbek_simple_window_and_door_path_is_localized(self) -> None:
        self.state.data = {
            "locale": "uz",
            "calculation_mode": "quick",
            "apartment_position": "middle",
            "wall_gross_area": 80.0,
            "volume": 200.0,
            "profile_defaults": {},
        }
        windows = FakeMessage("2", 77)
        await survey.window_count(windows, self.state)
        self.assertIn("Derazalarni", windows.answers[-1][0])
        await survey.window_method(FakeCallback("window_method:area", self.message), self.state)
        self.assertIn("umumiy maydoni", self.message.answers[-1][0])
        window_area = FakeMessage("4", 77)
        await survey.window_area(window_area, self.state)
        self.assertIn("Deraza turi", window_area.answers[-1][0])
        await survey.window_type(FakeCallback("window:double", self.message), self.state)
        self.assertIn("eshiklar", self.message.answers[-1][0])

        doors = FakeMessage("1", 77)
        await survey.door_count(doors, self.state)
        self.assertIn("eshiklarni", doors.answers[-1][0])
        await survey.door_method(FakeCallback("door_method:area", self.message), self.state)
        door_area = FakeMessage("2", 77)
        await survey.door_area(door_area, self.state)
        self.assertIn("Eshik turi", door_area.answers[-1][0])

    async def test_help_history_report_copy_and_compare_commands(self) -> None:
        await history_handlers.help_command(self.message)
        self.assertIn("/new", self.message.answers[-1][0])
        settings = Settings(bot_token="secret", database_path=self.repository.path)
        await history_handlers.history(self.message, self.repository, settings)
        self.assertIn("пуста", self.message.answers[-1][0])

        first = self.repository.save(
            77,
            {"object_name": "Дом", "building_type": "house", "indoor": 20},
            4,
            4.4,
            "первый отчёт",
        )
        second = self.repository.save(
            77,
            {"object_name": "Дом", "building_type": "house", "indoor": 22},
            5,
            5.5,
            "второй отчёт",
        )
        await history_handlers.history(self.message, self.repository, settings)
        self.assertIn("Дом", self.message.answers[-1][0])

        for text in ("/report", "/report 9999"):
            await history_handlers.saved_report(FakeMessage(text), self.repository)
        report_message = FakeMessage(f"/report {first}")
        await history_handlers.saved_report(report_message, self.repository)
        self.assertIn("первый отчёт", report_message.answers[-1][0])

        invalid_copy = FakeMessage("/copy nope")
        await history_handlers.copy_calculation(invalid_copy, self.state, self.repository)
        missing_copy = FakeMessage("/copy 9999")
        await history_handlers.copy_calculation(missing_copy, self.state, self.repository)
        copied = FakeMessage(f"/copy {first}")
        await history_handlers.copy_calculation(copied, self.state, self.repository)
        self.assertEqual(self.state.state, Survey.confirmation)
        self.assertEqual(self.state.data["parent_calculation_id"], first)

        invalid_compare = FakeMessage("/compare 1")
        await history_handlers.compare_calculations(invalid_compare, self.repository)
        missing_compare = FakeMessage(f"/compare {first} 9999")
        await history_handlers.compare_calculations(missing_compare, self.repository)
        same_compare = FakeMessage(f"/compare {first} {first}")
        await history_handlers.compare_calculations(same_compare, self.repository)
        diff_compare = FakeMessage(f"/compare {first} {second}")
        await history_handlers.compare_calculations(diff_compare, self.repository)
        self.assertIn("indoor", diff_compare.answers[-1][0])

    async def test_draft_survives_restart_resume_and_discard(self) -> None:
        empty = FakeMessage()
        await survey.resume_draft(empty, self.state, self.repository)
        self.assertIn("нет", empty.answers[-1][0])

        self.repository.save_draft(77, Survey.wall_thickness.state, {"wall_material": "brick"})
        restarted = CalculationRepository(self.repository.path)
        restarted.initialize()
        await survey.resume_draft(self.message, self.state, restarted)
        self.assertEqual(self.state.state, Survey.wall_thickness.state)
        self.assertEqual(self.state.data["wall_material"], "brick")
        self.assertIn("толщину", self.message.answers[-1][0])
        await survey.discard_draft(self.message, self.state, restarted)
        self.assertIsNone(restarted.load_draft(77))
        await survey.discard_draft(self.message, self.state, restarted)
        self.assertIn("нет", self.message.answers[-1][0])

    async def test_back_cancel_and_history_delete_callbacks_are_acknowledged(self) -> None:
        await survey.back_command(self.message, self.state)
        self.assertIn("нет", self.message.answers[-1][0])
        self.state.data = {
            "_back_stack": [{"state": Survey.indoor.state, "data": {"outdoor": -14}}]
        }
        await survey.back_command(self.message, self.state)
        self.assertEqual(self.state.state, Survey.indoor.state)
        self.assertIn("Снаружи -14", self.message.answers[-1][0])

        no_back = FakeCallback("nav:back", self.message)
        await survey.back_callback(no_back, FakeState())
        self.assertTrue(no_back.answers[-1][1]["show_alert"])
        with_back = FakeCallback("nav:back", self.message)
        await survey.back_callback(
            with_back,
            FakeState({"_back_stack": [{"state": Survey.indoor.state, "data": {}}]}),
        )
        self.assertTrue(with_back.answers)

        cancel_state = FakeState({"x": 1})
        await survey.cancel(self.message, cancel_state)
        self.assertEqual(cancel_state.data, {})
        callback = FakeCallback("nav:cancel", self.message)
        await survey.cancel_callback(callback, FakeState({"x": 1}))
        self.assertTrue(callback.answers)

        self.repository.save(77, {}, 1, 1.1, "r")
        await history_handlers.delete_history_prompt(self.message)
        cancelled = FakeCallback("delete_history:cancel", self.message)
        await history_handlers.delete_history(cancelled, self.repository)
        deleted = FakeCallback("delete_history:confirm", self.message)
        await history_handlers.delete_history(deleted, self.repository)
        self.assertEqual(self.repository.recent(77), [])
        unknown = FakeCallback("delete_history:stale", self.message)
        await history_handlers.delete_history(unknown, self.repository)
        self.assertTrue(unknown.answers[-1][1]["show_alert"])

    async def test_invalid_values_and_stale_callbacks_do_not_mutate_state(self) -> None:
        for function, value in (
            (survey._nonnegative, "nan"),
            (survey._nonnegative, "abc"),
            (survey._temperature, "100"),
            (survey._temperature, "cold"),
            (survey._conductivity, "0"),
            (survey._conductivity, "lambda"),
            (survey._parse_count, "1.5"),
            (survey._parse_count, "501"),
        ):
            with self.assertRaises(ValueError):
                function(value)

        await survey.object_name(FakeMessage(""), self.state)
        self.assertNotIn("object_name", self.state.data)
        invalid_type = FakeCallback("type:stale", self.message)
        await survey.building_type(invalid_type, self.state)
        self.assertEqual(self.state.data, {})
        invalid_position = FakeCallback("position:stale", self.message)
        await survey.apartment_position(invalid_position, self.state)
        self.assertEqual(self.state.data, {})
        invalid_mode = FakeCallback("mode:stale", self.message)
        await survey.calculation_mode(invalid_mode, self.state)
        self.assertEqual(self.state.data, {})

    async def test_step_by_step_wall_editor_builds_multiple_constructions(self) -> None:
        await survey.wall_method(FakeCallback("walls:editor", self.message), self.state)
        self.assertEqual(self.state.state, Survey.wall_editor_name)
        await wall_editor.wall_name(FakeMessage("Север", 77), self.state)
        await wall_editor.wall_area(FakeMessage("6x3", 77), self.state)
        await wall_editor.wall_orientation(
            FakeCallback("wori:north", self.message), self.state
        )
        await wall_editor.wall_material(FakeCallback("wmat:brick_solid", self.message), self.state)
        await wall_editor.wall_thickness(FakeMessage("25", 77), self.state)
        await wall_editor.wall_insulated(FakeCallback("wins:no", self.message), self.state)
        self.assertEqual(self.state.state, Survey.wall_editor_action)

        await wall_editor.wall_action(FakeCallback("wedit:add", self.message), self.state)
        duplicate = FakeMessage("сЕвЕр", 77)
        await wall_editor.wall_name(duplicate, self.state)
        self.assertIn("уже использовано", duplicate.answers[-1][0])
        await wall_editor.wall_name(FakeMessage("Торец", 77), self.state)
        await wall_editor.wall_area(FakeMessage("12", 77), self.state)
        await wall_editor.wall_orientation(FakeCallback("wori:west", self.message), self.state)
        await wall_editor.wall_material(FakeCallback("wmat:custom", self.message), self.state)
        await wall_editor.wall_custom_lambda(FakeMessage("0,12", 77), self.state)
        await wall_editor.wall_thickness(FakeMessage("30", 77), self.state)
        await wall_editor.wall_insulated(FakeCallback("wins:yes", self.message), self.state)
        await wall_editor.insulation_material(
            FakeCallback("wimat:mineral_wool", self.message), self.state
        )
        await wall_editor.insulation_thickness(FakeMessage("5", 77), self.state)
        await wall_editor.more_layers(FakeCallback("wlayer:add", self.message), self.state)
        await wall_editor.insulation_material(
            FakeCallback("wimat:brick_hollow", self.message), self.state
        )
        await wall_editor.insulation_thickness(FakeMessage("12", 77), self.state)
        await wall_editor.more_layers(FakeCallback("wlayer:finish", self.message), self.state)
        await wall_editor.wall_action(FakeCallback("wedit:finish", self.message), self.state)

        self.assertEqual(self.state.state, Survey.window_count)
        self.assertEqual(self.state.data["wall_gross_area"], 30)
        self.assertEqual(len(self.state.data["wall_groups"]), 2)
        self.assertEqual(self.state.data["wall_groups"][1]["material_conductivity"], 0.12)
        self.assertEqual(self.state.data["wall_groups"][1]["insulation_material"], "mineral_wool")
        self.assertEqual(len(self.state.data["wall_groups"][1]["layers"]), 3)

    async def test_specific_wall_group_can_be_replaced_and_deleted(self) -> None:
        self.state.data = {
            "locale": "ru",
            "wall_groups": [
                {"name": "Север", "gross_area_m2": 20},
                {"name": "Юг", "gross_area_m2": 15},
            ],
        }
        await wall_editor.wall_action(FakeCallback("wedit:edit:0", self.message), self.state)
        await wall_editor.wall_name(FakeMessage("Север новый", 77), self.state)
        await wall_editor.wall_area(FakeMessage("24", 77), self.state)
        await wall_editor.wall_orientation(
            FakeCallback("wori:north", self.message), self.state
        )
        await wall_editor.wall_material(
            FakeCallback("wmat:aerated_d500", self.message), self.state
        )
        await wall_editor.wall_thickness(FakeMessage("30", 77), self.state)
        await wall_editor.wall_insulated(FakeCallback("wins:no", self.message), self.state)
        self.assertEqual(
            [item["name"] for item in self.state.data["wall_groups"]],
            ["Север новый", "Юг"],
        )

        await wall_editor.wall_action(FakeCallback("wedit:delete:1", self.message), self.state)
        self.assertEqual(
            [item["name"] for item in self.state.data["wall_groups"]], ["Север новый"]
        )

        stale = FakeCallback("wedit:delete:9", self.message)
        await wall_editor.wall_action(stale, self.state)
        self.assertTrue(stale.answers[-1][1]["show_alert"])

    async def test_step_by_step_bridge_editor_validates_and_finishes(self) -> None:
        await survey.thermal_bridges(FakeCallback("bridges:exact", self.message), self.state)
        self.assertEqual(self.state.state, Survey.bridge_editor_name)
        await bridge_editor.bridge_name(FakeMessage("Балкон", 77), self.state)
        await bridge_editor.bridge_length(FakeMessage("4,5", 77), self.state)
        invalid = FakeMessage("5,1", 77)
        await bridge_editor.bridge_psi(invalid, self.state)
        self.assertIn("от 0 до 5", invalid.answers[-1][0])
        await bridge_editor.bridge_psi(FakeMessage("0,35", 77), self.state)
        await bridge_editor.bridge_action(FakeCallback("bedit:finish", self.message), self.state)

        self.assertEqual(self.state.state, Survey.safety_factor)
        self.assertEqual(self.state.data["thermal_bridge_factor"], 0.0)
        self.assertEqual(
            self.state.data["linear_thermal_bridges"],
            [{"name": "Балкон", "length_m": 4.5, "psi_w_mk": 0.35}],
        )

    async def test_uzbek_bridge_editor_and_restore_are_localized(self) -> None:
        self.state.data = {"locale": "uz", "profile_defaults": {}}
        await bridge_editor.start_editor(self.message, self.state)
        self.assertIn("Sovuq ko‘prigi nomi", self.message.answers[-1][0])
        await bridge_editor.bridge_name(FakeMessage("Balkon", 77), self.state)
        await bridge_editor.bridge_length(FakeMessage("4,5", 77), self.state)
        invalid = FakeMessage("6", 77)
        await bridge_editor.bridge_psi(invalid, self.state)
        self.assertIn("0 dan 5", invalid.answers[-1][0])
        valid = FakeMessage("0,35", 77)
        await bridge_editor.bridge_psi(valid, self.state)
        self.assertIn("Saqlangan sovuq ko‘priklari", valid.answers[-1][0])
        buttons = [
            button.text
            for row in valid.answers[-1][1]["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("➕ Ko‘prik qo‘shish", buttons)
        self.assertIn("⬅️ Orqaga", buttons)
        self.assertTrue(await bridge_editor.render_editor_step(self.message, self.state))

    async def test_specific_bridge_can_be_replaced_and_deleted(self) -> None:
        self.state.data = {
            "locale": "ru",
            "linear_thermal_bridges": [
                {"name": "Балкон", "length_m": 4.0, "psi_w_mk": 0.3},
                {"name": "Перемычка", "length_m": 6.0, "psi_w_mk": 0.2},
            ],
        }
        await bridge_editor.bridge_action(
            FakeCallback("bedit:edit:0", self.message), self.state
        )
        await bridge_editor.bridge_name(FakeMessage("Балкон новый", 77), self.state)
        await bridge_editor.bridge_length(FakeMessage("5", 77), self.state)
        await bridge_editor.bridge_psi(FakeMessage("0,25", 77), self.state)
        self.assertEqual(
            [item["name"] for item in self.state.data["linear_thermal_bridges"]],
            ["Балкон новый", "Перемычка"],
        )

        await bridge_editor.bridge_action(
            FakeCallback("bedit:delete:1", self.message), self.state
        )
        self.assertEqual(
            [item["name"] for item in self.state.data["linear_thermal_bridges"]],
            ["Балкон новый"],
        )
        stale = FakeCallback("bedit:edit:9", self.message)
        await bridge_editor.bridge_action(stale, self.state)
        self.assertTrue(stale.answers[-1][1]["show_alert"])

    async def test_uzbek_wall_editor_layers_and_restore_are_localized(self) -> None:
        self.state.data = {"locale": "uz", "profile_defaults": {}}
        await wall_editor.start_editor(self.message, self.state)
        self.assertIn("Devor yoki guruh nomi", self.message.answers[-1][0])

        invalid = FakeMessage("", 77)
        await wall_editor.wall_name(invalid, self.state)
        self.assertIn("Qayta urinib ko‘ring", invalid.answers[-1][0])

        await wall_editor.wall_name(FakeMessage("Shimol", 77), self.state)
        area = FakeMessage("6x3", 77)
        await wall_editor.wall_area(area, self.state)
        self.assertIn("Tashqi devor yo‘nalishi", area.answers[-1][0])
        await wall_editor.wall_orientation(
            FakeCallback("wori:north", self.message), self.state
        )
        material_buttons = [
            button.text
            for row in self.message.answers[-1][1]["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("To‘liq g‘isht", material_buttons)
        self.assertIn("⬅️ Orqaga", material_buttons)

        await wall_editor.wall_material(
            FakeCallback("wmat:brick_solid", self.message), self.state
        )
        await wall_editor.wall_thickness(FakeMessage("25", 77), self.state)
        await wall_editor.wall_insulated(FakeCallback("wins:yes", self.message), self.state)
        await wall_editor.insulation_material(
            FakeCallback("wimat:mineral_wool", self.message), self.state
        )
        layer = FakeMessage("5", 77)
        await wall_editor.insulation_thickness(layer, self.state)
        self.assertIn("Konstruksiyadagi qatlamlar: 2", layer.answers[-1][0])
        await wall_editor.more_layers(FakeCallback("wlayer:finish", self.message), self.state)

        self.assertEqual(self.state.state, Survey.wall_editor_action)
        self.assertEqual(len(self.state.data["wall_groups"][0]["layers"]), 2)
        self.assertEqual(self.state.data["wall_groups"][0]["orientation"], "north")
        self.assertIn("Saqlangan devorlar", self.message.answers[-1][0])
        action_buttons = [
            button.text
            for row in self.message.answers[-1][1]["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("➕ Devor qo‘shish", action_buttons)
        self.assertIn("✖️ Bekor qilish", action_buttons)
        self.assertTrue(await wall_editor.render_editor_step(self.message, self.state))

    async def test_confirmation_handles_domain_internal_db_and_pdf_failures(self) -> None:
        invalid = FakeCallback("confirm:calculate", self.message)
        with patch(
            "u_calc.handlers.survey.calculate_from_answers",
            side_effect=InvalidCalculationData("нет стены"),
        ):
            await survey.confirmation(invalid, self.state, self.repository)
        self.assertIn("нет стены", self.message.answers[-1][0])

        internal = FakeCallback("confirm:calculate", self.message)
        with patch("u_calc.handlers.survey.calculate_from_answers", side_effect=RuntimeError("x")):
            await survey.confirmation(internal, self.state, self.repository)
        self.assertIn("внутренней ошибки", self.message.answers[-1][0])

        class BrokenRepository:
            def save(self, *args, **kwargs):
                raise OSError("disk full")

        self.state = FakeState({"object_name": "Несохранённый", "calculation_request_id": "id"})
        callback = FakeCallback("confirm:calculate", self.message)
        with (
            patch("u_calc.handlers.survey.calculate_from_answers", return_value=sample_bundle()),
            patch("u_calc.pdf_report.build_pdf_report", return_value=b"%PDF-test"),
        ):
            await survey.confirmation(callback, self.state, BrokenRepository())
        self.assertIn("не сохранён", self.message.answers[-2][0])
        self.assertEqual(self.message.documents[-1][0].filename, "u-calc-unsaved.pdf")
        self.assertIsNone(self.state.state)

        self.state = FakeState({"object_name": "PDF error"})
        callback = FakeCallback("confirm:calculate", self.message)
        with (
            patch("u_calc.handlers.survey.calculate_from_answers", return_value=sample_bundle()),
            patch("u_calc.pdf_report.build_pdf_report", side_effect=RuntimeError("font")),
        ):
            await survey.confirmation(callback, self.state, self.repository)
        self.assertIn("PDF создать не удалось", self.message.answers[-2][0])

    async def test_uzbek_completed_calculation_summary_and_pdf_caption_are_localized(self) -> None:
        state = FakeState(
            {
                "locale": "uz",
                "object_name": "Yunusobod uyi",
                "calculation_request_id": "uz-result-test",
            }
        )
        message = FakeMessage()
        callback = FakeCallback("confirm:calculate", message)
        with (
            patch("u_calc.handlers.survey.calculate_from_answers", return_value=sample_bundle()),
            patch("u_calc.pdf_report.build_pdf_report", return_value=b"%PDF-test"),
        ):
            await survey.confirmation(callback, state, self.repository)

        self.assertIn("Hisob №", message.answers[0][0])
        self.assertIn("🔥 Hisob tayyor: Yunusobod uyi", message.answers[0][0])
        self.assertNotIn("Расчёт готов", message.answers[0][0])
        self.assertEqual(message.documents[0][1]["caption"], "U-Calc PDF hisoboti")
        self.assertEqual(message.answers[-1][0], "Yangi hisob: /new")
        self.assertIsNone(state.state)

    async def test_confirmation_edit_routes_and_unknown_callback(self) -> None:
        for action, expected in (
            ("climate", Survey.climate),
            ("walls", Survey.wall_method),
            ("openings", Survey.window_count),
            ("boundaries", Survey.floor_boundary),
            ("airflow", Survey.air_changes),
        ):
            state = FakeState()
            callback = FakeCallback(f"confirm:{action}", self.message)
            await survey.confirmation(callback, state, self.repository)
            self.assertEqual(state.state, expected)
            self.assertTrue(callback.answers)
        stale = FakeCallback("confirm:old-screen", self.message)
        await survey.confirmation(stale, FakeState(), self.repository)
        self.assertTrue(stale.answers[-1][1]["show_alert"])

    async def test_uzbek_confirmation_edit_screens_keep_full_localized_options(self) -> None:
        state = FakeState({"locale": "uz"})
        walls_message = FakeMessage()
        await survey.confirmation(
            FakeCallback("confirm:walls", walls_message), state, self.repository
        )
        wall_buttons = [
            button.text
            for row in walls_message.answers[-1][1]["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("Turli konstruksiyalar — bosqichma-bosqich", wall_buttons)
        self.assertIn("Butun perimetr", wall_buttons)
        self.assertIn("⬅️ Orqaga", wall_buttons)

        boundaries_message = FakeMessage()
        await survey.confirmation(
            FakeCallback("confirm:boundaries", boundaries_message), state, self.repository
        )
        self.assertIn("Pol ostida nima bor", boundaries_message.answers[-1][0])
        boundary_buttons = [
            button.text
            for row in boundaries_message.answers[-1][1]["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("Sovuq yerto‘la", boundary_buttons)
        self.assertIn("✖️ Bekor qilish", boundary_buttons)

        stale = FakeCallback("confirm:missing", FakeMessage())
        await survey.confirmation(stale, state, self.repository)
        self.assertEqual(stale.answers[-1][0], "Noma’lum amal")

    async def test_unmatched_stale_callback_is_always_acknowledged(self) -> None:
        callback = FakeCallback("old:button", self.message)
        await survey.stale_callback(callback, self.repository)
        self.assertTrue(callback.answers[-1][1]["show_alert"])
        self.assertIn("устарела", callback.answers[-1][0])
