"""Professional PDF rendering for a completed heat-loss calculation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any

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
from .services.calculation_service import CalculationBundle
from .storage import NORMS_VERSION

rl_config.warnOnMissingFontGlyphs = 0


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
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"U-Calc - {answers.get('object_name', 'Расчёт')}",
        author=f"Telegram user {telegram_user_id}",
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
        Paragraph("Расчёт пиковой тепловой нагрузки", heading),
        Table(
            [
                [
                    Paragraph("Объект", small),
                    Paragraph(escape(str(answers.get("object_name", "Без названия"))), body),
                ],
                [
                    Paragraph("Дата UTC", small),
                    Paragraph(created_at.isoformat(timespec="minutes"), body),
                ],
                [Paragraph("Автор", small), Paragraph(f"Telegram user {telegram_user_id}", body)],
                [
                    Paragraph("Версии", small),
                    Paragraph(
                        f"движок {ENGINE_VERSION}; каталог {CATALOG_VERSION}; "
                        f"нормы {escape(NORMS_VERSION)}",
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
            Paragraph("Результат", heading),
            Table(
                [
                    ["Ограждения, проёмы и мостики", f"{result.transmission_w:.0f} Вт"],
                    ["Вентиляция и инфильтрация", f"{result.ventilation_w:.0f} Вт"],
                    ["Расчётная нагрузка", f"{result.total_w:.0f} Вт / {result.total_kw:.3f} кВт"],
                    [
                        f"Рекомендуемая мощность (+{reserve_percent:.0f}%)",
                        f"{result.recommended_w:.0f} Вт / {result.recommended_kw:.3f} кВт",
                    ],
                    [
                        "Диапазон подбора без ГВС",
                        f"{result.total_kw:.2f}-{result.recommended_kw:.2f} кВт",
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
            Paragraph(
                "Проверка суммы: расчётная нагрузка равна сумме всех строк ниже; "
                "эксплуатационный запас показан отдельно.",
                small,
            ),
            Paragraph("Формулы и построчный расчёт", heading),
            Paragraph(
                "Ограждения: Q = U x A x ΔT x (1 + β) x n. Воздушные потери: "
                "Q = 0,33 x L x ΔT; рекуперация применяется только к механическому потоку. "
                "Линейные мостики: Q = ψ x L x ΔT.",
                body,
            ),
        ]
    )
    table_rows = [["Элемент", "Тип", "A / L", "U / ψ", "ΔT", "Q, Вт"]]
    rounded_line_watts: list[Decimal] = []
    quantum = Decimal("0.1")
    for line in result.lines:
        rounded_watts = Decimal(str(line.watts)).quantize(quantum, rounding=ROUND_HALF_UP)
        rounded_line_watts.append(rounded_watts)
        table_rows.append(
            [
                Paragraph(escape(line.name), small),
                Paragraph(escape(line.kind), small),
                "-" if line.area_m2 is None else f"{line.area_m2:.2f}",
                "-" if line.u_value is None else f"{line.u_value:.3f}",
                f"{line.delta_t_k:.1f}",
                f"{rounded_watts:.1f}",
            ]
        )
    rounded_total = Decimal(str(result.total_w)).quantize(quantum, rounding=ROUND_HALF_UP)
    rounding_adjustment = rounded_total - sum(rounded_line_watts, Decimal("0"))
    if rounding_adjustment:
        table_rows.append(["Поправка округления", "", "", "", "", f"{rounding_adjustment:.1f}"])
    table_rows.append(["ИТОГО", "", "", "", "", f"{rounded_total:.1f}"])
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
    story.extend([PageBreak(), Paragraph("Полный протокол и источники", heading)])
    for paragraph in bundle.report.split("\n"):
        story.append(Paragraph(escape(paragraph) if paragraph else "&nbsp;", body))
    story.append(
        KeepTogether(
            [
                Spacer(1, 5 * mm),
                Paragraph("Ограничение ответственности", heading),
                Paragraph(
                    "Отчёт является инженерной оценкой для подбора отопительной мощности, "
                    "не является официальной проектной документацией и не заменяет проверку "
                    "лицензированным проектировщиком.",
                    body,
                ),
            ]
        )
    )

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("UCalc", 7)
        canvas.setFillColor(colors.HexColor("#66757A"))
        canvas.drawString(16 * mm, 9 * mm, "U-Calc - инженерная оценка теплопотерь")
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Страница {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
