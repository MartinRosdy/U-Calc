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
    profile_design,
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
        await send(profile_design, "-14", Survey.profile_design)
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

        self.assertIsNone(state.state)
        self.assertEqual(len(records), 1)
        self.assertGreater(records[0].recommended_kw, 0)
        self.assertIn("calculation_snapshot", records[0].answers)
        self.assertEqual(records[0].answers["calculation_snapshot"]["report"], records[0].report)
        self.assertIn("Газоблок D500 30 см", records[0].report)
        self.assertIn("Пол по грунту", records[0].report)
        self.assertIn("Мощность по климатическим сценариям", records[0].report)
        self.assertTrue(any("Расчёт №1" in text for text, _ in outbox))


if __name__ == "__main__":
    unittest.main()
