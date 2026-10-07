import math
import re
from typing import Any

MATERIAL_ALIASES = {
    "кирпич": "brick_solid",
    "полнотелый кирпич": "brick_solid",
    "brick_solid": "brick_solid",
    "пустотелый кирпич": "brick_hollow",
    "brick_hollow": "brick_hollow",
    "газоблок": "aerated_d500",
    "газобетон": "aerated_d500",
    "aerated_d500": "aerated_d500",
    "бетон": "concrete",
    "железобетон": "concrete",
    "concrete": "concrete",
    "дерево": "wood",
    "древесина": "wood",
    "wood": "wood",
    "минвата": "mineral_wool",
    "каменная вата": "mineral_wool",
    "mineral_wool": "mineral_wool",
    "пенопласт": "eps",
    "пенополистирол": "eps",
    "eps": "eps",
    "эппс": "xps",
    "xps": "xps",
    "ппу": "pu_foam",
    "пенополиуретан": "pu_foam",
    "pu_foam": "pu_foam",
}


def parse_number(
    value: str | None,
    *,
    minimum: float = 0.001,
    maximum: float = 1_000_000.0,
    label: str = "Значение",
) -> float:
    value = _require_text(value)
    try:
        number = float(value.strip().replace(",", "."))
    except ValueError as exc:
        raise ValueError("Введите число, например 12,5") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} должно быть конечным числом")
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} должно быть от {minimum:g} до {maximum:g}")
    return number


def parse_dimensions(value: str | None) -> list[tuple[float, float]]:
    """Parse `5x3, 4x3` wall dimensions, accepting x, х, * and ×."""
    value = _require_text(value)
    # A comma can be a decimal separator (4,5), so it separates walls only
    # when followed by whitespace: `5x3, 4x3`. Semicolons/newlines are unambiguous.
    chunks = re.split(r"[;\n]+|,\s+(?=\d)", value.strip().lower())
    result: list[tuple[float, float]] = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        parts = re.split(r"\s*[xх×*]\s*", chunk.strip())
        if len(parts) != 2:
            raise ValueError("Формат стен: 5x3, 4x3")
        result.append(
            (
                parse_number(parts[0], minimum=0.1, maximum=1_000, label="Размер"),
                parse_number(parts[1], minimum=0.1, maximum=100, label="Размер"),
            )
        )
    if not result:
        raise ValueError("Укажите хотя бы одну стену")
    return result


def parse_triplet(value: str | None) -> tuple[float, float, float]:
    value = _require_text(value)
    parts = re.split(r"[xх×*\s;,]+", value.strip().lower())
    if len(parts) != 3:
        raise ValueError("Введите длину, ширину и высоту: 10 8 3")
    return tuple(parse_number(item, minimum=0.1, maximum=1_000, label="Размер") for item in parts)  # type: ignore[return-value]


def parse_wall_groups(value: str | None) -> list[dict[str, Any]]:
    """Parse advanced wall rows separated by newlines.

    Format: name | area or width x height | material | thickness cm |
    insulation or `-` | insulation thickness cm.
    """
    value = _require_text(value)
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    for line_number, raw_line in enumerate(value.strip().splitlines(), start=1):
        if not raw_line.strip():
            continue
        fields = [item.strip() for item in raw_line.split("|")]
        if len(fields) not in (4, 6):
            raise ValueError(
                f"строка {line_number}: нужно 4 поля без утепления или 6 полей с утеплением"
            )
        name, area_text, material_text, thickness_text = fields[:4]
        if not name:
            raise ValueError(f"строка {line_number}: укажите название стены")
        folded_name = name.casefold()
        if folded_name in names:
            raise ValueError(f"строка {line_number}: название стены «{name}» уже использовано")
        names.add(folded_name)
        area = _parse_area_or_dimensions(area_text)
        material_key, material_conductivity = _material_spec(material_text, line_number)
        thickness_m = parse_number(thickness_text, minimum=0.1, maximum=200, label="Толщина") / 100
        insulation_material = None
        insulation_conductivity = None
        insulation_thickness_m = 0.0
        if len(fields) == 6 and fields[4].lower() not in {"-", "нет", "no"}:
            insulation_material, insulation_conductivity = _material_spec(fields[4], line_number)
            if insulation_conductivity is None and insulation_material not in {
                "mineral_wool",
                "eps",
                "xps",
                "pu_foam",
            }:
                raise ValueError(f"строка {line_number}: пятый столбец должен быть утеплителем")
            insulation_thickness_m = (
                parse_number(fields[5], minimum=0.1, maximum=200, label="Толщина утеплителя") / 100
            )
        elif len(fields) == 6 and fields[5] not in {"", "0", "-"}:
            raise ValueError(
                f"строка {line_number}: при отсутствии утеплителя толщина должна быть 0"
            )
        result.append(
            {
                "name": name[:60],
                "gross_area_m2": area,
                "material": material_key,
                "material_conductivity": material_conductivity,
                "thickness_m": thickness_m,
                "insulation_material": insulation_material,
                "insulation_conductivity": insulation_conductivity,
                "insulation_thickness_m": insulation_thickness_m,
            }
        )
    if not result:
        raise ValueError("укажите хотя бы одну стену")
    if len(result) > 12:
        raise ValueError("за один расчёт можно задать не более 12 групп стен")
    return result


def _parse_area_or_dimensions(value: str) -> float:
    if re.search(r"[xх×*]", value.lower()):
        dimensions = parse_dimensions(value)
        if len(dimensions) != 1:
            raise ValueError("в одной строке укажите одну пару размеров")
        return dimensions[0][0] * dimensions[0][1]
    return parse_number(value)


