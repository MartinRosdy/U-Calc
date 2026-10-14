import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from u_calc.bot import (
    Survey,
    air_changes,
    building_type,
    calculation_mode,
    ceiling_boundary,
    climate,
    confirmation,
    dimensions,
    door_count,
    door_dimensions,
    door_method,
    door_type,
    floor_boundary,
    ground_exterior_sides,
    ground_floor_construction,
    heat_recovery,
    indoor,
    insulated,
    insulation_material,
    insulation_thickness,
    object_name,
    safety_factor,
    scenario,
    start,
    surface_adjacent_mode,
    surface_insulated,
    surface_insulation_material,
    surface_insulation_thickness,
    surface_material,
    surface_thickness,
    thermal_bridges,
    wall_area,
    wall_material,
    wall_method,
    wall_thickness,
    window_count,
    window_dimensions,
    window_method,
    window_type,
)
from u_calc.handlers import airflow, boundaries, bridge_editor, opening_editor, wall_editor
from u_calc.storage import CalculationRepository


class FakeState:
    def __init__(self) -> None:
        self.data = {}
        self.state = None

    async def get_data(self) -> dict:
        return dict(self.data)

    async def update_data(self, **values) -> None:
        self.data.update(values)

    async def set_state(self, state) -> None:
        self.state = state

    async def clear(self) -> None:
        self.data.clear()
        self.state = None


class FakeMessage:
    def __init__(self, outbox: list, text: str | None = None) -> None:
        self.outbox = outbox
        self.text = text
        self.from_user = SimpleNamespace(id=777)

    async def answer(self, text, **kwargs) -> None:
        self.outbox.append((text, kwargs))

    async def answer_document(self, document, **kwargs) -> None:
        self.outbox.append((document, kwargs))


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage) -> None:
        self.data = data
        self.message = message
        self.from_user = message.from_user
        self.answers = []

    async def answer(self, text=None, **kwargs) -> None:
        self.answers.append((text, kwargs))


class FullDialogIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_house_dialog_calculates_saves_and_returns_report(self) -> None:
        state = FakeState()
        outbox = []
        message = FakeMessage(outbox)

        async def press(handler, data: str, expected_state, *extra) -> None:
            self.assertEqual(state.state, expected_state)
            await handler(FakeCallback(data, message), state, *extra)

        async def send(handler, text: str, expected_state) -> None:
            self.assertEqual(state.state, expected_state)
            await handler(FakeMessage(outbox, text), state)

        await start(message, state)
        self.assertEqual(state.state, Survey.calculation_mode)
        await press(calculation_mode, "mode:quick", Survey.calculation_mode)
        await press(building_type, "type:house", Survey.building_type)
        await send(object_name, "Дом тестовый", Survey.object_name)
        await press(climate, "climate:tashkent", Survey.climate)
        await press(scenario, "scenario:design", Survey.scenario)
        await send(indoor, "24", Survey.indoor)
        await send(dimensions, "10 8 3", Survey.dimensions)
        await press(wall_method, "walls:area", Survey.wall_method)
        await send(wall_area, "108", Survey.wall_area)
        await press(wall_material, "mat:aerated_d500", Survey.wall_material)
        await send(wall_thickness, "30", Survey.wall_thickness)
        await press(insulated, "ins:yes", Survey.insulated)
        await press(insulation_material, "imat:mineral_wool", Survey.insulation_material)
        await send(insulation_thickness, "5", Survey.insulation_thickness)
        await send(window_count, "4", Survey.window_count)
        await press(window_method, "window_method:dimensions", Survey.window_method)
        await send(window_dimensions, "1,5x1,5", Survey.window_dimensions)
        await press(window_type, "window:triple", Survey.window_type)
        await send(door_count, "1", Survey.door_count)
        await press(door_method, "door_method:dimensions", Survey.door_method)
        await send(door_dimensions, "1x2", Survey.door_dimensions)
        await press(door_type, "door_type:insulated", Survey.door_type)

        await press(floor_boundary, "floor:ground", Survey.floor_boundary)
        await press(
            surface_adjacent_mode,
            "adjacent:floor:zonal",
            Survey.surface_adjacent_mode,
        )
        await press(
            ground_exterior_sides,
            "gsides:n,e,s,w",
            Survey.ground_exterior_sides,
        )
        await press(
            ground_floor_construction,
            "ground_floor:solid",
            Survey.ground_floor_construction,
        )
        await press(surface_insulated, "sins:yes", Survey.surface_insulated)
        await press(
            surface_insulation_material,
            "simat:xps",
            Survey.surface_insulation_material,
        )
        await send(
            surface_insulation_thickness,
            "8",
            Survey.surface_insulation_thickness,
        )

        await press(ceiling_boundary, "ceiling:outdoor", Survey.ceiling_boundary)
        await press(surface_material, "smat:concrete", Survey.surface_material)
        await send(surface_thickness, "18", Survey.surface_thickness)
        await press(surface_insulated, "sins:yes", Survey.surface_insulated)
        await press(
            surface_insulation_material,
            "simat:mineral_wool",
            Survey.surface_insulation_material,
        )
        await send(
            surface_insulation_thickness,
            "15",
            Survey.surface_insulation_thickness,
        )

        await press(air_changes, "ach:0.5", Survey.air_changes)
        await press(heat_recovery, "recovery:no", Survey.heat_recovery)
        await press(thermal_bridges, "bridges:0.10", Survey.thermal_bridges)

        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "u_calc.db")
            repository.initialize()
            self.assertEqual(state.state, Survey.safety_factor)
            await safety_factor(FakeCallback("safety:1.10", message), state)
            self.assertEqual(state.state, Survey.confirmation)
            await confirmation(FakeCallback("confirm:calculate", message), state, repository)
            records = repository.recent(777)
            stored_pdf = repository.get_pdf_for_user(777, records[0].id)

        self.assertIsNone(state.state)
        self.assertEqual(len(records), 1)
        self.assertGreater(records[0].recommended_kw, 0)
        self.assertIn("calculation_snapshot", records[0].answers)
        self.assertEqual(records[0].answers["calculation_snapshot"]["report"], records[0].report)
        self.assertIsNotNone(stored_pdf)
        self.assertTrue(stored_pdf.startswith(b"%PDF-"))
        self.assertIn(
            "Автоклавный силикатный газобетон D500 30 см",
            records[0].report,
        )
        self.assertIn("Пол по грунту", records[0].report)
        self.assertIn("Мощность по климатическим сценариям", records[0].report)
        self.assertTrue(any("Расчёт №1" in text for text, _ in outbox))

    async def test_advanced_dialog_uses_stepwise_editors_without_pipe_syntax(self) -> None:
        state = FakeState()
        outbox = []
        message = FakeMessage(outbox)
        typed_inputs: list[str] = []

        async def press(handler, data: str, expected_state, *extra) -> None:
            self.assertEqual(state.state, expected_state)
            await handler(FakeCallback(data, message), state, *extra)

        async def send(handler, text: str, expected_state) -> None:
            self.assertEqual(state.state, expected_state)
            typed_inputs.append(text)
            await handler(FakeMessage(outbox, text), state)

        await start(message, state)
        await press(calculation_mode, "mode:advanced", Survey.calculation_mode)
        await press(building_type, "type:house", Survey.building_type)
        await send(object_name, "Дом мастера", Survey.object_name)
        await press(climate, "climate:tashkent", Survey.climate)
        await press(scenario, "scenario:design", Survey.scenario)
        await send(indoor, "24", Survey.indoor)
        await send(dimensions, "10 8 3", Survey.dimensions)

        await press(wall_method, "walls:editor", Survey.wall_method)
        await send(wall_editor.wall_name, "Северная стена", Survey.wall_editor_name)
        await send(wall_editor.wall_area, "10x3", Survey.wall_editor_area)
        await press(
            wall_editor.wall_orientation,
            "wori:north",
            Survey.wall_editor_orientation,
        )
        await press(
            wall_editor.wall_material,
            "wmat:aerated_d500",
            Survey.wall_editor_material,
        )
        await send(wall_editor.wall_thickness, "30", Survey.wall_editor_thickness)
        await press(
            wall_editor.wall_insulated,
            "wins:yes",
            Survey.wall_editor_insulated,
        )
        await press(
            wall_editor.insulation_material,
            "wimat:mineral_wool",
            Survey.wall_editor_insulation_material,
        )
        await send(
            wall_editor.insulation_thickness,
            "10",
            Survey.wall_editor_insulation_thickness,
        )
        await press(
            wall_editor.more_layers,
            "wlayer:finish",
            Survey.wall_editor_more_layers,
        )
        await press(
            wall_editor.wall_action,
            "wedit:finish",
            Survey.wall_editor_action,
        )

        await send(window_count, "2", Survey.window_count)
        await press(window_method, "window_method:editor", Survey.window_method)
        await send(
            opening_editor.opening_name,
            "Окна гостиной",
            Survey.opening_editor_name,
        )
        await send(opening_editor.opening_count, "2", Survey.opening_editor_count)
        await send(
            opening_editor.opening_dimensions,
            "1,5x1,5",
            Survey.opening_editor_dimensions,
        )
        await send(opening_editor.opening_u_value, "1,1", Survey.opening_editor_u_value)
        await press(
            opening_editor.opening_wall,
            "oewall:0",
            Survey.opening_editor_wall,
        )
        await press(
            opening_editor.opening_action,
            "oedit:finish",
            Survey.opening_editor_action,
        )

        await send(door_count, "1", Survey.door_count)
        await press(door_method, "door_method:editor", Survey.door_method)
        await send(
            opening_editor.opening_name,
            "Входная дверь",
            Survey.opening_editor_name,
        )
        await send(opening_editor.opening_count, "1", Survey.opening_editor_count)
        await send(
            opening_editor.opening_dimensions,
            "1x2,1",
            Survey.opening_editor_dimensions,
        )
        await send(opening_editor.opening_u_value, "1,5", Survey.opening_editor_u_value)
        await press(
            opening_editor.opening_wall,
            "oewall:0",
            Survey.opening_editor_wall,
        )
        await press(
            opening_editor.opening_action,
            "oedit:finish",
            Survey.opening_editor_action,
        )

        await press(floor_boundary, "floor:outdoor", Survey.floor_boundary)
        await press(surface_material, "smat:concrete", Survey.surface_material)
        await send(surface_thickness, "20", Survey.surface_thickness)
        await press(
            boundaries.surface_layer_action,
            "slayer:add",
            Survey.surface_layer_action,
        )
        await press(
            boundaries.surface_layer_material,
            "slmat:xps",
            Survey.surface_layer_material,
        )
        await send(
            boundaries.surface_layer_thickness,
            "10",
            Survey.surface_layer_thickness,
        )
        await press(
            boundaries.surface_layer_action,
            "slayer:finish",
            Survey.surface_layer_action,
        )

        await press(ceiling_boundary, "ceiling:outdoor", Survey.ceiling_boundary)
        await press(surface_material, "smat:concrete", Survey.surface_material)
        await send(surface_thickness, "18", Survey.surface_thickness)
        await press(
            boundaries.surface_layer_action,
            "slayer:add",
            Survey.surface_layer_action,
        )
        await press(
            boundaries.surface_layer_material,
            "slmat:mineral_wool",
            Survey.surface_layer_material,
        )
        await send(
            boundaries.surface_layer_thickness,
            "15",
            Survey.surface_layer_thickness,
        )
        await press(
            boundaries.surface_layer_action,
            "slayer:finish",
            Survey.surface_layer_action,
        )

        await press(airflow.airflow_unit, "airflow_unit:m3h", Survey.air_changes)
        await send(
            airflow.mechanical_ventilation,
            "120",
            Survey.mechanical_ventilation,
        )
        await send(
            airflow.natural_ventilation,
            "40",
            Survey.natural_ventilation,
        )
        await press(
            airflow.infiltration_method,
            "infiltration_method:residential",
            Survey.infiltration,
        )
        await send(
            airflow.infiltration_living_area,
            "50",
            Survey.infiltration_living_area,
        )
        await press(heat_recovery, "recovery:yes", Survey.heat_recovery)
        await send(
            airflow.heat_recovery_efficiency,
            "70",
            Survey.heat_recovery_efficiency,
        )

        await press(thermal_bridges, "bridges:exact", Survey.thermal_bridges)
        await send(bridge_editor.bridge_name, "Примыкание балкона", Survey.bridge_editor_name)
        await send(bridge_editor.bridge_length, "4,5", Survey.bridge_editor_length)
        await send(bridge_editor.bridge_psi, "0,25", Survey.bridge_editor_psi)
        await press(
            bridge_editor.bridge_action,
            "bedit:finish",
            Survey.bridge_editor_action,
        )

        with tempfile.TemporaryDirectory() as directory:
            repository = CalculationRepository(Path(directory) / "u_calc.db")
            repository.initialize()
            await press(safety_factor, "safety:1.10", Survey.safety_factor)
            await press(
                confirmation,
                "confirm:calculate",
                Survey.confirmation,
                repository,
            )
            records = repository.recent(777)
            stored_pdf = repository.get_pdf_for_user(777, records[0].id)

        self.assertIsNone(state.state)
        self.assertTrue(typed_inputs)
        self.assertTrue(all("|" not in value for value in typed_inputs))
        self.assertEqual(len(records), 1)
        self.assertGreater(records[0].recommended_kw, 0)
        self.assertIsNotNone(stored_pdf)
        self.assertTrue(stored_pdf.startswith(b"%PDF-"))
        self.assertIn("Северная стена", records[0].report)
        self.assertIn("Окна гостиной", records[0].report)
        self.assertIn("Примыкание балкона", records[0].report)
        self.assertEqual(
            records[0].answers["airflow_input_basis"],
            "components_m3_h",
        )


if __name__ == "__main__":
    unittest.main()
