import unittest
from contextlib import redirect_stdout
from io import StringIO

from u_calc.calculator import calculate_heat_loss, ground_floor_zones
from u_calc.catalog import CLIMATES
from u_calc.demo import main as demo_main
from u_calc.models import (
    Airflow,
    Boundary,
    Building,
    HeatLossResult,
    Layer,
    LossLine,
    OpaqueSurface,
    Opening,
    SurfaceKind,
)
from u_calc.report import format_report, format_telegram_summary
from u_calc.services.calculation_service import calculate_from_answers


class ReportTests(unittest.TestCase):
    def test_installed_demo_uses_current_airflow_model_and_auditable_values(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            demo_main()

        report = output.getvalue()
        self.assertNotIn("legacy ACH", report)
        self.assertIn("механическая 80 м³/ч", report)
        self.assertIn("инфильтрация 30 м³/ч", report)
        self.assertIn("рекуперация механической части 75%", report)
        self.assertIn("Демонстрационный паспортный U", report)
        self.assertIn("ISO 6946:2017, таблица 7", report)
        self.assertIn("нормативное расчётное значение для условий Б", report)
        self.assertIn("паспортное значение, введённое пользователем", report)
        self.assertIn("расчётная температура холодного периода (параметр Б)=-14", report)
        self.assertIn("https://mc.uz/uploads/mcuz_5064970383794.pdf", report)
        self.assertNotIn("normative_base_not_design", report)
        self.assertNotIn("passport_user_input", report)

    def test_legacy_airflow_report_states_conservative_nonrecoverable_treatment(self) -> None:
        building = Building(
            indoor_temperature_c=20,
            outdoor_temperature_c=-10,
            volume_m3=100,
            opaque_surfaces=(),
            air_changes_per_hour=0.5,
            heat_recovery_efficiency=0.8,
            safety_factor=1,
        )

        report = format_report(building, calculate_heat_loss(building))
        self.assertIn("поток принят невосстанавливаемым", report)
        self.assertNotIn("рекуперация 80%", report)

        uz_report = format_report(building, calculate_heat_loss(building), locale="uz")
        self.assertIn("qayta tiklanmaydigan deb qabul qilingan", uz_report)

    def test_summary_uses_surface_kind_instead_of_words_in_user_name(self) -> None:
        building = Building(
            indoor_temperature_c=24,
            outdoor_temperature_c=-14,
            volume_m3=100,
            opaque_surfaces=(
                OpaqueSurface(
                    "Полка и кровля — название стены",
                    10,
                    (Layer("custom", 0.25, conductivity_w_mk=0.8),),
                    kind=SurfaceKind.WALL,
                ),
            ),
        )
        summary = format_telegram_summary("Объект", building, calculate_heat_loss(building))
        self.assertIn("• стены —", summary)
        self.assertNotIn("• пол и верх —", summary)

    def test_summary_warns_for_reference_openings_but_not_passport_u(self) -> None:
        common = dict(
            indoor_temperature_c=24,
            outdoor_temperature_c=-14,
            volume_m3=100,
            opaque_surfaces=(
                OpaqueSurface(
                    "Стена",
                    10,
                    (Layer("custom", 0.25, conductivity_w_mk=0.8),),
                ),
            ),
        )
        passport_building = Building(
            **common,
            openings=(
                Opening(
                    "Окно",
                    2,
                    1.1,
                    value_status="passport_user_input",
                    source_note="Паспорт",
                ),
            ),
        )
        passport_summary = format_telegram_summary(
            "Объект",
            passport_building,
            calculate_heat_loss(passport_building),
        )
        self.assertNotIn("U части проёмов — справочное", passport_summary)

        reference_building = Building(
            **common,
            openings=(
                Opening(
                    "Окно",
                    2,
                    1.6,
                    value_status="typical_reference",
                    source_note="Типовое значение",
                ),
            ),
        )
        reference_summary = format_telegram_summary(
            "Объект",
            reference_building,
            calculate_heat_loss(reference_building),
        )
        self.assertIn("U части проёмов — справочное", reference_summary)

    def test_percentage_bridge_fallback_states_its_base_and_estimate_status(self) -> None:
        building = Building(
            indoor_temperature_c=24,
            outdoor_temperature_c=-14,
            volume_m3=100,
            opaque_surfaces=(
                OpaqueSurface("Стена", 10, (Layer("brick_solid", 0.25),)),
            ),
            thermal_bridge_factor=0.1,
        )
        result = calculate_heat_loss(building)

        report = format_report(building, result)
        self.assertIn(
            "оценка 10% от потерь через ограждения, проёмы и пол по грунту до мостиков",
            report,
        )
        uz_report = format_report(building, result, locale="uz")
        self.assertIn("to‘siqlar, ochiqlar va gruntdagi polning", uz_report)
        self.assertIn("yo‘qotishlaridan 10%", uz_report)

    def test_text_report_reconciles_rounded_breakdown_with_total(self) -> None:
        building = Building(
            indoor_temperature_c=24,
            outdoor_temperature_c=-14,
            volume_m3=100,
            opaque_surfaces=(
                OpaqueSurface("Стена", 10, (Layer("brick_solid", 0.25),)),
            ),
        )
        result = HeatLossResult(
            transmission_w=12,
            ventilation_w=0,
            total_w=12,
            recommended_w=13.2,
            lines=(
                LossLine("Строка 1", "Ограждение", 1, 1, 38, 4),
                LossLine("Строка 2", "Ограждение", 1, 1, 38, 4),
                LossLine("Строка 3", "Ограждение", 1, 1, 38, 4),
            ),
        )

        report = format_report(building, result)
        for index in range(1, 4):
            self.assertIn(f"Строка {index}: 0.00 кВт", report)
        self.assertIn("Корректировка округления: +0.01 кВт", report)
        self.assertIn("Расчётная нагрузка: 0.01 кВт", report)

        uz_report = format_report(building, result, locale="uz")
        for index in range(1, 4):
            self.assertIn(f"Строка {index}: 0.00 kVt", uz_report)
        self.assertIn("Yaxlitlash tuzatishi: +0.01 kVt", uz_report)

    def test_appendix8_formula_three_is_auditable_in_report(self) -> None:
        bundle = calculate_from_answers(
            {
                "locale": "ru",
                "wall_material": "brick_solid",
                "wall_thickness": 0.25,
                "wall_gross_area": 60,
                "window_area": 0,
                "door_area": 0,
                "length": 10,
                "width": 8,
                "floor_boundary": "heated",
                "ceiling_boundary": "heated",
                "indoor": 24,
                "outdoor": -14,
                "volume": 240,
                "airflow_input_basis": "components_m3_h",
                "mechanical_ventilation_m3_h": 0,
                "natural_ventilation_m3_h": 0,
                "infiltration_m3_h": 150,
                "infiltration_living_area_m2": 50,
                "infiltration_basis": "appendix8_envelope",
                "infiltration_paths": [
                    {
                        "pressure_pa": 12,
                        "first_floor_pressure_pa": 10,
                        "opening_area_m2": 20,
                        "air_permeability_resistance_m2_h_pa_kg": 0.5,
                        "envelope_area_m2": 100,
                        "normative_air_permeability_kg_m2_h": 0.2,
                        "gap_area_m2": 0,
                        "panel_joint_length_m": 0,
                        "pressure_input": {
                            "building_height_m": 12,
                            "opening_height_m": 8,
                            "indoor_temperature_c": 24,
                            "outdoor_temperature_c": -14,
                            "outdoor_air_density_kg_m3": 1.3,
                            "wind_speed_m_s": 5,
                            "windward_coefficient": 0.8,
                            "leeward_coefficient": -0.6,
                            "height_factor": 1,
                            "internal_pressure_pa": 0,
                        },
                        "first_floor_pressure_input": {
                            "building_height_m": 12,
                            "opening_height_m": 2.5,
                            "indoor_temperature_c": 24,
                            "outdoor_temperature_c": -14,
                            "outdoor_air_density_kg_m3": 1.3,
                            "wind_speed_m_s": 5,
                            "windward_coefficient": 0.8,
                            "leeward_coefficient": -0.6,
                            "height_factor": 1,
                            "internal_pressure_pa": 0,
                        },
                    }
                ],
            }
        )
        self.assertIn("формула 3 приложения 8 ШНҚ", bundle.report)
        self.assertIn("групп давления 1", bundle.report)
        self.assertIn("Q1=", bundle.report)
        self.assertIn("Q2=", bundle.report)
        self.assertIn("формула 4: H=12", bundle.report)
        self.assertIn("h=8→12.00 Pa", bundle.report)
        self.assertRegex(bundle.report, r"принята формула [12] \(50 м²\)")

    def test_appendix8_infiltration_method_is_visible_and_localized(self) -> None:
        bundle = calculate_from_answers(
            {
                "locale": "uz",
                "wall_material": "brick_solid",
                "wall_thickness": 0.25,
                "wall_gross_area": 60,
                "window_area": 0,
                "door_area": 0,
                "length": 10,
                "width": 8,
                "floor_boundary": "heated",
                "ceiling_boundary": "heated",
                "indoor": 24,
                "outdoor": -14,
                "volume": 240,
                "airflow_input_basis": "components_m3_h",
                "mechanical_ventilation_m3_h": 0,
                "natural_ventilation_m3_h": 0,
                "infiltration_m3_h": 150,
                "infiltration_basis": "appendix8_residential_exhaust",
            }
        )
        self.assertIn("8-ilova, 2-formula quyi bahosi", bundle.report)
        self.assertIn("yashash maydoni 50 m²", bundle.report)
        self.assertIn("har 1 m² iga 3 m³/soat", bundle.report)
        self.assertNotIn("нижняя оценка", bundle.report)

    def test_calculation_service_propagates_locale_to_engineering_report(self) -> None:
        bundle = calculate_from_answers(
            {
                "locale": "uz",
                "climate_key": "manual",
                "manual_climate_source": "Loyiha OV, 3-varaq",
                "wall_material": "brick_solid",
                "wall_thickness": 0.25,
                "wall_gross_area": 60,
                "window_area": 0,
                "door_area": 0,
                "length": 10,
                "width": 8,
                "floor_boundary": "heated",
                "ceiling_boundary": "heated",
                "indoor": 24,
                "outdoor": -14,
                "volume": 240,
                "air_changes": 0.5,
            }
        )

        self.assertIn("Issiqlik yo‘qotishlari hisobi natijasi", bundle.report)
        self.assertIn("Loyiha OV, 3-varaq", bundle.report)
        self.assertIn("me’yoriy deb belgilanmaydi", bundle.report)

    def test_missing_manual_climate_source_is_localized_in_uzbek_report(self) -> None:
        bundle = calculate_from_answers(
            {
                "locale": "uz",
                "climate_key": "manual",
                "wall_material": "brick_solid",
                "wall_thickness": 0.25,
                "wall_gross_area": 60,
                "window_area": 0,
                "door_area": 0,
                "length": 10,
                "width": 8,
                "floor_boundary": "heated",
                "ceiling_boundary": "heated",
                "indoor": 24,
                "outdoor": -14,
                "volume": 240,
                "air_changes": 0.5,
            }
        )

        self.assertIn("foydalanuvchi ko‘rsatmagan", bundle.report)
        self.assertNotIn("не указан пользователем", bundle.report)
        self.assertNotIn("Результат расчёта теплопотерь", bundle.report)

    def test_full_engineering_report_is_localized_to_uzbek(self) -> None:
        building = Building(
            indoor_temperature_c=24,
            outdoor_temperature_c=-14,
            volume_m3=240,
            heated_area_m2=80,
            opaque_surfaces=(
                OpaqueSurface("Наружные стены", 84, (Layer("aerated_d500", 0.30),)),
            ),
            openings=(
                Opening(
                    "Окна (2 шт.)",
                    6,
                    1.1,
                    value_status="passport_user_input",
                    source_note="Паспортный U введён пользователем",
                ),
            ),
            airflow=Airflow(mechanical_m3_h=80, infiltration_m3_h=40),
            safety_factor=1.1,
            assumptions=(
                "Непривязанные проёмы распределены между стенами пропорционально свободной "
                "площади; ориентационная добавка для них не определена и принята β=0.",
            ),
        )

        report = format_report(
            building,
            calculate_heat_loss(building),
            CLIMATES["tashkent"],
            locale="uz",
        )

        self.assertIn("Boshlang‘ich ma’lumotlar", report)
        self.assertIn("D500 gazoblok 30 cm", report)
        self.assertIn("Derazalar (2 dona)", report)
        self.assertIn("Mexanik ventilyatsiya", report)
        self.assertIn("Toshkent", report)
        self.assertIn("Qabul qilingan farazlar", report)
        self.assertIn("foydalanuvchi tomonidan kiritilgan", report)
        for russian_fragment in (
            "Исходные данные",
            "Отапливаемый объём",
            "Конструкции",
            "Разбивка",
            "Принятые допущения",
            "Расчётная нагрузка",
            "Наружные стены",
            "Механическая вентиляция",
        ):
            self.assertNotIn(russian_fragment, report)

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
        self.assertIn("Автоклавный силикатный газобетон D500 30 см", report)
        self.assertIn("материал по паспорту 5 см (λ=0.037 Вт/(м·К)", report)
        self.assertIn("Пол по грунту: 80 м²", report)
        self.assertIn("средний жаркий месяц 27.8 °C", report)
        self.assertIn("В отопительную нагрузку не входит", report)
        self.assertIn("ISO 6946:2017, таблица 7", report)
        self.assertIn("Rsi=0,13", report)
        self.assertIn("Rse=0,04", report)
        self.assertIn("нормативное расчётное значение для условий Б", report)
        self.assertNotIn("reference_unverified", report)
        self.assertIn("средняя температура холодного месяца=1.9 °C", report)
        self.assertIn("наблюдавшийся абсолютный минимум=-29.5 °C", report)
        self.assertNotIn("cold_month_mean_c", report)
        self.assertNotIn("observed_extreme_c", report)

        uz_report = format_report(
            building,
            calculate_heat_loss(building),
            CLIMATES["tashkent"],
            locale="uz",
        )
        self.assertIn("ISO 6946:2017, 7-jadval", uz_report)
        self.assertIn("Rsi=0,13", uz_report)
        self.assertIn("Rse=0,04", uz_report)
        self.assertIn("sovuq oyning o‘rtacha harorati=1.9 °C", uz_report)
        self.assertIn("kuzatilgan mutlaq minimum=-29.5 °C", uz_report)
        self.assertNotIn("cold_month_mean_c", uz_report)

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
