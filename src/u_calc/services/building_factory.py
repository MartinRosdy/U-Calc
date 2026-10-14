from __future__ import annotations

import math
import unicodedata
from dataclasses import replace
from typing import Any

from ..calculator import ground_floor_zones, orientation_heat_loss_factor
from ..catalog import CLIMATES, DOORS, MATERIALS, WINDOWS, ClimateProfile, ValueSource
from ..models import (
    Airflow,
    Appendix8PressureInput,
    Boundary,
    Building,
    InfiltrationPath,
    Layer,
    LinearThermalBridge,
    OpaqueSurface,
    Opening,
    Orientation,
    SurfaceKind,
)


class InvalidCalculationData(ValueError):
    """User-facing error raised for incomplete or corrupted survey data."""


def build_from_answers(data: dict[str, Any]) -> Building:
    """Build and centrally validate a domain model from Telegram FSM data."""
    try:
        _validate_collection_shapes(data)
        _validate_opening_group_semantics(data)
        length = _number(data, "length", 0.5, 1_000)
        width = _number(data, "width", 0.5, 1_000)
        height = _number(data, "height", 0.1, 100, default=volume_height(data, length, width))
        volume = _number(data, "volume", 1, 10_000_000)
        geometric_volume = length * width * height
        if abs(volume - geometric_volume) > max(1.0, geometric_volume * 0.02):
            raise InvalidCalculationData(
                "Объём не согласован с длиной × шириной × высотой (допуск 2%)"
            )
        indoor = _number(data, "indoor", -30, 50)
        outdoor = _number(data, "outdoor", -80, 50)
        air_changes = _number(data, "air_changes", 0, 10, default=0.0)
        floor_area = length * width
        surfaces = _wall_surfaces(data)

        floor_boundary = _boundary(data, "floor_boundary")
        ground_zones = ()
        if floor_boundary == Boundary.HEATED and data.get("floor_adjacent_temperature") is None:
            surfaces.append(
                OpaqueSurface(
                    "Пол над соседом",
                    floor_area,
                    (),
                    floor_boundary,
                    kind=SurfaceKind.FLOOR,
                )
            )
        elif floor_boundary == Boundary.GROUND and data.get("floor_ground_method") == "zonal":
            if data.get("ground_plan_shape", "rectangle") != "rectangle":
                raise InvalidCalculationData(
                    "Нормативное зонирование сейчас поддерживает только прямоугольный план. "
                    "Разбейте сложный план на прямоугольники и рассчитайте их отдельно."
                )
            insulation_resistance = _ground_insulation_resistance(data)
            exterior_sides = _ground_exterior_sides(data)
            ground_zones = ground_floor_zones(
                length,
                width,
                insulation_resistance,
                exterior_sides,
                _strict_bool(data, "floor_on_joists", default=False),
            )
        else:
            surfaces.append(
                OpaqueSurface(
                    "Пол",
                    floor_area,
                    _surface_layers(data, "floor"),
                    floor_boundary,
                    _optional_number(data, "floor_adjacent_temperature", -80, 70),
                    SurfaceKind.FLOOR,
                )
            )

        ceiling_boundary = _boundary(data, "ceiling_boundary")
        if ceiling_boundary == Boundary.HEATED and data.get("ceiling_adjacent_temperature") is None:
            surfaces.append(
                OpaqueSurface(
                    "Потолок под соседом",
                    floor_area,
                    (),
                    ceiling_boundary,
                    kind=SurfaceKind.CEILING,
                )
            )
        else:
            surfaces.append(
                OpaqueSurface(
                    "Потолок / кровля",
                    floor_area,
                    _surface_layers(data, "ceiling"),
                    ceiling_boundary,
                    _optional_number(data, "ceiling_adjacent_temperature", -80, 70),
                    SurfaceKind.ROOF
                    if ceiling_boundary == Boundary.OUTDOOR
                    else SurfaceKind.CEILING,
                )
            )

        openings = _openings(data)
        bridges = tuple(
            LinearThermalBridge(
                name=_short_name(item, "name", "мостика"),
                length_m=_mapping_number(item, "length_m", 0.01, 10_000),
                psi_w_mk=_mapping_number(item, "psi_w_mk", 0, 5),
            )
            for item in _mapping_list(data, "linear_thermal_bridges", "мостиков холода", maximum=30)
        )
        return Building(
            indoor_temperature_c=indoor,
            outdoor_temperature_c=outdoor,
            volume_m3=volume,
            opaque_surfaces=tuple(surfaces),
            heated_area_m2=floor_area,
            length_m=length,
            width_m=width,
            height_m=height,
            openings=tuple(openings),
            ground_floor_zones=ground_zones,
            linear_thermal_bridges=bridges,
            assumptions=assumptions_from_answers(data),
            airflow=_airflow_from_answers(data, floor_area),
            air_changes_per_hour=air_changes,
            heat_recovery_efficiency=_number(
                data, "heat_recovery_efficiency", 0, 0.95, default=0.0
            ),
            thermal_bridge_factor=_number(data, "thermal_bridge_factor", 0, 0.5, default=0.0),
            safety_factor=_number(data, "safety_factor", 1, 1.5, default=1.10),
        )
    except InvalidCalculationData:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise InvalidCalculationData(f"Некорректные исходные данные: {exc}") from exc


