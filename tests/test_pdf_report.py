import unittest

from u_calc.calculator import calculate_heat_loss
from u_calc.models import Airflow, Building, Layer, OpaqueSurface
from u_calc.pdf_report import build_pdf_report
from u_calc.report import format_report
from u_calc.services.calculation_service import CalculationBundle


class PdfReportTests(unittest.TestCase):
    def test_pdf_is_generated_and_contains_multiple_pages(self) -> None:
        building = Building(
            indoor_temperature_c=24,
            outdoor_temperature_c=-14,
            volume_m3=240,
            heated_area_m2=80,
            opaque_surfaces=(OpaqueSurface("Наружные стены", 90, (Layer("aerated_d500", 0.3),)),),
            airflow=Airflow(mechanical_m3_h=80, infiltration_m3_h=40),
            safety_factor=1.1,
        )
        result = calculate_heat_loss(building)
        report = format_report(building, result)
        bundle = CalculationBundle(building, result, None, None, report)

        pdf = build_pdf_report(bundle, {"object_name": "Тестовый дом"}, 777)

        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 10_000)
        self.assertGreaterEqual(pdf.count(b"/Type /Page"), 2)
        self.assertAlmostEqual(sum(line.watts for line in result.lines), result.total_w)
