import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from u_calc.handlers import menu
from u_calc.storage import CalculationRepository


class FakeState:
    def __init__(self) -> None:
        self.data = {}
        self.state = None
        self.clear_count = 0

    async def clear(self) -> None:
        self.data = {}
        self.state = None
        self.clear_count += 1

    async def set_state(self, state) -> None:
        self.state = state

    async def update_data(self, **values) -> None:
        self.data.update(values)

    async def get_data(self) -> dict:
        return dict(self.data)


class FakeMessage:
    def __init__(self, text: str | None = None, user_id: int = 100) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
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


class MenuFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = CalculationRepository(Path(self.temp.name) / "menu.db")
        self.repository.initialize()
        self.state = FakeState()
        self.message = FakeMessage()

    def tearDown(self) -> None:
        self.temp.cleanup()

    async def test_main_navigation_language_help_and_history(self) -> None:
        await menu.start_menu(self.message, self.state, self.repository)
        self.assertEqual(self.state.clear_count, 1)
        self.assertIn("U-Calc", self.message.answers[-1][0])
        self.assertEqual(len(menu.main_menu("ru").inline_keyboard), 5)

        callback = FakeCallback("m:language", self.message)
        await menu.language_menu(callback, self.repository)
        self.assertTrue(callback.answers)
        invalid = FakeCallback("lang:xx", self.message)
        await menu.language_save(invalid, self.repository)
        self.assertTrue(invalid.answers[-1][1]["show_alert"])
        saved = FakeCallback("lang:uz", self.message)
        await menu.language_save(saved, self.repository)
        self.assertEqual(self.repository.get_user_settings(100).locale, "uz")
        self.assertIn("saqlandi", self.message.answers[-1][0])

        await menu.help_menu(FakeCallback("m:help", self.message), self.repository)
        await menu.history_menu(FakeCallback("m:history", self.message), self.repository)
        self.assertIn("bo‘sh", self.message.answers[-1][0])

        self.repository.save(
            100,
            {"object_name": "Uy", "building_type": "house"},
            4,
            4.4,
            "report",
        )
        await menu.history_menu(FakeCallback("m:history", self.message), self.repository)
        self.assertIn("Uy", self.message.answers[-1][0])
        await menu.home_callback(FakeCallback("m:home", self.message), self.state, self.repository)

    async def test_new_calculation_and_profiles_command(self) -> None:
        callback = FakeCallback("m:new", self.message)
        await menu.new_calculation(callback, self.state, self.repository)
        self.assertIn("детализации", self.message.answers[-1][0])
        await menu.profiles_command(self.message, self.repository)
        self.assertIn("Профил", self.message.answers[-1][0])
        await menu.profiles_menu(FakeCallback("m:profiles", self.message), self.repository)

    async def test_pdf_author_setting_is_validated_saved_and_cleared(self) -> None:
        callback = FakeCallback("p:prepared_by", self.message)
        await menu.prepared_by_start(callback, self.state, self.repository)
        self.assertEqual(self.state.state, menu.ProfileFlow.prepared_by)
        invalid = FakeMessage("x" * 121)
        await menu.prepared_by_save(invalid, self.state, self.repository)
        self.assertIn("120", invalid.answers[-1][0])
        await menu.prepared_by_save(FakeMessage("Мастер Али"), self.state, self.repository)
        self.assertEqual(self.repository.get_user_settings(100).prepared_by, "Мастер Али")

        await menu.prepared_by_start(callback, self.state, self.repository)
        await menu.prepared_by_save(FakeMessage("-"), self.state, self.repository)
        self.assertEqual(self.repository.get_user_settings(100).prepared_by, "")

    async def test_complete_profile_crud_and_missing_paths(self) -> None:
        create_callback = FakeCallback("p:create", self.message)
        await menu.profile_create_start(create_callback, self.state, self.repository)
        self.assertEqual(self.state.state, menu.ProfileFlow.create_name)

        invalid = FakeMessage("", user_id=100)
        await menu.profile_create_name(invalid, self.state, self.repository)
        self.assertIn("⚠️", invalid.answers[-1][0])
        created_message = FakeMessage("Дом", user_id=100)
        await menu.profile_create_name(created_message, self.state, self.repository)
        profile = self.repository.list_profiles(100)[0]
        self.assertEqual(profile.settings["indoor"], 24.0)

        view = FakeCallback(f"p:view:{profile.id}", self.message)
        await menu.profile_view(view, self.repository)
        self.assertIn("Дом", self.message.answers[-1][0])
        missing = FakeCallback("p:view:9999", self.message)
        await menu.profile_view(missing, self.repository)
        self.assertTrue(missing.answers[-1][1]["show_alert"])

        settings = FakeCallback(f"p:settings:{profile.id}", self.message)
        await menu.profile_settings_start(settings, self.state, self.repository)
        invalid_temperature = FakeMessage("nan")
        await menu.profile_settings_indoor(invalid_temperature, self.state, self.repository)
        self.assertIn("-30", invalid_temperature.answers[-1][0])
        await menu.profile_settings_indoor(FakeMessage("22"), self.state, self.repository)
        await menu.profile_settings_air(
            FakeCallback("pset:air:0.8", self.message), self.state, self.repository
        )
        await menu.profile_settings_safety(
            FakeCallback("pset:safety:1.15", self.message), self.state, self.repository
        )
        updated_profile = self.repository.get_profile(100, profile.id)
        self.assertEqual(updated_profile.settings["indoor"], 22.0)
        self.assertEqual(updated_profile.settings["air_changes"], 0.8)
        self.assertEqual(updated_profile.settings["safety_factor"], 1.15)

        rename = FakeCallback(f"p:rename:{profile.id}", self.message)
        await menu.profile_rename_start(rename, self.state, self.repository)
        await menu.profile_rename_name(FakeMessage("Коттедж"), self.state, self.repository)
        self.assertEqual(self.repository.get_profile(100, profile.id).name, "Коттедж")

        await menu.profile_rename_start(rename, self.state, self.repository)
        await menu.profile_rename_name(FakeMessage(""), self.state, self.repository)
        self.assertEqual(self.state.state, menu.ProfileFlow.rename_name)

        copy = FakeCallback(f"p:copy:{profile.id}", self.message)
        await menu.profile_copy_start(copy, self.state, self.repository)
        await menu.profile_copy_name(FakeMessage("Копия"), self.state, self.repository)
        profiles = self.repository.list_profiles(100)
        self.assertEqual(len(profiles), 2)

        await menu.profile_copy_start(copy, self.state, self.repository)
        await menu.profile_copy_name(FakeMessage("Копия"), self.state, self.repository)
        self.assertEqual(self.state.state, menu.ProfileFlow.copy_name)

        default = FakeCallback(f"p:default:{profile.id}", self.message)
        await menu.profile_default(default, self.repository)
        self.assertEqual(self.repository.get_user_settings(100).default_profile_id, profile.id)
        await menu.new_calculation(FakeCallback("m:new", self.message), self.state, self.repository)
        self.assertEqual(self.state.data["applied_profile_id"], profile.id)
        self.assertEqual(self.state.data["profile_defaults"]["indoor"], 22.0)
        self.assertIn("Коттедж", self.message.answers[-1][0])
        await self.state.update_data(outdoor=-14)
        await menu.new_calculation(FakeCallback("m:new", self.message), self.state, self.repository)
        self.assertEqual(self.state.data["profile_defaults"]["safety_factor"], 1.15)
        await menu.profile_default(FakeCallback("p:default:9999", self.message), self.repository)

        prompt = FakeCallback(f"p:delete:{profile.id}", self.message)
        await menu.profile_delete_prompt(prompt, self.repository)
        self.assertIn("Удалить", self.message.answers[-1][0])
        missing_delete = FakeCallback("p:delete:9999", self.message)
        await menu.profile_delete_prompt(missing_delete, self.repository)
        self.assertTrue(missing_delete.answers[-1][1]["show_alert"])
        await menu.profile_delete(
            FakeCallback(f"p:delete_ok:{profile.id}", self.message), self.repository
        )
        self.assertIsNone(self.repository.get_profile(100, profile.id))
        await menu.profile_delete(FakeCallback("p:delete_ok:9999", self.message), self.repository)

    async def test_copy_of_missing_profile_is_reported(self) -> None:
        self.state.data["profile_id"] = 9999
        message = FakeMessage("Нет")
        await menu.profile_copy_name(message, self.state, self.repository)
        self.assertIn("не найден", message.answers[-2][0])