def _airflow_from_answers(data: dict[str, Any], heated_area_m2: float) -> Airflow | None:
    component_keys = {
        "mechanical_ventilation_m3_h",
        "natural_ventilation_m3_h",
        "infiltration_m3_h",
    }
    has_components = bool(component_keys.intersection(data))
    if data.get("infiltration_paths") and not has_components:
        raise InvalidCalculationData(
            "Заданы группы инфильтрации, но отсутствуют поля расходов воздуха"
        )
    if not has_components:
        return None
    input_basis = str(data.get("airflow_input_basis", "components_m3_h"))
    if input_basis == "components_m3h":
        input_basis = "components_m3_h"
    infiltration_basis = str(data.get("infiltration_basis", "manual_flow"))
    infiltration_flow = _number(data, "infiltration_m3_h", 0, 10_000_000, default=0.0)
    living_area_raw = data.get("infiltration_living_area_m2")
    if living_area_raw is None:
        living_area = (
            infiltration_flow / 3
            if infiltration_basis in {"appendix8_residential_exhaust", "appendix8_envelope"}
            else 0.0
        )
    else:
        living_area = _number(data, "infiltration_living_area_m2", 0, heated_area_m2)
    if infiltration_basis == "appendix8_residential_exhaust" and living_area <= 0:
        raise InvalidCalculationData("Для формулы 2 требуется положительная жилая площадь")
    if infiltration_basis in {"appendix8_residential_exhaust", "appendix8_envelope"}:
        expected_flow = 3 * living_area
        if not math.isclose(infiltration_flow, expected_flow, rel_tol=1e-9, abs_tol=1e-6):
            raise InvalidCalculationData(
                "Расход инфильтрации не совпадает с 3 м³/ч × площадь жилых комнат"
            )
    elif living_area_raw is not None and living_area > 0:
        raise InvalidCalculationData(
            "Жилая площадь для инфильтрации допустима только для формул приложения 8"
        )

    def pressure_input(item: dict[str, Any], key: str) -> Appendix8PressureInput | None:
        raw = item.get(key)
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise InvalidCalculationData(f"Поле {key} должно быть объектом")
        return Appendix8PressureInput(
            building_height_m=_mapping_number(raw, "building_height_m", 0.01, 1_000),
            opening_height_m=_mapping_number(raw, "opening_height_m", 0, 1_000),
            indoor_temperature_c=_mapping_number(raw, "indoor_temperature_c", -80, 100),
            outdoor_temperature_c=_mapping_number(raw, "outdoor_temperature_c", -100, 80),
            outdoor_air_density_kg_m3=_mapping_number(raw, "outdoor_air_density_kg_m3", 0.5, 2),
            wind_speed_m_s=_mapping_number(raw, "wind_speed_m_s", 0, 100),
            windward_coefficient=_mapping_number(raw, "windward_coefficient", -5, 5),
            leeward_coefficient=_mapping_number(raw, "leeward_coefficient", -5, 5),
            height_factor=_mapping_number(raw, "height_factor", 0, 10),
            internal_pressure_pa=_mapping_number(raw, "internal_pressure_pa", -5_000, 5_000),
        )

    infiltration_paths = tuple(
        InfiltrationPath(
            pressure_pa=_mapping_number(item, "pressure_pa", 0.01, 5_000),
            first_floor_pressure_pa=_mapping_number(item, "first_floor_pressure_pa", 0.01, 5_000),
            opening_area_m2=_mapping_number(item, "opening_area_m2", 0, 100_000),
            air_permeability_resistance_m2_h_pa_kg=_mapping_number(
                item,
                "air_permeability_resistance_m2_h_pa_kg",
                0,
                1_000_000,
            ),
            envelope_area_m2=_mapping_number(item, "envelope_area_m2", 0, 1_000_000),
            normative_air_permeability_kg_m2_h=_mapping_number(
                item,
                "normative_air_permeability_kg_m2_h",
                0,
                10_000,
            ),
            gap_area_m2=_mapping_number(item, "gap_area_m2", 0, 10_000),
            panel_joint_length_m=_mapping_number(item, "panel_joint_length_m", 0, 1_000_000),
            pressure_input=pressure_input(item, "pressure_input"),
            first_floor_pressure_input=pressure_input(item, "first_floor_pressure_input"),
        )
        for item in _mapping_list(
            data, "infiltration_paths", "групп давления инфильтрации", maximum=50
        )
    )
    return Airflow(
        mechanical_m3_h=_number(data, "mechanical_ventilation_m3_h", 0, 10_000_000, default=0.0),
        natural_m3_h=_number(data, "natural_ventilation_m3_h", 0, 10_000_000, default=0.0),
        infiltration_m3_h=infiltration_flow,
        heat_recovery_efficiency=_number(data, "heat_recovery_efficiency", 0, 0.95, default=0.0),
        input_basis=input_basis,
        infiltration_basis=infiltration_basis,
        infiltration_paths=infiltration_paths,
    )


