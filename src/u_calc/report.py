from decimal import ROUND_HALF_UP, Decimal

from .calculator import appendix8_infiltration_mass_flow
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
from .models import (
    Boundary,
    Building,
    HeatLossResult,
    Layer,
    OpaqueSurface,
    Orientation,
    SurfaceKind,
)

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

UZ_BOUNDARY_NAMES = {
    Boundary.OUTDOOR: "tashqi havo",
    Boundary.UNHEATED: "isitilmaydigan zona",
    Boundary.GROUND: "grunt",
    Boundary.HEATED: "isitiladigan xona",
}

UZ_ORIENTATION_NAMES = {
    Orientation.NORTH: "shimol",
    Orientation.NORTH_EAST: "shimoli-sharq",
    Orientation.EAST: "sharq",
    Orientation.SOUTH_EAST: "janubi-sharq",
    Orientation.SOUTH: "janub",
    Orientation.SOUTH_WEST: "janubi-g‘arb",
    Orientation.WEST: "g‘arb",
    Orientation.NORTH_WEST: "shimoli-g‘arb",
}

UZ_MATERIAL_NAMES = {
    "brick_solid": "to‘liq g‘isht",
    "brick_hollow": "g‘ovak g‘isht",
    "aerated_d500": "D500 gazoblok",
    "concrete": "temirbeton",
    "wood": "tolalarga ko‘ndalang yog‘och",
    "mineral_wool": "tikilgan mineral paxta mati",
    "eps": "EPS penopolistirol",
    "xps": "XPS ekstrudirovka penopolistirol",
    "pu_foam": "poliuretan ko‘pik",
}

UZ_SYSTEM_TEXT = {
    "Ограждение": "To‘siq",
    "Проём": "Ochiq",
    "Пол по грунту": "Gruntdagi pol",
    "Поправка": "Tuzatish",
    "Линейный мостик": "Chiziqli issiqlik ko‘prigi",
    "Вентиляция": "Ventilyatsiya",
    "Наружные стены": "Tashqi devorlar",
    "Пол над соседом": "Pastki qo‘shni ustidagi pol",
    "Пол": "Pol",
    "Потолок под соседом": "Yuqori qo‘shni ostidagi shift",
    "Потолок / кровля": "Shift / tom",
    "Окна": "Derazalar",
    "Наружные двери": "Tashqi eshiklar",
    "Механическая вентиляция": "Mexanik ventilyatsiya",
    "Естественная вентиляция": "Tabiiy ventilyatsiya",
    "Инфильтрация": "Infiltratsiya",
    "Мостики холода (оценка)": "Issiqlik ko‘priklari (baho)",
}

UZ_SYSTEM_PREFIXES = {
    "Стена: ": "Devor: ",
    "Мостик: ": "Ko‘prik: ",
    "Пол по грунту — зона ": "Gruntdagi pol — zona ",
    "Окна (": "Derazalar (",
}

RU_VALUE_STATUS = {
    "passport": "паспортное значение",
    "passport_user_input": "паспортное значение, введённое пользователем",
    "typical_reference": "типовое справочное значение",
    "reference_unverified": "непроверенное справочное значение",
    "normative_base_not_design": "нормативное базовое значение, не расчётное",
    "normative_design_b": "нормативное расчётное значение для условий Б",
    "legacy_reference_unverified": "устаревшее неподтверждённое справочное значение",
    "legacy_reference": "устаревшее справочное значение",
    "unspecified": "статус источника не указан",
    "user_supplied_unverified": "введено пользователем, не проверено",
    "normative": "нормативное значение",
    "user_confirmed": "подтверждено пользователем",
}

RU_CLIMATE_PARAMETER_NAMES = {
    "cold_month_mean_c": "средняя температура холодного месяца",
    "design_c": "расчётная температура холодного периода (параметр Б)",
    "observed_extreme_c": "наблюдавшийся абсолютный минимум",
    "hot_month_mean_c": "средняя температура жаркого месяца",
    "observed_maximum_c": "наблюдавшийся абсолютный максимум",
}

UZ_CLIMATE_PARAMETER_NAMES = {
    "cold_month_mean_c": "sovuq oyning o‘rtacha harorati",
    "design_c": "sovuq davr hisobiy harorati (B parametri)",
    "observed_extreme_c": "kuzatilgan mutlaq minimum",
    "hot_month_mean_c": "issiq oyning o‘rtacha harorati",
    "observed_maximum_c": "kuzatilgan mutlaq maksimum",
}


