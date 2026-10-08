from .catalog import (
    CATALOG_VERSION,
    CLIMATES,
    ENGINE_VERSION,
    MATERIALS,
    SCENARIO_NAMES,
    ClimateProfile,
)
from .i18n import normalize_locale
from .i18n import translate as tr
from .models import Boundary, Building, HeatLossResult, Layer, OpaqueSurface, Orientation

BOUNDARY_NAMES = {
    Boundary.OUTDOOR: "наружный воздух",
    Boundary.UNHEATED: "неотапливаемая зона",
    Boundary.GROUND: "грунт",
    Boundary.HEATED: "отапливаемое помещение",
}

ORIENTATION_NAMES = {
    Orientation.NORTH: "север",
    Orientation.NORTH_EAST: "северо-восток",
    Orientation.EAST: "восток",
    Orientation.SOUTH_EAST: "юго-восток",
    Orientation.SOUTH: "юг",
    Orientation.SOUTH_WEST: "юго-запад",
    Orientation.WEST: "запад",
    Orientation.NORTH_WEST: "северо-запад",
}


def format_telegram_summary(
    object_name: str,
    building: Building,
    result: HeatLossResult,
    climate: ClimateProfile | None = None,
    scenario: str = "design",
    locale: str = "ru",
) -> str:
    """Return the short client-facing result; engineering details stay in the PDF."""
    locale = normalize_locale(locale)
    categories = {
        "walls": 0.0,
        "openings": 0.0,
        "boundaries": 0.0,
        "airflow": 0.0,
        "bridges": 0.0,
    }
    for line in result.lines:
        lowered = line.name.casefold()
        if line.kind in {"Поправка", "Линейный мостик"}:
            category = "bridges"
        elif line.kind.startswith("Вентиляция") or line.kind in {
            "Инфильтрация",
            "Естественная вентиляция",
        }:
            category = "airflow"
        elif line.kind == "Проём":
            category = "openings"
        elif line.kind == "Пол по грунту" or any(
            word in lowered for word in ("пол", "потолок", "кровл", "чердак")
        ):
            category = "boundaries"
        else:
            category = "walls"
        categories[category] += line.watts

    lines = [
        tr("summary.ready", locale, name=object_name),
        "",
        tr("summary.load", locale, value=f"{result.total_kw:.2f}"),
        tr(
            "summary.range",
            locale,
            minimum=f"{result.total_kw:.2f}",
            maximum=f"{result.recommended_kw:.2f}",
        ),
        tr("summary.reserve", locale, value=f"{(building.safety_factor - 1) * 100:.0f}"),
    ]
    if climate:
        scenario_name = (
            tr(f"survey.scenario.{scenario}", locale)
            if scenario in {"economy", "design", "extreme", "future"}
            else SCENARIO_NAMES.get(scenario, scenario)
        )
        city = tr(f"climate.{climate.key}", locale) if climate.key in CLIMATES else climate.name
        lines.append(
            tr(
                "summary.temperature",
                locale,
                value=f"{building.outdoor_temperature_c:g}",
                scenario=scenario_name,
                city=city,
            )
        )
    else:
        lines.append(
            tr(
                "summary.temperature_manual",
                locale,
                value=f"{building.outdoor_temperature_c:g}",
            )
        )

    lines.extend(["", tr("summary.destinations", locale)])
    for label, watts in categories.items():
        if watts <= 0:
            continue
        percent = watts / result.total_w * 100 if result.total_w else 0.0
        lines.append(
            tr(
                "summary.category.line",
                locale,
                name=tr(f"summary.category.{label}", locale),
                value=f"{watts / 1000:.2f}",
                percent=f"{percent:.0f}",
            )
        )

    warnings: list[str] = []
    if climate is None:
        warnings.append(tr("summary.warning.manual_climate", locale))
    if any(opening.value_status != "passport" for opening in building.openings):
        warnings.append(tr("summary.warning.openings", locale))
    if any(
        layer.conductivity_w_mk is None
        and MATERIALS[layer.material_key].value_status != "normative_design"
        for surface in building.opaque_surfaces
        for layer in surface.layers
        if layer.material_key in MATERIALS
    ):
        warnings.append(tr("summary.warning.materials", locale))
    if building.assumptions:
        if locale == "ru":
            warnings.extend(building.assumptions[:3])
        else:
            warnings.append(tr("summary.warning.assumptions", locale))
    if warnings:
        lines.extend(["", tr("summary.warning.title", locale)])
        lines.extend(f"• {warning}" for warning in dict.fromkeys(warnings))
    lines.extend(
        [
            "",
            tr("summary.footer", locale),
        ]
    )
    return "\n".join(lines)