def climate_from_answers(data: dict[str, Any]) -> ClimateProfile | None:
    key = data.get("climate_key")
    if key in CLIMATES:
        profile = CLIMATES[key]
        if data.get("confirmed_design_c") is not None:
            confirmed_design = _number(data, "confirmed_design_c", -80, 15)
            if not profile.observed_extreme_c <= confirmed_design < profile.cold_month_mean_c:
                raise InvalidCalculationData(
                    "Расчётная температура должна быть не ниже абсолютного минимума "
                    "и холоднее среднего холодного месяца"
                )
            confirmed_source = _source_text(data, "confirmed_design_source")
            return replace(
                profile,
                design_c=confirmed_design,
                source_note=(
                    "средние и экстремумы — ШНҚ 2.01.01-22; расчётная температура "
                    "параметра Б (наиболее холодная пятидневка 0,92 по ШНҚ 2.01.18-24, "
                    "п. 16) введена пользователем; источник значения: "
                    f"{confirmed_source}"
                ),
                provenance=tuple(
                    item for item in profile.provenance if item.parameter != "design_c"
                )
                + (
                    ValueSource(
                        parameter="design_c",
                        value=confirmed_design,
                        unit="°C",
                        document=confirmed_source,
                        edition="пользовательский источник; редакция не проверена",
                        location=(
                            "значение введено пользователем; определение параметра Б: "
                            "ШНҚ 2.01.01-22, п. 14 и таблица 4; метод выбора расчётной "
                            "зимней температуры: ШНҚ 2.01.18-24, п. 16"
                        ),
                        url="https://lex.uz/docs/-6363141",
                        observation_period="не указан пользователем",
                        updated_at="в момент расчёта",
                        status="user_supplied_unverified",
                    ),
                ),
            )
        return profile
    if key in {None, "manual"}:
        return None
    if key != "custom":
        raise InvalidCalculationData("Неизвестный климатический профиль")
    custom_values = (
        (
            "cold_month_mean_c",
            _number(data, "custom_cold_mean", -80, 50),
            "таблица/ряд среднего холодного месяца",
        ),
        ("design_c", _number(data, "custom_design", -80, 50), "расчётная температура отопления"),
        (
            "observed_extreme_c",
            _number(data, "custom_extreme", -80, 50),
            "абсолютный наблюдавшийся минимум",
        ),
        (
            "hot_month_mean_c",
            _number(data, "custom_hot_mean", -30, 70),
            "таблица/ряд среднего жаркого месяца",
        ),
        (
            "observed_maximum_c",
            _number(data, "custom_hot_max", -30, 70),
            "абсолютный наблюдавшийся максимум",
        ),
    )
    cold_mean = custom_values[0][1]
    design = custom_values[1][1]
    extreme = custom_values[2][1]
    hot_mean = custom_values[3][1]
    hot_maximum = custom_values[4][1]
    if not extreme <= design < cold_mean:
        raise InvalidCalculationData(
            "Для климата требуется: абсолютный минимум ≤ расчётный мороз < среднее холодного месяца"
        )
    if hot_mean < cold_mean:
        raise InvalidCalculationData(
            "Средний жаркий месяц не может быть холоднее среднего холодного месяца"
        )
    if hot_maximum < hot_mean:
        raise InvalidCalculationData(
            "Абсолютный максимум не может быть ниже среднего жаркого месяца"
        )
    custom_source = _source_text(data, "custom_climate_source")
    return ClimateProfile(
        key="custom",
        name=_text(data, "custom_city_name", 2, 80),
        cold_month_mean_c=custom_values[0][1],
        design_c=custom_values[1][1],
        observed_extreme_c=custom_values[2][1],
        hot_month_mean_c=custom_values[3][1],
        observed_maximum_c=custom_values[4][1],
        source_note=(
            "климатические значения введены пользователем и требуют проверки; "
            f"источник: {custom_source}"
        ),
        source_url="",
        data_period="период наблюдений не указан пользователем",
        version="custom",
        updated_at="в момент расчёта",
        provenance=tuple(
            ValueSource(
                parameter=parameter,
                value=value,
                unit="°C",
                document=custom_source,
                edition="пользовательский источник; редакция не проверена",
                location=location,
                url="",
                observation_period="не указан пользователем",
                updated_at="в момент расчёта",
                status="user_supplied_unverified",
            )
            for parameter, value, location in custom_values
        ),
    )


