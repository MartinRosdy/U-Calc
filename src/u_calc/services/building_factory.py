from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from ..calculator import ground_floor_zones, orientation_heat_loss_factor
from ..catalog import CLIMATES, DOORS, MATERIALS, WINDOWS, ClimateProfile, ValueSource
from ..models import (
    Airflow,
    Boundary,
    Building,
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
            exterior_sides = tuple(
                data.get("ground_exterior_sides") or ("north", "east", "south", "west")
            )
            ground_zones = ground_floor_zones(
                length,
                width,
                insulation_resistance,
                exterior_sides,
                bool(data.get("floor_on_joists", False)),
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
            for item in data.get("linear_thermal_bridges", [])
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
            airflow=_airflow_from_answers(data),
            air_changes_per_hour=air_changes,
            heat_recovery_efficiency=_number(
                data, "heat_recovery_efficiency", 0, 0.95, default=0.0
            ),
            thermal_bridge_factor=_number(data, "thermal_bridge_factor", 0, 0.5, default=0.0),
            safety_factor=_number(data, "safety_factor", 1, 1.5, default=1.10),
        )
    except InvalidCalculationData:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidCalculationData(f"Некорректные исходные данные: {exc}") from exc


def _airflow_from_answers(data: dict[str, Any]) -> Airflow | None:
    component_keys = {
        "mechanical_ventilation_m3_h",
        "natural_ventilation_m3_h",
        "infiltration_m3_h",
    }
    if not component_keys.intersection(data):
        return None
    return Airflow(
        mechanical_m3_h=_number(data, "mechanical_ventilation_m3_h", 0, 10_000_000, default=0.0),
        natural_m3_h=_number(data, "natural_ventilation_m3_h", 0, 10_000_000, default=0.0),
        infiltration_m3_h=_number(data, "infiltration_m3_h", 0, 10_000_000, default=0.0),
        heat_recovery_efficiency=_number(data, "heat_recovery_efficiency", 0, 0.95, default=0.0),
        input_basis=str(data.get("airflow_input_basis", "components_m3_h")),
    )


def climate_from_answers(data: dict[str, Any]) -> ClimateProfile | None:
    key = data.get("climate_key")
    if key in CLIMATES:
        profile = CLIMATES[key]
        if data.get("confirmed_design_c") is not None:
            confirmed_design = _number(data, "confirmed_design_c", -80, 15)
            return replace(
                profile,
                design_c=confirmed_design,
                source_note=(
                    "средние и экстремумы — ШНҚ 2.01.01-22; расчётная температура "
                    "параметра Б подтверждена пользователем"
                ),
                provenance=profile.provenance
                + (
                    ValueSource(
                        parameter="design_c",
                        value=confirmed_design,
                        unit="°C",
                        document="ШНҚ 2.01.01-22",
                        edition="утверждён 19.12.2022",
                        location=(
                            "п. 14 и приложение, таблица 4, параметр Б холодного периода; "
                            "значение введено пользователем"
                        ),
                        url="https://lex.uz/docs/-6363141",
                        observation_period="подтверждается пользователем",
                        updated_at="в момент расчёта",
                        status="user_confirmed",
                    ),
                ),
            )
        return profile
    if key in {None, "manual"}:
        return None
    if key != "custom":
        raise InvalidCalculationData("Неизвестный климатический профиль")
    return ClimateProfile(
        key="custom",
        name=_text(data, "custom_city_name", 2, 80),
        cold_month_mean_c=_number(data, "custom_cold_mean", -80, 50),
        design_c=_number(data, "custom_design", -80, 50),
        observed_extreme_c=_number(data, "custom_extreme", -80, 50),
        hot_month_mean_c=_number(data, "custom_hot_mean", -30, 70),
        observed_maximum_c=_number(data, "custom_hot_max", -30, 70),
        source_note="климатические значения введены пользователем и требуют проверки",
        source_url="",
        data_period="введено пользователем",
        version="custom",
        updated_at="не указано",
    )


def assumptions_from_answers(data: dict[str, Any]) -> tuple[str, ...]:
    assumptions: list[str] = []
    if data.get("airflow_input_basis") == "quick_estimate":
        assumptions.append(
            "Воздушные потери заданы упрощённой общей кратностью как невосстанавливаемый "
            "поток. Для подбора рекуператора нужен раздельный расход вентиляции и инфильтрации."
        )
    window_groups = data.get("window_groups") or []
    door_groups = data.get("door_groups") or []
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
        sides = data.get("ground_exterior_sides")
        side_note = (
            ", наружные стороны: " + ", ".join(str(side) for side in sides)
            if sides
            else "; для старого расчёта принято, что наружные все четыре стороны"
        )
        assumptions.append(
            "Пол по грунту рассчитан по приложению 9 ШНҚ 2.04.05-22: "
            "полосы шириной 2 м с R=2,1 / 4,3 / 8,5 / 14,2 м²·К/Вт; "
            "угловые участки зоны I учтены дважды; добавлено сопротивление "
            f"указанного слоя с λ<1,2 Вт/(м·К){side_note}."
        )
        if data.get("floor_on_joists"):
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
    groups = data.get("wall_groups")
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

    if not isinstance(groups, list) or not 1 <= len(groups) <= 12:
        raise InvalidCalculationData("Некорректный список групп стен")
    names: set[str] = set()
    assigned_by_wall: dict[str, float] = {}
    for group in groups:
        name = _short_name(group, "name", "стены")
        folded = name.casefold()
        if folded in names:
            raise InvalidCalculationData(f"Название стены «{name}» повторяется")
        names.add(folded)
        assigned_by_wall[name] = 0.0

    for opening_group in [*(data.get("window_groups") or []), *(data.get("door_groups") or [])]:
        wall_name = opening_group.get("wall_name")
        if wall_name:
            if wall_name not in assigned_by_wall:
                raise InvalidCalculationData(f"Не найдена стена «{wall_name}»")
            assigned_by_wall[wall_name] += _mapping_number(opening_group, "area_m2", 0.01, 100_000)

    unassigned_opening_area = 0.0
    if data.get("window_groups"):
        unassigned_opening_area += sum(
            _mapping_number(item, "area_m2", 0.01, 100_000)
            for item in data["window_groups"]
            if not item.get("wall_name")
        )
    else:
        unassigned_opening_area += window_area
    if data.get("door_groups"):
        unassigned_opening_area += sum(
            _mapping_number(item, "area_m2", 0.01, 100_000)
            for item in data["door_groups"]
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
        for group in (data.get("wall_groups") or [])
    }
    window_groups = data.get("window_groups") or []
    if window_groups:
        for group in window_groups:
            count = int(_mapping_number(group, "count", 1, 500))
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
            count = int(_number(data, "window_count", 0, 500, default=0))
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

    door_groups = data.get("door_groups") or []
    if door_groups:
        for group in door_groups:
            count = int(_mapping_number(group, "count", 1, 100))
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
    material = data.get(f"{surface}_material", "concrete")
    thickness = _number(data, f"{surface}_thickness", 0.001, 2, default=0.20)
    layers = [_layer(material, thickness, data.get(f"{surface}_conductivity"))]
    insulation_material = data.get(f"{surface}_insulation_material")
    insulation_thickness = _number(
        data,
        f"{surface}_insulation_thickness",
        0,
        2,
        default=float(data.get(f"{surface}_insulation", 0.0)),
    )
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
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise InvalidCalculationData(f"Некорректное текстовое поле: {key}")
    return value.strip()


def _short_name(data: dict[str, Any], key: str, label: str) -> str:
    try:
        return _text(data, key, 1, 60)
    except InvalidCalculationData as exc:
        raise InvalidCalculationData(f"Некорректное название {label}") from exc