def _layer_description(layer: Layer) -> str:
    material = MATERIALS.get(layer.material_key)
    name = material.name if material else "материал по паспорту"
    conductivity = (
        layer.conductivity_w_mk if layer.conductivity_w_mk is not None else material.conductivity
    )
    if material is None or layer.conductivity_w_mk is not None:
        status = "паспортное/ручное значение"
    else:
        status = f"{material.value_status}; {material.table_row}"
    return f"{name} {layer.thickness_m * 100:g} см (λ={conductivity:g} Вт/(м·К); {status})"


def _surface_description(surface: OpaqueSurface) -> str:
    boundary = BOUNDARY_NAMES[surface.boundary]
    if surface.adjacent_temperature_c is not None:
        boundary += f", {surface.adjacent_temperature_c:g} °C"
    layers = ", ".join(_layer_description(layer) for layer in surface.layers)
    if not layers:
        layers = "тепловой поток принят равным нулю"
    orientation = (
        f"; ориентация {ORIENTATION_NAMES[surface.orientation]}"
        if surface.orientation is not None
        else ""
    )
    return (
        f"• {surface.name}: {surface.area_m2:g} м² → {boundary}; {layers}; "
        f"β={surface.additional_heat_loss_factor:g}; n={surface.position_factor:g}{orientation}"
    )