def assumptions_from_answers(data: dict[str, Any]) -> tuple[str, ...]:
    assumptions: list[str] = []
    if data.get("climate_key") == "manual":
        source = _source_text(data, "manual_climate_source")
        assumptions.append(
            "Расчётная наружная температура введена пользователем; источник значения: "
            f"{source}. Значение не маркируется как нормативное."
        )
    if data.get("airflow_input_basis") == "quick_estimate":
        assumptions.append(
            "Воздушные потери заданы упрощённой общей кратностью как невосстанавливаемый "
            "поток. Для подбора рекуператора нужен раздельный расход вентиляции и инфильтрации."
        )
    if data.get("infiltration_basis") == "appendix8_residential_exhaust":
        assumptions.append(
            "Инфильтрация рассчитана как нижняя оценка по формуле 2 приложения 8 "
            "ШНҚ 2.04.05-22: 3 м³/ч на 1 м² жилой площади для некомпенсированной "
            "естественной вытяжки. Норма требует принять большее из формул 1 и 2; "
            "расчёт через воздухопроницаемость и давление нужно проверить отдельно."
        )
    if data.get("infiltration_basis") == "appendix8_envelope":
        comparison = (
            " Для жилого объекта результат сопоставлен с формулой 2 и принято большее значение."
            if _number(data, "infiltration_m3_h", 0, 10_000_000, default=0.0) > 0
            else " Формула 2 не применялась: жилая площадь указана как 0."
        )
        assumptions.append(
            "Инфильтрация рассчитана по формуле 3 приложения 8 ШНҚ 2.04.05-22 из "
            "введённых пользователем перепадов давления, Ru, Gn, площадей и длин стыков."
            + comparison
        )
    window_groups = _mapping_list(data, "window_groups", "групп окон", maximum=20)
    door_groups = _mapping_list(data, "door_groups", "групп дверей", maximum=20)
    has_unassigned_windows = any(not group.get("wall_name") for group in window_groups) or (
        not window_groups and float(data.get("window_area") or 0) > 0
    )
    has_unassigned_doors = any(not group.get("wall_name") for group in door_groups) or (
        not door_groups and float(data.get("door_area") or 0) > 0
    )
    has_unassigned_openings = has_unassigned_windows or has_unassigned_doors
    if data.get("wall_groups") and has_unassigned_openings:
        assumptions.append(
            "Непривязанные проёмы распределены между стенами пропорционально свободной "
            "площади; ориентационная добавка для них не определена и принята β=0."
        )
    uses_unheated_estimate = (
        data.get("floor_boundary") == "unheated" and data.get("floor_adjacent_temperature") is None
    ) or (
        data.get("ceiling_boundary") == "unheated"
        and data.get("ceiling_adjacent_temperature") is None
    )
    if uses_unheated_estimate:
        assumptions.append(
            "Для холодного подвала/чердака использована оценка 70% наружной ΔT; "
            "это не заявлено как нормативный коэффициент."
        )
    if (
        data.get("floor_boundary") == "ground"
        and data.get("floor_ground_method") != "zonal"
        and data.get("floor_adjacent_temperature") is None
    ):
        assumptions.append(
            "Для упрощённого пола по грунту использована оценка 50% наружной ΔT; "
            "это не нормативный зональный метод."
        )
    if data.get("floor_ground_method") == "zonal":
        raw_sides = data.get("ground_exterior_sides")
        sides = _ground_exterior_sides(data)
        side_note = (
            "; для старого расчёта принято, что наружные все четыре стороны"
            if raw_sides is None
            else ", наружные стороны: " + ", ".join(sides)
        )
        assumptions.append(
            "Пол по грунту рассчитан по приложению 9 ШНҚ 2.04.05-22: "
            "полосы шириной 2 м с R=2,1 / 4,3 / 8,5 / 14,2 м²·К/Вт; "
            "угловые участки зоны I учтены дважды; добавлено сопротивление "
            f"указанного слоя с λ<1,2 Вт/(м·К){side_note}."
        )
        if _strict_bool(data, "floor_on_joists", default=False):
            assumptions.append("Для пола на лагах сопротивления зон умножены на 1,18.")
    if data.get("thermal_bridge_factor", 0) > 0:
        assumptions.append(
            "Процентная поправка мостиков холода применена ко всей базовой "
            "трансмиссионной нагрузке; это оценка, а не расчёт узлов."
        )
    return tuple(assumptions)


