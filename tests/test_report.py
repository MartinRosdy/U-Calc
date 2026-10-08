import unittest

from u_calc.calculator import calculate_heat_loss, ground_floor_zones
from u_calc.catalog import CLIMATES
from u_calc.models import Boundary, Building, Layer, OpaqueSurface, SurfaceKind
from u_calc.report import format_report, format_telegram_summary


class ReportTests(unittest.TestCase):
    def test_report_records_inputs_layers_and_summer_reference(self) -> None:
        building = Building(
            indoor_temperature_c=24,
            outdoor_temperature_c=-14,
            volume_m3=240,
            heated_area_m2=80,
            opaque_surfaces=(
                OpaqueSurface(
                    "Наружные стены",
                    90,
                    (Layer("aerated_d500", 0.30), Layer("custom", 0.05, 0.037)),
                ),
                OpaqueSurface(
                    "Потолок под соседом",
                    80,
                    (),
                    Boundary.HEATED,
                    kind=SurfaceKind.CEILING,
                ),
            ),
            ground_floor_zones=ground_floor_zones(10, 8, 2.0),
            air_changes_per_hour=0.5,
        )
        report = format_report(
            building,
            calculate_heat_loss(building),
            CLIMATES["tashkent"],
        )
        self.assertIn("Отапливаемый объём: 240 м³", report)
        self.assertIn("Газоблок D500 30 см", report)
        self.assertIn("материал по паспорту 5 см (λ=0.037 Вт/(м·К)", report)
        self.assertIn("Пол по грунту: 80 м²", report)
        self.assertIn("средний жаркий месяц 27.8 °C", report)
        self.assertIn("В отопительную нагрузку не входит", report)

    def test_telegram_summary_is_short_and_hides_engineering_protocol(self) -> None:
        building = Building(
            indoor_temperature_c=24,
            outdoor_temperature_c=-14,
            volume_m3=240,
            heated_area_m2=80,
            opaque_surfaces=(OpaqueSurface("Наружные стены", 90, (Layer("aerated_d500", 0.30),)),),
            air_changes_per_hour=0.5,
            safety_factor=1.1,
        )
        result = calculate_heat_loss(building)
        summary = format_telegram_summary("Дом Юнусабад", building, result, CLIMATES["tashkent"])
        self.assertIn("🔥 Расчёт готов: Дом Юнусабад", summary)
        self.assertIn("Рекомендуемый диапазон", summary)
        self.assertIn("Куда уходит тепло", summary)
        self.assertNotIn("value_status", summary)
        self.assertNotIn("Полный протокол и источники", summary)

        uz_summary = format_telegram_summary(
            "Yunusobod uyi", building, result, CLIMATES["tashkent"], locale="uz"
        )
        self.assertIn("🔥 Hisob tayyor: Yunusobod uyi", uz_summary)
        self.assertIn("Tavsiya etilgan oraliq", uz_summary)
        self.assertIn("Issiqlik qayerga ketadi", uz_summary)
        self.assertIn("Toshkent", uz_summary)
        self.assertNotIn("Расчёт", uz_summary)
        self.assertNotIn("Куда уходит тепло", uz_summary)


if __name__ == "__main__":
    unittest.main()