def _rounded_breakdown_adjustment_kw(result: HeatLossResult) -> Decimal:
    """Make the sum of displayed 0.01 kW rows equal the displayed total."""
    quantum = Decimal("0.01")
    rounded_lines = sum(
        (
            (Decimal(str(line.watts)) / Decimal("1000")).quantize(
                quantum,
                rounding=ROUND_HALF_UP,
            )
            for line in result.lines
        ),
        Decimal("0"),
    )
    rounded_total = (Decimal(str(result.total_w)) / Decimal("1000")).quantize(
        quantum,
        rounding=ROUND_HALF_UP,
    )
    return rounded_total - rounded_lines


def _formula4_pressure_note(building: Building, locale: str) -> str:
    """Describe formula (4) inputs when pressure was calculated by the bot."""
    if building.airflow is None or not building.airflow.infiltration_paths:
        return ""
    paths = building.airflow.infiltration_paths
    first = paths[0].pressure_input
    if first is None:
        return ""
    groups = ", ".join(
        f"h={path.pressure_input.opening_height_m:g}→{path.pressure_pa:.2f} Pa; "
        f"h1={path.first_floor_pressure_input.opening_height_m:g}"
        f"→{path.first_floor_pressure_pa:.2f} Pa"
        for path in paths
        if path.pressure_input is not None and path.first_floor_pressure_input is not None
    )
    prefix = "4-formula" if locale == "uz" else "формула 4"
    return (
        f"; {prefix}: H={first.building_height_m:g} m, "
        f"ti/te={first.indoor_temperature_c:g}/{first.outdoor_temperature_c:g} °C, "
        f"ρe={first.outdoor_air_density_kg_m3:g} kg/m³, v={first.wind_speed_m_s:g} m/s, "
        f"ce.n/ce.p={first.windward_coefficient:g}/{first.leeward_coefficient:g}, "
        f"k1={first.height_factor:g}, pint={first.internal_pressure_pa:g} Pa; {groups}"
    )


def localize_system_text(value: str, locale: str) -> str:
    """Translate calculation-generated names while preserving user-provided names."""
    if normalize_locale(locale) != "uz":
        return value
    if value in UZ_SYSTEM_TEXT:
        return UZ_SYSTEM_TEXT[value]
    for source, target in UZ_SYSTEM_PREFIXES.items():
        if value.startswith(source):
            translated = target + value.removeprefix(source)
            return translated.replace(" шт.)", " dona)")
    return value


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
        if line.kind in {"Поправка", "Линейный мостик"}:
            category = "bridges"
        elif line.kind.startswith("Вентиляция") or line.kind in {
            "Инфильтрация",
            "Естественная вентиляция",
        }:
            category = "airflow"
        elif line.kind == "Проём":
            category = "openings"
        elif line.surface_kind in {
            SurfaceKind.FLOOR,
            SurfaceKind.CEILING,
            SurfaceKind.ROOF,
        }:
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
    passport_statuses = {"passport", "passport_user_input"}
    if any(opening.value_status not in passport_statuses for opening in building.openings):
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
        status = f"{_ru_status(material.value_status)}; {material.table_row}"
    return f"{name} {layer.thickness_m * 100:g} см (λ={conductivity:g} Вт/(м·К); {status})"


def _ru_status(value: str) -> str:
    return RU_VALUE_STATUS.get(value, value)


def _climate_parameter_name(value: str, locale: str) -> str:
    names = (
        UZ_CLIMATE_PARAMETER_NAMES
        if normalize_locale(locale) == "uz"
        else RU_CLIMATE_PARAMETER_NAMES
    )
    return names.get(value, value)


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


def _uz_status(value: str) -> str:
    return {
        "passport": "pasport qiymati",
        "passport_user_input": "foydalanuvchi kiritgan pasport qiymati",
        "typical_reference": "ma’lumotnoma qiymati",
        "reference_unverified": "tasdiqlanmagan ma’lumotnoma qiymati",
    "normative_base_not_design": "me’yoriy bazaviy, hisobiy emas",
    "normative_design_b": "B sharoiti uchun me’yoriy hisobiy qiymat",
    "legacy_reference_unverified": "eskirgan tasdiqlanmagan ma’lumotnoma qiymati",
        "legacy_reference": "eski ma’lumotnoma qiymati",
        "unspecified": "holati ko‘rsatilmagan",
        "user_supplied_unverified": "foydalanuvchi kiritgan, tekshirilmagan",
        "normative": "me’yoriy",
        "user_confirmed": "foydalanuvchi tasdiqlagan",
    }.get(value, value)