def _wall_surfaces(data: dict[str, Any]) -> list[OpaqueSurface]:
    window_area = _number(data, "window_area", 0, 100_000)
    door_area = _number(data, "door_area", 0, 100_000)
    opening_area = window_area + door_area
    groups = _mapping_list(data, "wall_groups", "групп стен", maximum=12)
    if not groups:
        gross_area = _number(data, "wall_gross_area", 0.1, 100_000)
        if opening_area > gross_area:
            raise InvalidCalculationData("Площадь проёмов больше площади стен")
        return [
            OpaqueSurface(
                "Наружные стены",
                gross_area - opening_area,
                _wall_layers(data),
                kind=SurfaceKind.WALL,
            )
        ]

    names: set[str] = set()
    assigned_by_wall: dict[str, float] = {}
    for group in groups:
        name = _short_name(group, "name", "стены")
        folded = name.casefold()
        if folded in names:
            raise InvalidCalculationData(f"Название стены «{name}» повторяется")
        names.add(folded)
        assigned_by_wall[name] = 0.0

    window_groups = _mapping_list(data, "window_groups", "групп окон", maximum=20)
    door_groups = _mapping_list(data, "door_groups", "групп дверей", maximum=20)
    for opening_group in [*window_groups, *door_groups]:
        wall_name = opening_group.get("wall_name")
        if wall_name:
            if wall_name not in assigned_by_wall:
                raise InvalidCalculationData(f"Не найдена стена «{wall_name}»")
            assigned_by_wall[wall_name] += _mapping_number(opening_group, "area_m2", 0.01, 100_000)

    unassigned_opening_area = 0.0
    if window_groups:
        unassigned_opening_area += sum(
            _mapping_number(item, "area_m2", 0.01, 100_000)
            for item in window_groups
            if not item.get("wall_name")
        )
    else:
        unassigned_opening_area += window_area
    if door_groups:
        unassigned_opening_area += sum(
            _mapping_number(item, "area_m2", 0.01, 100_000)
            for item in door_groups
            if not item.get("wall_name")
        )
    else:
        unassigned_opening_area += door_area

    remaining_area = 0.0
    for group in groups:
        name = _short_name(group, "name", "стены")
        capacity = _mapping_number(group, "gross_area_m2", 0.1, 100_000)
        if assigned_by_wall[name] > capacity:
            raise InvalidCalculationData(f"Проёмы на стене «{name}» больше её площади")
        remaining_area += capacity - assigned_by_wall[name]
    if unassigned_opening_area > remaining_area:
        raise InvalidCalculationData("Непривязанные проёмы больше оставшейся площади стен")

    result: list[OpaqueSurface] = []
    for group in groups:
        name = _short_name(group, "name", "стены")
        capacity = _mapping_number(group, "gross_area_m2", 0.1, 100_000) - assigned_by_wall[name]
        share = unassigned_opening_area * capacity / remaining_area if remaining_area else 0.0
        orientation = _orientation(group)
        result.append(
            OpaqueSurface(
                f"Стена: {name}",
                capacity - share,
                _group_layers(group),
                kind=SurfaceKind.WALL,
                additional_heat_loss_factor=orientation_heat_loss_factor(orientation),
                orientation=orientation,
            )
        )
    return result