def _material_key(value: str, line_number: int) -> str:
    return _material_spec(value, line_number)[0]


def _material_spec(value: str, line_number: int) -> tuple[str, float | None]:
    normalized = " ".join(value.strip().lower().split())
    lambda_match = re.fullmatch(r"(?:λ|lambda)\s*=\s*([0-9]+(?:[.,][0-9]+)?)", normalized)
    if lambda_match:
        conductivity = float(lambda_match.group(1).replace(",", "."))
        if not math.isfinite(conductivity):
            raise ValueError(f"строка {line_number}: λ должна быть конечным числом")
        if not 0.005 <= conductivity <= 5:
            raise ValueError(f"строка {line_number}: λ должна быть от 0,005 до 5")
        return "custom", conductivity
    try:
        return MATERIAL_ALIASES[normalized], None
    except KeyError as exc:
        raise ValueError(f"строка {line_number}: неизвестный материал «{value}»") from exc


def parse_linear_thermal_bridges(value: str | None) -> list[dict[str, Any]]:
    """Parse `name | length m | psi W/(m·K)` rows."""
    value = _require_text(value)
    result: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(value.strip().splitlines(), start=1):
        if not raw_line.strip():
            continue
        fields = [item.strip() for item in raw_line.split("|")]
        if len(fields) != 3 or not fields[0]:
            raise ValueError(f"строка {line_number}: формат Название | длина | ψ")
        length_m = parse_number(fields[1], minimum=0.01, maximum=10_000, label="Длина мостика")
        psi = _parse_nonnegative(fields[2], "ψ")
        result.append({"name": fields[0][:60], "length_m": length_m, "psi_w_mk": psi})
    if not result:
        raise ValueError("укажите хотя бы один мостик холода")
    if len(result) > 30:
        raise ValueError("за один расчёт можно задать не более 30 мостиков холода")
    return result


def _parse_nonnegative(value: str, label: str) -> float:
    try:
        number = float(value.strip().replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"{label} должен быть числом") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} должен быть конечным числом")
    if number < 0:
        raise ValueError(f"{label} не может быть отрицательным")
    return number


def parse_window_groups(value: str | None) -> list[dict[str, Any]]:
    """Parse `name | count | width x height | U | optional wall name` rows."""
    value = _require_text(value)
    result: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(value.strip().splitlines(), start=1):
        if not raw_line.strip():
            continue
        fields = [item.strip() for item in raw_line.split("|")]
        if len(fields) not in (4, 5) or not fields[0]:
            raise ValueError(
                f"строка {line_number}: формат Название | количество | ширина×высота | U | стена"
            )
        try:
            count = int(fields[1])
        except ValueError as exc:
            raise ValueError(f"строка {line_number}: количество должно быть целым") from exc
        if not 1 <= count <= 200:
            raise ValueError(f"строка {line_number}: количество должно быть от 1 до 200")
        dimensions = parse_dimensions(fields[2])
        if len(dimensions) != 1:
            raise ValueError(f"строка {line_number}: укажите один размер окна")
        u_value = _parse_nonnegative(fields[3], "U-value")
        if not 0.1 <= u_value <= 8:
            raise ValueError(f"строка {line_number}: U-value должен быть от 0,1 до 8")
        width, height = dimensions[0]
        result.append(
            {
                "name": fields[0][:60],
                "count": count,
                "width_m": width,
                "height_m": height,
                "area_m2": count * width * height,
                "u_value": u_value,
                "wall_name": fields[4][:60] if len(fields) == 5 and fields[4] else None,
            }
        )
    if not result:
        raise ValueError("укажите хотя бы одну группу окон")
    if len(result) > 20:
        raise ValueError("за один расчёт можно задать не более 20 групп окон")
    return result


def parse_door_groups(value: str | None) -> list[dict[str, Any]]:
    """Parse `name | count | width x height | U | optional wall name` rows."""
    value = _require_text(value)
    result: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(value.strip().splitlines(), start=1):
        if not raw_line.strip():
            continue
        fields = [item.strip() for item in raw_line.split("|")]
        if len(fields) not in (4, 5) or not fields[0]:
            raise ValueError(
                f"строка {line_number}: формат Название | количество | ширина×высота | U | стена"
            )
        try:
            count = int(fields[1])
        except ValueError as exc:
            raise ValueError(f"строка {line_number}: количество должно быть целым") from exc
        if not 1 <= count <= 100:
            raise ValueError(f"строка {line_number}: количество должно быть от 1 до 100")
        dimensions = parse_dimensions(fields[2])
        if len(dimensions) != 1:
            raise ValueError(f"строка {line_number}: укажите один размер двери")
        u_value = _parse_nonnegative(fields[3], "U-value")
        if not 0.1 <= u_value <= 8:
            raise ValueError(f"строка {line_number}: U-value должен быть от 0,1 до 8")
        width, height = dimensions[0]
        result.append(
            {
                "name": fields[0][:60],
                "count": count,
                "width_m": width,
                "height_m": height,
                "area_m2": count * width * height,
                "u_value": u_value,
                "wall_name": fields[4][:60] if len(fields) == 5 and fields[4] else None,
            }
        )
    if not result:
        raise ValueError("укажите хотя бы одну группу дверей")
    if len(result) > 20:
        raise ValueError("за один расчёт можно задать не более 20 групп дверей")
    return result


def _require_text(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Отправьте значение текстовым сообщением")
    return value