def _uz_source_note(value: str) -> str:
    exact = {
        "Паспортный U введён пользователем": "Pasportdagi U foydalanuvchi tomonidan kiritilgan",
        "Не паспорт изделия; для рабочего расчёта ввести паспортный U": (
            "Bu mahsulot pasporti emas; ishchi hisob uchun pasportdagi U ni kiriting"
        ),
        "Старое справочное значение U": "Eski ma’lumotnoma U qiymati",
        "климатические значения введены пользователем и требуют проверки": (
            "Iqlim qiymatlari foydalanuvchi tomonidan kiritilgan va tekshirilishi kerak"
        ),
        "ШНҚ 2.01.01-22; расчётную температуру подтвердить для адреса объекта": (
            "SHNQ 2.01.01-22; hisobiy harorat obyekt manzili uchun tasdiqlanishi kerak"
        ),
        (
            "средние и экстремумы — ШНҚ 2.01.01-22; расчётная температура "
            "параметра Б подтверждена пользователем"
        ): (
            "o‘rtacha va ekstremal qiymatlar — SHNQ 2.01.01-22; B parametrining "
            "hisobiy harorati foydalanuvchi tomonidan tasdiqlangan"
        ),
    }
    if value in exact:
        return exact[value]
    custom_prefix = "климатические значения введены пользователем и требуют проверки; источник: "
    if value.startswith(custom_prefix):
        source = value.removeprefix(custom_prefix)
        if source == "не указан пользователем":
            source = "foydalanuvchi ko‘rsatmagan"
        return (
            "Iqlim qiymatlari foydalanuvchi tomonidan kiritilgan va tekshirilishi kerak; "
            f"manba: {source}"
        )
    design_prefix = (
        "средние и экстремумы — ШНҚ 2.01.01-22; расчётная температура "
        "параметра Б введена пользователем; источник значения: "
    )
    if value.startswith(design_prefix):
        source = value.removeprefix(design_prefix)
        if source == "не указан пользователем":
            source = "foydalanuvchi ko‘rsatmagan"
        return (
            "o‘rtacha va ekstremal qiymatlar — SHNQ 2.01.01-22; B parametrining "
            "hisobiy harorati foydalanuvchi tomonidan kiritilgan; manba: "
            f"{source}"
        )
    return value


def _uz_reference_text(value: str) -> str:
    replacements = (
        ("ШНҚ", "SHNQ"),
        ("ҚМҚ", "QMQ"),
        ("Ташкент", "Toshkent"),
        ("Самарканд", "Samarqand"),
        ("Нукус", "Nukus"),
        ("утверждён", "tasdiqlangan"),
        ("действует с", "amal qiladi"),
        ("приложение", "ilova"),
        ("таблица", "jadval"),
        ("строка", "satr"),
        ("позиция", "pozitsiya"),
        ("колонка", "ustun"),
        ("январь", "yanvar"),
        ("июль", "iyul"),
        ("год", "yil"),
        ("параметр Б холодного периода", "sovuq davr B parametri"),
        ("значение введено пользователем", "qiymat foydalanuvchi tomonidan kiritilgan"),
        (
            "пользовательский источник; редакция не проверена",
            "foydalanuvchi manbasi; tahrir tekshirilmagan",
        ),
        ("не указан пользователем", "foydalanuvchi ko‘rsatmagan"),
        ("определение параметра Б", "B parametrining ta’rifi"),
        ("расчётная температура отопления", "isitishning hisobiy harorati"),
        ("таблица/ряд среднего холодного месяца", "sovuq oy o‘rtachasi jadvali/qatori"),
        ("таблица/ряд среднего жаркого месяца", "issiq oy o‘rtachasi jadvali/qatori"),
        ("абсолютный наблюдавшийся минимум", "kuzatilgan mutlaq minimum"),
        ("абсолютный наблюдавшийся максимум", "kuzatilgan mutlaq maksimum"),
        ("период наблюдений", "kuzatuv davri"),
        ("подтверждается пользователем", "foydalanuvchi tasdiqlaydi"),
        ("в момент расчёта", "hisob vaqtida"),
        (
            "полный период наблюдений в публикации не указан",
            "kuzatuv davri nashrda ko‘rsatilmagan",
        ),
        (
            "нормативная климатическая таблица; период уточнять в первоисточнике",
            "me’yoriy iqlim jadvali; davrni birlamchi manbada aniqlang",
        ),
        ("введено пользователем", "foydalanuvchi kiritgan"),
        ("не указано", "ko‘rsatilmagan"),
        (
            "не подтверждена для обобщённой позиции",
            "umumlashtirilgan pozitsiya uchun tasdiqlanmagan",
        ),
    )
    for source, target in replacements:
        value = value.replace(source, target)
    return value