def _orientation(group: dict[str, Any]) -> Orientation | None:
    value = group.get("orientation")
    if value in {None, "", "unknown"}:
        return None
    try:
        return Orientation(str(value))
    except ValueError as exc:
        raise InvalidCalculationData(f"Неизвестная ориентация стены: {value}") from exc


def _openings(data: dict[str, Any]) -> list[Opening]:
    result: list[Opening] = []
    wall_orientations = {
        _short_name(group, "name", "стены"): _orientation(group)
        for group in _mapping_list(data, "wall_groups", "групп стен", maximum=12)
    }
    window_groups = _mapping_list(data, "window_groups", "групп окон", maximum=20)
    if window_groups:
        for group in window_groups:
            count = _mapping_integer(group, "count", 1, 500)
            orientation = wall_orientations.get(group.get("wall_name"))
            result.append(
                Opening(
                    f"{_short_name(group, 'name', 'окна')} ({count} шт.)",
                    _mapping_number(group, "area_m2", 0.01, 10_000),
                    _mapping_number(group, "u_value", 0.1, 10),
                    value_status="passport_user_input",
                    source_note="Паспортный U введён пользователем",
                    additional_heat_loss_factor=orientation_heat_loss_factor(orientation),
                    orientation=orientation,
                )
            )
    else:
        area = _number(data, "window_area", 0, 10_000)
        if area:
            window_key = data.get("window_type")
            if window_key not in WINDOWS:
                raise InvalidCalculationData("Неизвестный тип окна")
            count = _mapping_integer(data, "window_count", 0, 500) if "window_count" in data else 0
            name = f"Окна ({count} шт.)" if count else "Окна"
            window = WINDOWS[window_key]
            result.append(
                Opening(
                    name,
                    area,
                    window.u_value,
                    value_status=window.value_status,
                    source_note=window.source_note,
                )
            )

    door_groups = _mapping_list(data, "door_groups", "групп дверей", maximum=20)
    if door_groups:
        for group in door_groups:
            count = _mapping_integer(group, "count", 1, 100)
            orientation = wall_orientations.get(group.get("wall_name"))
            result.append(
                Opening(
                    f"{_short_name(group, 'name', 'двери')} ({count} шт.)",
                    _mapping_number(group, "area_m2", 0.01, 10_000),
                    _mapping_number(group, "u_value", 0.1, 10),
                    value_status="passport_user_input",
                    source_note="Паспортный U введён пользователем",
                    additional_heat_loss_factor=orientation_heat_loss_factor(orientation),
                    orientation=orientation,
                )
            )
    else:
        area = _number(data, "door_area", 0, 10_000)
        if area:
            door_key = data.get("door_type")
            door = DOORS.get(door_key) if isinstance(door_key, str) else None
            result.append(
                Opening(
                    "Наружные двери",
                    area,
                    _number(data, "door_u_value", 0.1, 10, default=2.0),
                    value_status=door.value_status if door else "legacy_reference",
                    source_note=door.source_note if door else "Старое справочное значение U",
                )
            )
    return result


def _wall_layers(data: dict[str, Any]) -> tuple[Layer, ...]:
    layers = [
        _layer(
            data.get("wall_material"),
            _number(data, "wall_thickness", 0.001, 2),
            data.get("wall_conductivity"),
        )
    ]
    if data.get("insulation_material"):
        layers.append(
            _layer(
                data.get("insulation_material"),
                _number(data, "insulation_thickness", 0.001, 2),
                data.get("insulation_conductivity"),
            )
        )
    return tuple(layers)


def _group_layers(group: dict[str, Any]) -> tuple[Layer, ...]:
    explicit_layers = group.get("layers")
    if explicit_layers is not None:
        if not isinstance(explicit_layers, list) or not 1 <= len(explicit_layers) <= 10:
            raise InvalidCalculationData("Конструкция стены должна содержать от 1 до 10 слоёв")
        if not all(isinstance(item, dict) for item in explicit_layers):
            raise InvalidCalculationData("Каждый слой стены должен быть объектом")
        return tuple(
            _layer(
                item.get("material"),
                _mapping_number(item, "thickness_m", 0.001, 2),
                item.get("material_conductivity"),
            )
            for item in explicit_layers
        )
    layers = [
        _layer(
            group.get("material"),
            _mapping_number(group, "thickness_m", 0.001, 2),
            group.get("material_conductivity"),
        )
    ]
    if group.get("insulation_material"):
        layers.append(
            _layer(
                group.get("insulation_material"),
                _mapping_number(group, "insulation_thickness_m", 0.001, 2),
                group.get("insulation_conductivity"),
            )
        )
    return tuple(layers)