def format_report(
    building: Building,
    result: HeatLossResult,
    climate: ClimateProfile | None = None,
    scenario: str = "design",
    scenario_results: dict[str, HeatLossResult] | None = None,
) -> str:
    delta_t = building.indoor_temperature_c - building.outdoor_temperature_c
    bridge_description = (
        "точный ввод ψ·L"
        if building.linear_thermal_bridges
        else f"поправка {building.thermal_bridge_factor * 100:g}%"
    )
    if building.airflow is None:
        airflow_description = (
            f"legacy ACH {building.air_changes_per_hour:g} 1/ч; "
            f"рекуперация {building.heat_recovery_efficiency * 100:g}%"
        )
    else:
        airflow_description = (
            f"механическая {building.airflow.mechanical_m3_h:g} м³/ч; "
            f"естественная {building.airflow.natural_m3_h:g} м³/ч; "
            f"инфильтрация {building.airflow.infiltration_m3_h:g} м³/ч; "
            f"рекуперация механической части "
            f"{building.airflow.heat_recovery_efficiency * 100:g}%"
        )
    lines = [
        "🔥 Результат расчёта теплопотерь",
        "",
        "Исходные данные:",
        f"Отапливаемый объём: {building.volume_m3:g} м³",
        f"Температуры: {building.indoor_temperature_c:.1f} °C / "
        f"{building.outdoor_temperature_c:.1f} °C (ΔT {delta_t:.1f} K)",
        f"Воздухообмен: {airflow_description}",
        f"Мостики холода: {bridge_description}",
    ]
    if all(value is not None for value in (building.length_m, building.width_m, building.height_m)):
        lines.insert(
            4,
            f"Габариты: {building.length_m:g} × {building.width_m:g} × {building.height_m:g} м",
        )
    if building.heated_area_m2:
        lines.append(f"Отапливаемая площадь: {building.heated_area_m2:g} м²")
    lines.extend(
        [
            "",
            "Итог:",
            f"Ограждения и проёмы: {result.transmission_w / 1000:.2f} кВт",
            f"Воздухообмен: {result.ventilation_w / 1000:.2f} кВт",
            f"Расчётная нагрузка: {result.total_kw:.2f} кВт",
            f"Коэффициент теплопотерь здания: {result.total_w / delta_t:.0f} Вт/К",
            f"Рекомендуемая мощность с запасом {(building.safety_factor - 1) * 100:.0f}%: "
            f"{result.recommended_kw:.2f} кВт",
        ]
    )
    if building.heated_area_m2:
        lines.append(
            f"Удельная нагрузка: {result.total_w / building.heated_area_m2:.0f} Вт/м² "
            f"({result.recommended_w / building.heated_area_m2:.0f} Вт/м² с запасом)"
        )
    lines.extend(["", "Конструкции:"])
    lines.extend(_surface_description(surface) for surface in building.opaque_surfaces)
    for opening in building.openings:
        orientation = (
            f"; ориентация {ORIENTATION_NAMES[opening.orientation]}"
            if opening.orientation is not None
            else ""
        )
        lines.append(
            f"• {opening.name}: {opening.area_m2:g} м²; U={opening.u_value:g} Вт/(м²·К); "
            f"{opening.value_status}; {opening.source_note}; "
            f"β={opening.additional_heat_loss_factor:g}; n={opening.position_factor:g}"
            f"{orientation}"
        )
    if building.ground_floor_zones:
        lines.append(
            f"• Пол по грунту: {building.heated_area_m2:g} м² геометрической площади → "
            f"{len(building.ground_floor_zones)} нормативные зоны; "
            "угловые участки зоны I учтены дважды"
        )
    lines.extend(["", "Разбивка:"])
    for item in sorted(result.lines, key=lambda row: row.watts, reverse=True):
        details = ""
        if item.area_m2 is not None and item.u_value is not None:
            if item.kind == "Линейный мостик":
                details = f" — {item.area_m2:.1f} м, ψ={item.u_value:.3f} Вт/(м·К)"
            elif item.kind == "Пол по грунту":
                details = (
                    f" — {item.area_m2:.1f} м², R={1 / item.u_value:.2f} м²·К/Вт, "
                    f"ΔT={item.delta_t_k:.1f} K"
                )
            else:
                details = (
                    f" — {item.area_m2:.1f} м², R={1 / item.u_value:.2f} м²·К/Вт, "
                    f"U={item.u_value:.2f} Вт/(м²·К), "
                    f"ΔT={item.delta_t_k:.1f} K"
                )
        lines.append(f"• {item.name}: {item.watts / 1000:.2f} кВт{details}")
    if climate:
        scenario_name = SCENARIO_NAMES.get(scenario, scenario)
        lines.extend(
            [
                "",
                f"Климат: {climate.name}, сценарий «{scenario_name}». {climate.source_note}.",
                f"Источник климата: {climate.source_url or 'ввод пользователя'}; "
                f"версия {climate.version}; период: {climate.data_period}; "
                f"обновлено {climate.updated_at}.",
                f"Лето справочно: средний жаркий месяц {climate.hot_month_mean_c:g} °C; "
                f"абсолютный максимум {climate.observed_maximum_c:g} °C. "
                "В отопительную нагрузку не входит.",
            ]
        )
        if climate.provenance:
            lines.append("Происхождение климатических значений:")
            lines.extend(
                f"• {item.parameter}={item.value:g} {item.unit}: {item.document}, "
                f"{item.location}; статус {item.status}."
                for item in climate.provenance
            )
    if climate and scenario_results:
        lines.extend(["", "Мощность по климатическим сценариям (включая запас):"])
        for key in ("economy", "design", "future", "extreme"):
            temperature = climate.outdoor_temperature(key)
            load = scenario_results[key].recommended_kw
            lines.append(f"• {SCENARIO_NAMES[key]} ({temperature:g} °C): {load:.2f} кВт")
        lines.append("Исторический экстремум — стресс-тест, а не автоматический выбор котла.")
    if building.assumptions:
        lines.extend(["", "Принятые допущения:"])
        lines.extend(f"• {item}" for item in building.assumptions)
    lines.extend(
        [
            "",
            f"Версии: расчётный движок {ENGINE_VERSION}; каталог {CATALOG_VERSION}.",
            "Нормативные коэффициенты: без структурированной ориентации β=0; "
            "коэффициент положения ограждения n=1,0. Эти значения показаны для каждой "
            "конструкции и не подбираются по её названию.",
            "Важно: расчётная тепловая нагрузка и рекомендуемая мощность оборудования "
            "с эксплуатационным запасом показаны отдельно. ГВС не включено. "
            "Месячное потребление энергии не рассчитывается. Результат не является "
            "автоматически проектной документацией. Перед монтажом инженер должен проверить "
            "мостики холода, фактический воздухообмен, паспортные λ/U и местные нормы.",
        ]
    )
    return "\n".join(lines)