def _uz_assumption(value: str) -> str:
    exact = {
        (
            "Воздушные потери заданы упрощённой общей кратностью как невосстанавливаемый "
            "поток. Для подбора рекуператора нужен раздельный расход вентиляции и инфильтрации."
        ): (
            "Havo yo‘qotishlari soddalashtirilgan umumiy karralik bilan qayta tiklanmaydigan "
            "oqim sifatida berilgan. Rekuperator tanlash uchun ventilyatsiya va infiltratsiya "
            "sarflari alohida kerak."
        ),
        (
            "Инфильтрация рассчитана как нижняя оценка по формуле 2 приложения 8 "
            "ШНҚ 2.04.05-22: 3 м³/ч на 1 м² жилой площади для некомпенсированной "
            "естественной вытяжки. Норма требует принять большее из формул 1 и 2; "
            "расчёт через воздухопроницаемость и давление нужно проверить отдельно."
        ): (
            "Infiltratsiya ШНҚ 2.04.05-22 8-ilovasining 2-formulasi bo‘yicha quyi baho "
            "sifatida hisoblandi: kompensatsiyalanmagan tabiiy tortish uchun yashash "
            "maydonining har 1 m² iga 3 m³/soat. Me’yor 1- va 2-formulalardan kattasini "
            "olishni talab qiladi; havo o‘tkazuvchanlik va bosim hisobi alohida tekshiriladi."
        ),
        (
            "Непривязанные проёмы распределены между стенами пропорционально свободной "
            "площади; ориентационная добавка для них не определена и принята β=0."
        ): (
            "Muayyan devorga biriktirilmagan ochiqlar bo‘sh maydonga mutanosib taqsimlangan; "
            "ularning yo‘nalish qo‘shimchasi aniqlanmagan va β=0 qabul qilingan."
        ),
        (
            "Для холодного подвала/чердака использована оценка 70% наружной ΔT; "
            "это не заявлено как нормативный коэффициент."
        ): (
            "Sovuq yerto‘la/chordoq uchun tashqi ΔT ning 70% bahosi ishlatilgan; "
            "bu me’yoriy koeffitsiyent deb ko‘rsatilmaydi."
        ),
        (
            "Для упрощённого пола по грунту использована оценка 50% наружной ΔT; "
            "это не нормативный зональный метод."
        ): (
            "Gruntdagi polning soddalashtirilgan hisobi uchun tashqi ΔT ning 50% bahosi "
            "ishlatilgan; bu me’yoriy zonal usul emas."
        ),
        "Для пола на лагах сопротивления зон умножены на 1,18.": (
            "Lagali pol uchun zonalar qarshiligi 1,18 ga ko‘paytirilgan."
        ),
        (
            "Процентная поправка мостиков холода применена ко всей базовой "
            "трансмиссионной нагрузке; это оценка, а не расчёт узлов."
        ): (
            "Issiqlik ko‘priklarining foizli tuzatishi butun bazaviy transmissiya yukiga "
            "qo‘llangan; bu uzellar hisobi emas, bahodir."
        ),
    }
    if value in exact:
        return exact[value]
    manual_climate_prefix = (
        "Расчётная наружная температура введена пользователем; источник значения: "
    )
    if value.startswith(manual_climate_prefix):
        source = value.removeprefix(manual_climate_prefix).removesuffix(
            ". Значение не маркируется как нормативное."
        )
        if source == "не указан пользователем":
            source = "foydalanuvchi ko‘rsatmagan"
        return (
            "Hisobiy tashqi harorat foydalanuvchi tomonidan kiritilgan; qiymat manbasi: "
            f"{source}. Qiymat me’yoriy deb belgilanmaydi."
        )
    if value.startswith("Пол по грунту рассчитан по приложению 9"):
        translated = value.replace(
            "Пол по грунту рассчитан по приложению 9",
            "Gruntdagi pol 9-ilova bo‘yicha hisoblangan",
        )
        translated = translated.replace("полосы шириной", "kengligi")
        translated = translated.replace(
            "угловые участки зоны I учтены дважды",
            "I zona burchak qismlari ikki marta hisobga olingan",
        )
        translated = translated.replace(
            "добавлено сопротивление указанного слоя",
            "ko‘rsatilgan qatlam qarshiligi qo‘shilgan",
        )
        translated = translated.replace("наружные стороны", "tashqi tomonlar")
        translated = translated.replace(
            "для старого расчёта принято, что наружные все четыре стороны",
            "eski hisob uchun to‘rtta tomon ham tashqi deb qabul qilingan",
        )
        translated = translated.replace("Вт/(м·К)", "Vt/(m·K)")
        translated = translated.replace("м²·К/Вт", "m²·K/Vt")
        return translated.replace(" м ", " m ")
    return value