def _surface_layers(data: dict[str, Any], surface: str) -> tuple[Layer, ...]:
    explicit_layers = data.get(f"{surface}_layers")
    if explicit_layers is not None:
        if not isinstance(explicit_layers, list) or not 1 <= len(explicit_layers) <= 10:
            raise InvalidCalculationData(
                "Конструкция пола или потолка должна содержать от 1 до 10 слоёв"
            )
        if not all(isinstance(item, dict) for item in explicit_layers):
            raise InvalidCalculationData("Каждый слой пола или потолка должен быть объектом")
        return tuple(
            _layer(
                item.get("material"),
                _mapping_number(item, "thickness_m", 0.001, 2),
                item.get("material_conductivity"),
            )
            for item in explicit_layers
        )
    material = data.get(f"{surface}_material", "concrete")
    thickness = _number(data, f"{surface}_thickness", 0.001, 2, default=0.20)
    layers = [_layer(material, thickness, data.get(f"{surface}_conductivity"))]
    insulation_material = data.get(f"{surface}_insulation_material")
    insulation_key = f"{surface}_insulation_thickness"
    legacy_insulation_key = f"{surface}_insulation"
    if insulation_key in data:
        insulation_thickness = _number(data, insulation_key, 0, 2)
    elif legacy_insulation_key in data:
        insulation_thickness = _number(data, legacy_insulation_key, 0, 2)
    else:
        insulation_thickness = 0.0
    if insulation_thickness:
        layers.append(
            _layer(
                insulation_material or "mineral_wool",
                insulation_thickness,
                data.get(f"{surface}_insulation_conductivity"),
            )
        )
    return tuple(layers)


def _ground_insulation_resistance(data: dict[str, Any]) -> float:
    material_key = data.get("floor_insulation_material")
    if not material_key:
        return 0.0
    layer = _layer(
        material_key,
        _number(data, "floor_insulation_thickness", 0.001, 2),
        data.get("floor_insulation_conductivity"),
    )
    conductivity = layer.conductivity_w_mk or MATERIALS[layer.material_key].conductivity
    if conductivity >= 1.2:
        raise InvalidCalculationData(
            "Для добавки к нормативному R пола по грунту требуется слой с λ<1,2 Вт/(м·К)"
        )
    return layer.thickness_m / conductivity


def _layer(material_key: Any, thickness: float, conductivity: Any) -> Layer:
    if not isinstance(material_key, str) or not material_key:
        raise InvalidCalculationData("Не выбран материал конструкции")
    if material_key == "custom":
        value = _finite(conductivity, "Паспортная λ")
        return Layer(material_key, thickness, value)
    if material_key not in MATERIALS:
        raise InvalidCalculationData(f"Неизвестный материал: {material_key}")
    return Layer(material_key, thickness)


def _boundary(data: dict[str, Any], key: str) -> Boundary:
    try:
        return Boundary(data[key])
    except (KeyError, ValueError) as exc:
        raise InvalidCalculationData(f"Не выбрано корректное условие: {key}") from exc


def _number(
    data: dict[str, Any],
    key: str,
    minimum: float,
    maximum: float,
    *,
    default: float | None = None,
) -> float:
    if key not in data:
        if default is None:
            raise InvalidCalculationData(f"Не заполнено поле: {key}")
        return default
    value = _finite(data[key], key)
    if not minimum <= value <= maximum:
        raise InvalidCalculationData(f"Поле {key} должно быть от {minimum:g} до {maximum:g}")
    return value


def _optional_number(
    data: dict[str, Any], key: str, minimum: float, maximum: float
) -> float | None:
    if data.get(key) is None:
        return None
    return _number(data, key, minimum, maximum)


def _mapping_number(data: dict[str, Any], key: str, minimum: float, maximum: float) -> float:
    return _number(data, key, minimum, maximum)


