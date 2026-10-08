"""Professional PDF rendering for a completed heat-loss calculation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .catalog import CATALOG_VERSION, ENGINE_VERSION
from .i18n import normalize_locale
from .i18n import translate as tr
from .services.calculation_service import CalculationBundle
from .storage import NORMS_VERSION

rl_config.warnOnMissingFontGlyphs = 0

_UZ_LINE_TEXT = {
    "Ограждение": "To‘siq",
    "Проём": "Ochiq",
    "Пол по грунту": "Gruntdagi pol",
    "Поправка": "Tuzatish",
    "Линейный мостик": "Chiziqli issiqlik ko‘prigi",
    "Вентиляция": "Ventilyatsiya",
    "Инфильтрация": "Infiltratsiya",
    "Механическая вентиляция": "Mexanik ventilyatsiya",
    "Естественная вентиляция": "Tabiiy ventilyatsiya",
    "Мостики холода (оценка)": "Issiqlik ko‘priklari (baho)",
    "Пол над соседом": "Pastki qo‘shni ustidagi pol",
    "Пол": "Pol",
    "Потолок под соседом": "Yuqori qo‘shni ostidagi shift",
    "Потолок / кровля": "Shift / tom",
    "Наружные стены": "Tashqi devorlar",
    "Окна": "Derazalar",
    "Наружные двери": "Tashqi eshiklar",
}
_UZ_LINE_PREFIXES = {
    "Стена: ": "Devor: ",
    "Мостик: ": "Ko‘prik: ",
    "Пол по грунту — зона ": "Gruntdagi pol — zona ",
    "Окна (": "Derazalar (",
}


def _localized_line_text(value: str, locale: str) -> str:
    if locale != "uz":
        return value
    if value in _UZ_LINE_TEXT:
        return _UZ_LINE_TEXT[value]
    for source, target in _UZ_LINE_PREFIXES.items():
        if value.startswith(source):
            return target + value.removeprefix(source)
    return value


def _font_path() -> Path:
    path = Path(__file__).resolve().parent / "assets" / "fonts" / "NotoSans-Regular.ttf"
    if not path.is_file():
        raise RuntimeError("Не найден встроенный кириллический шрифт PDF")
    return path


def _register_fonts() -> None:
    if "UCalc" not in pdfmetrics.getRegisteredFontNames():
        font = TTFont("UCalc", _font_path())
        for symbol in "Теплопотери":
            if ord(symbol) not in font.face.charToGlyph:
                raise RuntimeError("PDF-шрифт не содержит обязательные кириллические символы")
        pdfmetrics.registerFont(font)


def build_pdf_report(
    bundle: CalculationBundle,
    answers: dict[str, Any],
    telegram_user_id: int,
    *,
    created_at: datetime | None = None,
) -> bytes:
    """Return a self-contained, Cyrillic-safe PDF report."""
    _register_fonts()
    created_at = created_at or datetime.now(UTC)
    local_created_at = created_at.astimezone(ZoneInfo("Asia/Tashkent"))
    prepared_by = str(answers.get("prepared_by") or "U-Calc")
    locale = normalize_locale(str(answers.get("locale") or "ru"))
    locale_label = locale.upper()
    watts = "Вт" if locale == "ru" else "Vt"
    kilowatts = "кВт" if locale == "ru" else "kVt"
    calculation_id = str(
        answers.get("calculation_id") or answers.get("calculation_request_id") or "unsaved"
    )
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"U-Calc - {answers.get('object_name', tr('pdf.unnamed', locale))}",
        author=prepared_by,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "BodyRU", parent=styles["BodyText"], fontName="UCalc", fontSize=8.7, leading=12
    )
    small = ParagraphStyle(
        "SmallRU", parent=body, fontSize=7.3, leading=9.5, textColor=colors.HexColor("#4B5563")
    )
    heading = ParagraphStyle(
        "HeadingRU",
        parent=styles["Heading2"],
        fontName="UCalc",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#0F4C5C"),
        spaceBefore=9,
        spaceAfter=6,
    )
    title = ParagraphStyle(
        "TitleRU",
        parent=styles["Title"],
        fontName="UCalc",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#12343B"),
    )
    story = [
        Paragraph("U-CALC", title),
        Paragraph(tr("pdf.title", locale), heading),
        Table(
            [
                [
                    Paragraph(tr("pdf.object", locale), small),
                    Paragraph(
                        escape(str(answers.get("object_name", tr("pdf.unnamed", locale)))), body
                    ),
                ],
                [
                    Paragraph(tr("pdf.date", locale), small),
                    Paragraph(local_created_at.strftime("%d.%m.%Y %H:%M"), body),
                ],
                [
                    Paragraph(tr("pdf.prepared_by", locale), small),
                    Paragraph(escape(prepared_by), body),
                ],
                [Paragraph(tr("pdf.language", locale), small), Paragraph(locale_label, body)],
                [
                    Paragraph(tr("pdf.calculation_id", locale), small),
                    Paragraph(escape(calculation_id), body),
                ],
                [
                    Paragraph(tr("pdf.versions", locale), small),
                    Paragraph(
                        tr(
                            "pdf.versions_value",
                            locale,
                            engine=ENGINE_VERSION,
                            catalog=CATALOG_VERSION,
                            norms=escape(NORMS_VERSION),
                        ),
                        body,
                    ),
                ],
            ],
            colWidths=[35 * mm, 140 * mm],
            style=TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "UCalc"),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E9F3F5")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C7CC")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        ),
        Spacer(1, 8 * mm),
    ]

    result = bundle.result
    building = bundle.building
    reserve_percent = (building.safety_factor - 1) * 100
    story.extend(
        [
            Paragraph(tr("pdf.result", locale), heading),
            Table(
                [
                    [tr("pdf.transmission", locale), f"{result.transmission_w:.0f} {watts}"],
                    [tr("pdf.airflow", locale), f"{result.ventilation_w:.0f} {watts}"],
                    [
                        tr("pdf.design_load", locale),
                        f"{result.total_w:.0f} {watts} / {result.total_kw:.3f} {kilowatts}",
                    ],
                    [
                        tr("pdf.recommended", locale, reserve=f"{reserve_percent:.0f}"),
                        f"{result.recommended_w:.0f} {watts} / "
                        f"{result.recommended_kw:.3f} {kilowatts}",
                    ],
                    [
                        tr("pdf.selection_range", locale),
                        f"{result.total_kw:.2f}-{result.recommended_kw:.2f} {kilowatts}",
                    ],
                ],
                colWidths=[115 * mm, 60 * mm],
                style=TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), "UCalc"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("BACKGROUND", (0, -2), (-1, -1), colors.HexColor("#D8EEF2")),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8FA9B0")),
                        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                ),
            ),
            Paragraph(tr("pdf.sum_check", locale), small),
            Paragraph(tr("pdf.formulas", locale), heading),
            Paragraph(tr("pdf.formulas_text", locale), body),
        ]
    )
    table_rows = [
        [
            tr("pdf.element", locale),
            tr("pdf.type", locale),
            "A / L",
            "U / ψ",
            "ΔT",
            f"Q, {watts}",
        ]
    ]
    rounded_line_watts: list[Decimal] = []
    quantum = Decimal("0.1")
    for line in result.lines:
        rounded_watts = Decimal(str(line.watts)).quantize(quantum, rounding=ROUND_HALF_UP)
        rounded_line_watts.append(rounded_watts)
        table_rows.append(
            [
                Paragraph(escape(_localized_line_text(line.name, locale)), small),
                Paragraph(escape(_localized_line_text(line.kind, locale)), small),
                "-" if line.area_m2 is None else f"{line.area_m2:.2f}",
                "-" if line.u_value is None else f"{line.u_value:.3f}",
                f"{line.delta_t_k:.1f}",
                f"{rounded_watts:.1f}",
            ]
        )
    rounded_total = Decimal(str(result.total_w)).quantize(quantum, rounding=ROUND_HALF_UP)
    rounding_adjustment = rounded_total - sum(rounded_line_watts, Decimal("0"))
    if rounding_adjustment:
        table_rows.append(
            [tr("pdf.rounding", locale), "", "", "", "", f"{rounding_adjustment:.1f}"]
        )
    table_rows.append([tr("pdf.total", locale), "", "", "", "", f"{rounded_total:.1f}"])
    story.append(
        Table(
            table_rows,
            repeatRows=1,
            colWidths=[57 * mm, 32 * mm, 21 * mm, 21 * mm, 18 * mm, 26 * mm],
            style=TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "UCalc"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.2),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F4C5C")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#D8EEF2")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#A9B8BC")),
                    ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            ),
        )
    )
    story.extend([PageBreak(), Paragraph(tr("pdf.protocol", locale), heading)])
    for paragraph in bundle.report.split("\n"):
        story.append(Paragraph(escape(paragraph) if paragraph else "&nbsp;", body))
    story.append(
        KeepTogether(
            [
                Spacer(1, 5 * mm),
                Paragraph(tr("pdf.disclaimer_title", locale), heading),
                Paragraph(tr("pdf.disclaimer", locale), body),
            ]
        )
    )

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("UCalc", 7)
        canvas.setFillColor(colors.HexColor("#66757A"))
        canvas.drawString(16 * mm, 9 * mm, tr("pdf.footer", locale))
        canvas.drawCentredString(A4[0] / 2, 9 * mm, tr("pdf.page", locale, page=doc.page))
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