def _uz_layer_description(layer: Layer) -> str:
    material = MATERIALS.get(layer.material_key)
    name = UZ_MATERIAL_NAMES.get(layer.material_key, "pasport bo‘yicha material")
    conductivity = (
        layer.conductivity_w_mk if layer.conductivity_w_mk is not None else material.conductivity
    )
    if material is None or layer.conductivity_w_mk is not None:
        status = "pasport/qo‘lda kiritilgan qiymat"
    else:
        status = f"{_uz_status(material.value_status)}; {_uz_reference_text(material.table_row)}"
    return f"{name} {layer.thickness_m * 100:g} cm (λ={conductivity:g} Vt/(m·K); {status})"


def _uz_surface_description(surface: OpaqueSurface) -> str:
    boundary = UZ_BOUNDARY_NAMES[surface.boundary]
    if surface.adjacent_temperature_c is not None:
        boundary += f", {surface.adjacent_temperature_c:g} °C"
    layers = ", ".join(_uz_layer_description(layer) for layer in surface.layers)
    if not layers:
        layers = "issiqlik oqimi nol deb qabul qilingan"
    orientation = (
        f"; yo‘nalish {UZ_ORIENTATION_NAMES[surface.orientation]}"
        if surface.orientation is not None
        else ""
    )
    return (
        f"• {localize_system_text(surface.name, 'uz')}: {surface.area_m2:g} m² → "
        f"{boundary}; {layers}; β={surface.additional_heat_loss_factor:g}; "
        f"n={surface.position_factor:g}{orientation}"
    )