def _mapping_integer(data: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = _mapping_number(data, key, minimum, maximum)
    if not value.is_integer():
        raise InvalidCalculationData(f"Поле {key} должно быть целым числом")
    return int(value)


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise InvalidCalculationData(f"{label} должно быть числом")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidCalculationData(f"{label} должно быть числом") from exc
    if not math.isfinite(number):
        raise InvalidCalculationData(f"{label} должно быть конечным числом")
    return number


def volume_height(data: dict[str, Any], length: float, width: float) -> float:
    """Compatibility fallback for older FSM payloads that only stored volume."""
    volume = _number(data, "volume", 1, 10_000_000)
    return volume / (length * width)


def _text(data: dict[str, Any], key: str, minimum: int, maximum: int) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise InvalidCalculationData(f"Некорректное текстовое поле: {key}")
    value = value.strip()
    if not minimum <= len(value) <= maximum or any(
        unicodedata.category(character).startswith("C") for character in value
    ):
        raise InvalidCalculationData(f"Некорректное текстовое поле: {key}")
    return value


def _short_name(data: dict[str, Any], key: str, label: str) -> str:
    try:
        return _text(data, key, 1, 60)
    except InvalidCalculationData as exc:
        raise InvalidCalculationData(f"Некорректное название {label}") from exc


def _source_text(data: dict[str, Any], key: str) -> str:
    raw = data.get(key)
    if raw is None or (isinstance(raw, str) and raw.strip() in {"", "-"}):
        return "не указан пользователем"
    return _text(data, key, 3, 300)


def _mapping_list(
    data: dict[str, Any],
    key: str,
    label: str,
    *,
    maximum: int,
) -> list[dict[str, Any]]:
    raw = data.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise InvalidCalculationData(f"Поле {key} должно быть списком {label}")
    if len(raw) > maximum:
        raise InvalidCalculationData(f"Поле {key}: допустимо не более {maximum} {label}")
    if not all(isinstance(item, dict) for item in raw):
        raise InvalidCalculationData(
            f"Поле {key}: каждый элемент списка {label} должен быть объектом"
        )
    return raw


def _validate_collection_shapes(data: dict[str, Any]) -> None:
    limits = (
        ("wall_groups", "групп стен", 12),
        ("window_groups", "групп окон", 20),
        ("door_groups", "групп дверей", 20),
        ("linear_thermal_bridges", "мостиков холода", 30),
        ("infiltration_paths", "групп давления инфильтрации", 50),
    )
    for key, label, maximum in limits:
        _mapping_list(data, key, label, maximum=maximum)


def _strict_bool(data: dict[str, Any], key: str, *, default: bool) -> bool:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise InvalidCalculationData(f"Поле {key} должно быть логическим значением")
    return value


def _ground_exterior_sides(data: dict[str, Any]) -> tuple[str, ...]:
    raw = data.get("ground_exterior_sides")
    if raw is None:
        return ("north", "east", "south", "west")
    if not isinstance(raw, (list, tuple)) or not 1 <= len(raw) <= 4:
        raise InvalidCalculationData(
            "Поле ground_exterior_sides должно содержать от 1 до 4 наружных сторон"
        )
    sides = tuple(raw)
    allowed = {"north", "east", "south", "west"}
    if any(not isinstance(side, str) or side not in allowed for side in sides):
        raise InvalidCalculationData("Поле ground_exterior_sides содержит неизвестную сторону")
    if len(set(sides)) != len(sides):
        raise InvalidCalculationData("Поле ground_exterior_sides содержит повторяющиеся стороны")
    return sides


def _validate_opening_group_semantics(data: dict[str, Any]) -> None:
    specifications = (
        ("window_groups", "окон", 500),
        ("door_groups", "дверей", 100),
    )
    for key, label, maximum_count in specifications:
        aggregate_count_key = "window_count" if key == "window_groups" else "door_count"
        if aggregate_count_key in data:
            _mapping_integer(data, aggregate_count_key, 0, maximum_count)
        for group in _mapping_list(data, key, f"групп {label}", maximum=20):
            count = _mapping_integer(group, "count", 1, maximum_count)
            area = _mapping_number(group, "area_m2", 0.01, 10_000)
            width = group.get("width_m")
            height = group.get("height_m")
            if width is None and height is None:
                continue
            if width is None or height is None:
                raise InvalidCalculationData(
                    f"Для группы {label} ширина и высота должны быть заданы вместе"
                )
            expected_area = (
                count
                * _mapping_number(group, "width_m", 0.1, 1_000)
                * _mapping_number(group, "height_m", 0.1, 100)
            )
            if not math.isclose(area, expected_area, rel_tol=1e-9, abs_tol=1e-6):
                raise InvalidCalculationData(
                    f"Площадь группы {label} не совпадает с количеством × шириной × высотой"
                )