def _format_report_uz(
    building: Building,
    result: HeatLossResult,
    climate: ClimateProfile | None,
    scenario: str,
    scenario_results: dict[str, HeatLossResult] | None,
) -> str:
    delta_t = building.indoor_temperature_c - building.outdoor_temperature_c
    if building.linear_thermal_bridges:
        bridge_description = "aniq ψ·L kiritish"
    elif building.thermal_bridge_factor:
        bridge_description = (
            f"baho: to‘siqlar, ochiqlar va gruntdagi polning ko‘priklargacha bo‘lgan "
            f"issiqlik yo‘qotishlaridan {building.thermal_bridge_factor * 100:g}%"
        )
    else:
        bridge_description = "kiritilmagan"
    if building.airflow is None:
        airflow_description = (
            f"eski umumiy ACH {building.air_changes_per_hour:g} 1/soat; "
            "komponentlar ajratilmagani uchun oqim qayta tiklanmaydigan deb qabul qilingan"
        )
    else:
        if building.airflow.infiltration_basis == "appendix8_residential_exhaust":
            infiltration_note = (
                "; ШНҚ 8-ilova, 2-formula quyi bahosi "
                f"(yashash maydoni {building.airflow.infiltration_m3_h / 3:g} m²)"
            )
        elif building.airflow.infiltration_basis == "appendix8_envelope":
            mass_flow = appendix8_infiltration_mass_flow(building.airflow.infiltration_paths)
            living_area = building.airflow.infiltration_m3_h / 3
            delta_t = building.indoor_temperature_c - building.outdoor_temperature_c
            formula_one_w = 0.28 * mass_flow * delta_t
            density = 353 / (273 + building.indoor_temperature_c)
            formula_two_w = 0.28 * building.airflow.infiltration_m3_h * density * delta_t
            governing = 1 if formula_one_w >= formula_two_w else 2
            comparison = (
                f"; Q1={formula_one_w:.1f} W, Q2={formula_two_w:.1f} W, "
                f"{governing}-formula qabul qilindi ({living_area:g} m²)"
                if living_area
                else f"; Q1={formula_one_w:.1f} W; 2-formula bilan solishtirilmagan"
            )
            infiltration_note = (
                f"; ШНҚ 8-ilova, 3-formula: {mass_flow:.2f} kg/soat, "
                f"{len(building.airflow.infiltration_paths)} ta bosim guruhi{comparison}"
                f"{_formula4_pressure_note(building, 'uz')}"
            )
        else:
            infiltration_note = ""
        infiltration_label = (
            "2-formula uchun solishtirma sarf"
            if building.airflow.infiltration_basis == "appendix8_envelope"
            else "infiltratsiya"
        )
        airflow_description = (
            f"mexanik {building.airflow.mechanical_m3_h:g} m³/soat; "
            f"tabiiy {building.airflow.natural_m3_h:g} m³/soat; "
            f"{infiltration_label} {building.airflow.infiltration_m3_h:g} m³/soat; "
            f"mexanik qism rekuperatsiyasi "
            f"{building.airflow.heat_recovery_efficiency * 100:g}%{infiltration_note}"
        )
    lines = [
        "🔥 Issiqlik yo‘qotishlari hisobi natijasi",
        "",
        "Boshlang‘ich ma’lumotlar:",
        f"Isitiladigan hajm: {building.volume_m3:g} m³",
        f"Haroratlar: {building.indoor_temperature_c:.1f} °C / "
        f"{building.outdoor_temperature_c:.1f} °C (ΔT {delta_t:.1f} K)",
        f"Havo almashinuvi: {airflow_description}",
        f"Issiqlik ko‘priklari: {bridge_description}",
    ]
    if all(value is not None for value in (building.length_m, building.width_m, building.height_m)):
        lines.insert(
            4,
            f"O‘lchamlar: {building.length_m:g} × {building.width_m:g} × "
            f"{building.height_m:g} m",
        )
    if building.heated_area_m2:
        lines.append(f"Isitiladigan maydon: {building.heated_area_m2:g} m²")
    lines.extend(
        [
            "",
            "Yakun:",
            f"To‘siqlar va ochiqlar: {result.transmission_w / 1000:.2f} kVt",
            f"Havo almashinuvi: {result.ventilation_w / 1000:.2f} kVt",
            f"Hisobiy yuklama: {result.total_kw:.2f} kVt",
            f"Binoning issiqlik yo‘qotish koeffitsiyenti: {result.total_w / delta_t:.0f} Vt/K",
            f"{(building.safety_factor - 1) * 100:.0f}% zaxira bilan tavsiya etilgan quvvat: "
            f"{result.recommended_kw:.2f} kVt",
        ]
    )
    if building.heated_area_m2:
        lines.append(
            f"Solishtirma yuklama: {result.total_w / building.heated_area_m2:.0f} Vt/m² "
            f"(zaxira bilan {result.recommended_w / building.heated_area_m2:.0f} Vt/m²)"
        )
    lines.extend(["", "Konstruksiyalar:"])
    lines.extend(_uz_surface_description(surface) for surface in building.opaque_surfaces)
    for opening in building.openings:
        orientation = (
            f"; yo‘nalish {UZ_ORIENTATION_NAMES[opening.orientation]}"
            if opening.orientation is not None
            else ""
        )
        lines.append(
            f"• {localize_system_text(opening.name, 'uz')}: {opening.area_m2:g} m²; "
            f"U={opening.u_value:g} Vt/(m²·K); {_uz_status(opening.value_status)}; "
            f"{_uz_source_note(opening.source_note)}; "
            f"β={opening.additional_heat_loss_factor:g}; n={opening.position_factor:g}"
            f"{orientation}"
        )
    if building.ground_floor_zones:
        lines.append(
            f"• Gruntdagi pol: {building.heated_area_m2:g} m² geometrik maydon → "
            f"{len(building.ground_floor_zones)} ta me’yoriy zona; "
            "I zona burchak qismlari ikki marta hisobga olingan"
        )
    lines.extend(["", "Tarkibiy taqsimot:"])
    for item in sorted(result.lines, key=lambda row: row.watts, reverse=True):
        details = ""
        if item.area_m2 is not None and item.u_value is not None:
            if item.kind == "Линейный мостик":
                details = f" — {item.area_m2:.1f} m, ψ={item.u_value:.3f} Vt/(m·K)"
            elif item.kind == "Пол по грунту":
                details = (
                    f" — {item.area_m2:.1f} m², R={1 / item.u_value:.2f} m²·K/Vt, "
                    f"ΔT={item.delta_t_k:.1f} K"
                )
            else:
                details = (
                    f" — {item.area_m2:.1f} m², R={1 / item.u_value:.2f} m²·K/Vt, "
                    f"U={item.u_value:.2f} Vt/(m²·K), ΔT={item.delta_t_k:.1f} K"
                )
        lines.append(
            f"• {localize_system_text(item.name, 'uz')}: {item.watts / 1000:.2f} kVt{details}"
        )
    rounding_adjustment = _rounded_breakdown_adjustment_kw(result)
    if rounding_adjustment:
        lines.append(f"• Yaxlitlash tuzatishi: {rounding_adjustment:+.2f} kVt")
    if climate:
        scenario_name = (
            tr(f"survey.scenario.{scenario}", "uz")
            if scenario in {"economy", "design", "extreme", "future"}
            else scenario
        )
        city = tr(f"climate.{climate.key}", "uz") if climate.key in CLIMATES else climate.name
        lines.extend(
            [
                "",
                f"Iqlim: {city}, «{scenario_name}» ssenariysi. "
                f"{_uz_source_note(climate.source_note)}.",
                f"Iqlim manbasi: {climate.source_url or 'foydalanuvchi kiritgan'}; "
                f"versiya {_uz_reference_text(climate.version)}; "
                f"davr: {_uz_reference_text(climate.data_period)}; "
                f"yangilangan {climate.updated_at}.",
                f"Yozgi ma’lumot: issiq oyning o‘rtachasi {climate.hot_month_mean_c:g} °C; "
                f"mutlaq maksimum {climate.observed_maximum_c:g} °C. Isitish yukiga kirmaydi.",
            ]
        )
        if climate.provenance:
            lines.append("Iqlim qiymatlarining kelib chiqishi:")
            lines.extend(
                f"• {_climate_parameter_name(item.parameter, 'uz')}={item.value:g} {item.unit}: "
                f"{_uz_reference_text(item.document)}, "
                f"{_uz_reference_text(item.location)}; holat {_uz_status(item.status)}."
                for item in climate.provenance
            )
    if climate and scenario_results:
        lines.extend(["", "Iqlim ssenariylari bo‘yicha quvvat (zaxira bilan):"])
        for key in ("economy", "design", "future", "extreme"):
            temperature = climate.outdoor_temperature(key)
            load = scenario_results[key].recommended_kw
            lines.append(
                f"• {tr(f'survey.scenario.{key}', 'uz')} ({temperature:g} °C): {load:.2f} kVt"
            )
        lines.append("Tarixiy ekstremum — stress-test, qozonni avtomatik tanlash emas.")
    if building.assumptions:
        lines.extend(["", "Qabul qilingan farazlar:"])
        lines.extend(
            f"• {_uz_reference_text(_uz_assumption(item))}" for item in building.assumptions
        )
    lines.extend(
        [
            "",
            f"Versiyalar: hisob dvigateli {ENGINE_VERSION}; katalog {CATALOG_VERSION}.",
            "Sirt qarshiliklari (ISO 6946:2017, 7-jadval): devor uchun Rsi=0,13; "
            "pastga oqim uchun 0,17; yuqoriga oqim uchun 0,10; tashqi havo uchun "
            "Rse=0,04 m²·K/Vt.",
            "Me’yoriy koeffitsiyentlar: tuzilmaviy yo‘nalish bo‘lmasa β=0; to‘siqning "
            "joylashuv koeffitsiyenti n=1,0. Bu qiymatlar har bir konstruksiya uchun "
            "ko‘rsatiladi va uning nomidan kelib chiqib tanlanmaydi.",
            "Muhim: hisobiy issiqlik yuklamasi va ekspluatatsion zaxirali tavsiya etilgan "
            "quvvat alohida ko‘rsatilgan. Issiq suv kiritilmagan. Oylik energiya sarfi "
            "hisoblanmaydi. Natija avtomatik ravishda loyiha hujjati hisoblanmaydi. Montajdan "
            "oldin muhandis issiqlik ko‘priklari, haqiqiy havo almashinuvi, pasportdagi λ/U "
            "va mahalliy me’yorlarni tekshirishi kerak.",
        ]
    )
    return "\n".join(lines)


def format_report(
    building: Building,
    result: HeatLossResult,
    climate: ClimateProfile | None = None,
    scenario: str = "design",
    scenario_results: dict[str, HeatLossResult] | None = None,
    locale: str = "ru",
) -> str:
    locale = normalize_locale(locale)
    if locale == "uz":
        return _format_report_uz(building, result, climate, scenario, scenario_results)
    delta_t = building.indoor_temperature_c - building.outdoor_temperature_c
    if building.linear_thermal_bridges:
        bridge_description = "точный ввод ψ·L"
    elif building.thermal_bridge_factor:
        bridge_description = (
            f"оценка {building.thermal_bridge_factor * 100:g}% от потерь через ограждения, "
            "проёмы и пол по грунту до мостиков"
        )
    else:
        bridge_description = "не заданы"
    if building.airflow is None:
        airflow_description = (
            f"старый общий ACH {building.air_changes_per_hour:g} 1/ч; поток принят "
            "невосстанавливаемым, поскольку компоненты не были разделены"
        )
    else:
        if building.airflow.infiltration_basis == "appendix8_residential_exhaust":
            infiltration_note = (
                "; нижняя оценка по формуле 2 приложения 8 ШНҚ "
                f"(жилая площадь {building.airflow.infiltration_m3_h / 3:g} м²)"
            )
        elif building.airflow.infiltration_basis == "appendix8_envelope":
            mass_flow = appendix8_infiltration_mass_flow(building.airflow.infiltration_paths)
            living_area = building.airflow.infiltration_m3_h / 3
            delta_t = building.indoor_temperature_c - building.outdoor_temperature_c
            formula_one_w = 0.28 * mass_flow * delta_t
            density = 353 / (273 + building.indoor_temperature_c)
            formula_two_w = 0.28 * building.airflow.infiltration_m3_h * density * delta_t
            governing = 1 if formula_one_w >= formula_two_w else 2
            comparison = (
                f"; Q1={formula_one_w:.1f} Вт, Q2={formula_two_w:.1f} Вт, "
                f"принята формула {governing} ({living_area:g} м²)"
                if living_area
                else f"; Q1={formula_one_w:.1f} Вт; без сравнения с формулой 2"
            )
            infiltration_note = (
                f"; формула 3 приложения 8 ШНҚ: {mass_flow:.2f} кг/ч, "
                f"групп давления {len(building.airflow.infiltration_paths)}{comparison}"
                f"{_formula4_pressure_note(building, 'ru')}"
            )
        else:
            infiltration_note = ""
        infiltration_label = (
            "сравнительный расход формулы 2"
            if building.airflow.infiltration_basis == "appendix8_envelope"
            else "инфильтрация"
        )
        airflow_description = (
            f"механическая {building.airflow.mechanical_m3_h:g} м³/ч; "
            f"естественная {building.airflow.natural_m3_h:g} м³/ч; "
            f"{infiltration_label} {building.airflow.infiltration_m3_h:g} м³/ч; "
            f"рекуперация механической части "
            f"{building.airflow.heat_recovery_efficiency * 100:g}%{infiltration_note}"
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
            f"{_ru_status(opening.value_status)}; {opening.source_note}; "
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
    rounding_adjustment = _rounded_breakdown_adjustment_kw(result)
    if rounding_adjustment:
        lines.append(f"• Корректировка округления: {rounding_adjustment:+.2f} кВт")
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
                f"• {_climate_parameter_name(item.parameter, 'ru')}={item.value:g} "
                f"{item.unit}: {item.document}, "
                f"{item.location}; статус {_ru_status(item.status)}."
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
            "Поверхностные сопротивления (ISO 6946:2017, таблица 7): Rsi=0,13 для "
            "стены, 0,17 для потока вниз, 0,10 для потока вверх; Rse=0,04 м²·К/Вт "
            "для наружного воздуха.",
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
