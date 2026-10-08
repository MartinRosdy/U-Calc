"""Small, strict RU/UZ-Latin translation catalog.

Keeping keys in one module makes missing translations a startup/test failure instead
of silently leaking Russian strings into the Uzbek interface.
"""

from collections.abc import Mapping

SUPPORTED_LOCALES = ("ru", "uz")
DEFAULT_LOCALE = "ru"

RU: dict[str, str] = {
    "language.name": "Русский",
    "menu.title": "🏠 U-Calc — расчёт теплопотерь",
    "menu.subtitle": "Выберите действие:",
    "menu.new": "➕ Новый расчёт",
    "menu.history": "📁 Мои объекты/расчёты",
    "menu.profiles": "⚙️ Профили расчёта",
    "menu.language": "🌐 Язык",
    "menu.help": "ℹ️ Помощь и методика",
    "menu.home": "🏠 В меню",
    "language.title": "Выберите язык интерфейса:",
    "language.saved": "Язык сохранён.",
    "profiles.title": "⚙️ Профили расчёта",
    "profiles.empty": "Профилей пока нет. Создайте первый профиль.",
    "profiles.create": "➕ Создать профиль",
    "profiles.prepared_by": "🖊 Автор PDF-отчёта",
    "profiles.prepared_by_ask": (
        "Введите имя мастера или организации для PDF (до 120 символов). "
        "Отправьте «-», чтобы очистить поле:"
    ),
    "profiles.prepared_by_saved": "Автор PDF сохранён: {name}.",
    "profiles.prepared_by_cleared": "Поле автора PDF очищено.",
    "profiles.rename": "✏️ Переименовать",
    "profiles.settings": "🎛 Изменить параметры",
    "profiles.ask_indoor": "Желаемая температура внутри, °C (от -30 до +50):",
    "profiles.ask_air": "Выберите расчётный воздухообмен:",
    "profiles.ask_safety": "Выберите эксплуатационный запас:",
    "profiles.settings_saved": "Параметры профиля сохранены.",
    "profiles.summary": (
        "Внутри: {indoor} °C · воздухообмен: {air_changes} 1/ч · запас: {safety}%"
    ),
    "profiles.copy": "📋 Дублировать",
    "profiles.default": "⭐ По умолчанию",
    "profiles.delete": "🗑 Удалить",
    "profiles.ask_name": "Введите название профиля (1–60 символов):",
    "profiles.ask_copy_name": "Введите название копии (1–60 символов):",
    "profiles.created": "Профиль «{name}» создан.",
    "profiles.renamed": "Профиль переименован.",
    "profiles.copied": "Копия «{name}» создана.",
    "profiles.default_saved": "Профиль назначен по умолчанию.",
    "profiles.delete_confirm": "Удалить профиль «{name}»? Старые расчёты сохранятся.",
    "profiles.deleted": "Профиль удалён.",
    "profiles.not_found": "Профиль не найден.",
    "common.back": "⬅️ Назад",
    "common.cancel": "✖️ Отменить",
    "common.confirm_delete": "Да, удалить",
    "common.yes": "Да",
    "common.no": "Нет",
    "common.error": "⚠️ {message}",
    "common.retry": "⚠️ {message}. Попробуйте ещё раз.",
    "common.invalid_input": "Проверьте введённое значение",
    "common.invalid_option": "Неизвестный или устаревший вариант",
    "common.internal": "Внутренняя ошибка",
    "common.unhandled": (
        "Не удалось обработать этот шаг. Данные расчёта могли сохраниться не полностью. "
        "Попробуйте ещё раз или начните заново командой /new."
    ),
    "common.stale": "Эта кнопка устарела. Откройте актуальный экран через /menu или /resume.",
    "safety.access_denied": "Доступ к U-Calc ограничен владельцем бота.",
    "safety.message_too_long": "Сообщение слишком длинное. Максимум {limit} символов.",
    "safety.rate_limited": "Слишком много действий. Подождите минуту и продолжите.",
    "safety.calculation_rate_limited": (
        "Слишком много расчётов. Подождите минуту перед повторным запуском."
    ),
    "survey.draft_missing": "Сохранённого черновика нет. Начать новый: /new",
    "survey.draft_restored": "Черновик восстановлен. Продолжаем с сохранённого шага:",
    "survey.draft_deleted": "Черновик удалён.",
    "survey.cancelled": "Расчёт отменён. Чтобы начать заново: /new",
    "survey.back_restored": "⬅️ Вернулись к предыдущему шагу:",
    "survey.back_missing": "Предыдущего шага нет. Начать расчёт: /new",
    "survey.back_missing_alert": "Предыдущего шага нет",
    "survey.start": (
        "🏠 U-Calc рассчитает пиковые теплопотери и покажет, куда уходит тепло.\n\n"
        "Выберите уровень детализации:{profile_note}"
    ),
    "survey.profile_applied": "\n\n⭐ Применён профиль «{name}».",
    "survey.mode.quick": "Быстрый расчёт",
    "survey.mode.advanced": "Расширенный расчёт",
    "survey.object.question": "Шаг 1/9 — объект. Что рассчитываем?",
    "survey.object.apartment": "Квартиру",
    "survey.object.house": "Частный дом",
    "survey.position.question": (
        "Где расположена квартира? Перекрытия с отапливаемыми соседями "
        "будут автоматически исключены."
    ),
    "survey.position.middle": "Средний этаж",
    "survey.position.first": "Первый этаж",
    "survey.position.last": "Последний этаж",
    "survey.position.first_last": "Первый и последний",
    "survey.object_name": ("Название объекта для истории и версий, например «Дом Юнусабад»: "),
    "survey.climate.question": "Шаг 2/9 — климат. Выберите профиль:",
    "survey.climate.custom": "Другой город (полный профиль)",
    "survey.climate.manual": "Только температура вручную",
    "survey.climate.manual_name": "Температура задана вручную",
    "climate.tashkent": "Ташкент",
    "climate.samarkand": "Самарканд",
    "climate.nukus": "Нукус",
    "survey.outdoor_manual": ("Введите расчётную наружную температуру зимой, °C (например -18):"),
    "survey.city_name": "Название города или населённого пункта:",
    "survey.custom.cold_mean": "Средняя температура самого холодного месяца, °C:",
    "survey.custom.design": "Расчётная зимняя температура для отопления, °C:",
    "survey.custom.extreme": "Абсолютный наблюдавшийся минимум, °C:",
    "survey.custom.hot_mean": "Средняя температура самого жаркого месяца, °C:",
    "survey.custom.hot_max": "Абсолютный наблюдавшийся максимум, °C:",
    "survey.profile_design": (
        "Для {city} среднемесячные и экстремальные температуры подтверждены "
        "таблицей 1 ШНҚ 2.01.01-22, но расчётный мороз требует подтверждения.\n\n"
        "Введите температуру параметра Б, °C — наиболее холодной пятидневки "
        "обеспеченностью 0,92:"
    ),
    "survey.scenario.question": (
        "Шаг 2/9 — климат. {city}: выберите режим расчёта.\n"
        "Средний холодный месяц {cold} °C; расчётный мороз {design} °C; "
        "наблюдавшийся экстремум {extreme} °C.\n"
        "Для справки о лете: средний жаркий месяц {hot} °C, абсолютный максимум "
        "{maximum} °C. Летние значения в нагрузку отопления не входят.\n"
        "Климатический резерв — стресс-сценарий на 2 °C холоднее расчётного, "
        "а не прогноз конкретной погоды."
    ),
    "survey.scenario.economy": "Обычная зима",
    "survey.scenario.design": "Расчётный мороз",
    "survey.scenario.extreme": "Экстремум",
    "survey.scenario.future": "Климатический резерв",
    "survey.indoor": (
        "Шаг 3/9 — температура. Снаружи {outdoor} °C. "
        "Какая температура нужна внутри, °C? Например 24"
    ),
    "survey.from_profile_temperature": "Из профиля: {temperature} °C",
    "survey.dimensions": "Шаг 4/9 — геометрия. Введите длину, ширину и высоту, м: 10 8 3",
    "survey.wall_method.question": ("Шаг 4/9 — стены. Как задать только наружные холодные стены?"),
    "survey.wall_method.area": "Общей площадью",
    "survey.wall_method.dimensions": "Размер каждой стены",
    "survey.wall_method.perimeter": "Весь периметр",
    "survey.wall_method.editor": "Разные конструкции — пошагово",
    "survey.wall_method.import": "Экспертный импорт строками |",
    "survey.wall.area": "Введите общую площадь наружных стен до вычета окон и дверей, м²:",
    "survey.wall.dimensions": "Введите ширину×высоту каждой стены: 5x3, 4x3",
    "survey.wall.material": "Шаг 4/9 — стены. Основной материал наружных стен:",
    "survey.wall.material_custom": "Другой материал — паспортная λ",
    "survey.wall.custom_lambda": "Паспортная теплопроводность материала λ, Вт/(м·К):",
    "survey.wall.thickness": "Толщина слоя «{material}» в сантиметрах, например 25:",
    "survey.wall.custom_thickness": "Толщина этого материала в сантиметрах:",
    "survey.wall.insulated": "Стена утеплена?",
    "survey.wall.insulation": "Какой утеплитель?",
    "survey.wall.insulation_custom": "Другой утеплитель — паспортная λ",
    "survey.wall.insulation_lambda": ("Паспортная теплопроводность утеплителя λ, Вт/(м·К):"),
    "survey.wall.insulation_thickness": ("Толщина «{material}» в сантиметрах, например 5:"),
    "survey.wall.custom_insulation_thickness": "Толщина этого утеплителя в сантиметрах:",
    "survey.window.count": "Шаг 5/9 — проёмы. Сколько наружных окон? Если окон нет — 0:",
    "survey.door.count": "Шаг 5/9 — проёмы. Сколько наружных дверей? Если дверей нет — 0:",
    "survey.opening.area_method": "Суммарной площадью",
    "survey.opening.dimensions_method": "Размером одного элемента",
    "survey.opening.editor_method": "Разные группы и U — пошагово",
    "survey.opening.import_method": "Экспертный импорт строками |",
    "survey.window.method": "Как задать окна?",
    "survey.window.area": "Суммарная площадь всех наружных окон, м²:",
    "survey.window.dimensions": (
        "Ширина × высота одного типового окна в метрах, например 1,4x1,5:"
    ),
    "survey.window.type": "Тип окон:",
    "survey.door.method": "Как задать наружные двери?",
    "survey.door.area": "Суммарная площадь наружных дверей, м²:",
    "survey.door.dimensions": ("Ширина × высота одной типовой двери в метрах, например 0,9x2,1:"),
    "survey.door.type": "Тип двери (справочное U; паспортное значение задаётся через группы):",
    "window.single": "Одинарное стекло",
    "window.double_old": "Старое двойное окно",
    "window.double": "2-стекольный стеклопакет",
    "window.triple": "3-стекольный стеклопакет",
    "window.efficient": "Энергоэффективное окно",
    "door.wood_old": "Старая деревянная дверь",
    "door.metal_basic": "Металлическая без терморазрыва",
    "door.insulated": "Утеплённая наружная дверь",
    "door.efficient": "Энергоэффективная дверь",
    "opening.windows": "окон",
    "opening.doors": "дверей",
    "opening.editor.name": (
        "Название группы {kind}, например «ПВХ север». Всего указано: {expected}."
    ),
    "opening.editor.count": "Количество одинаковых проёмов в этой группе:",
    "opening.editor.dimensions": "Ширина × высота одного проёма, м, например 1,4×1,5:",
    "opening.editor.u_value": "Паспортный U проёма, Вт/(м²·К), например 1,1:",
    "opening.editor.wall": "К какой стене относится группа?",
    "opening.editor.no_wall": "Без привязки",
    "opening.editor.saved": "Сохранённые группы {kind} — {used}/{expected}:\n{summary}",
    "opening.editor.summary": "• {name}: {count} шт., {area} м², U={u_value}",
    "opening.editor.add": "➕ Добавить группу",
    "opening.editor.edit": "✏️ Изменить: {name}",
    "opening.editor.delete_named": "🗑 Удалить: {name}",
    "opening.editor.delete": "🗑 Удалить последнюю",
    "opening.editor.finish": "✅ Готово",
    "opening.editor.name_resume": "Название группы {kind}. Всего указано: {expected}.",
    "opening.editor.retry": "⚠️ {message}. Попробуйте ещё раз.",
    "opening.editor.error.name_length": "Название должно содержать от 1 до 60 символов",
    "opening.editor.error.duplicate": "Название группы «{name}» уже использовано",
    "opening.editor.error.integer": "Введите целое количество",
    "opening.editor.error.count_range": "Можно добавить от 1 до {remaining} {kind}",
    "opening.editor.error.dimensions": "Укажите одну пару размеров, например 1,4×1,5",
    "opening.editor.error.u_value": "U должен быть от 0,1 до 8 Вт/(м²·К)",
    "opening.editor.error.stale_wall": "Стена больше недоступна",
    "opening.editor.error.total_area": "Суммарная площадь проёмов больше площади стен",
    "opening.editor.error.wall_area": "Проёмы на стене «{wall}» больше её площади",
    "opening.editor.error.distributed": "Все указанные проёмы уже распределены",
    "opening.editor.error.empty": "Список уже пуст",
    "opening.editor.error.incomplete": (
        "Распределено {used} из {expected}. Добавьте оставшиеся проёмы."
    ),
    "opening.editor.error.unknown_action": "Неизвестное действие",
    "opening.editor.error.stale_group": "Группа больше недоступна",
    "survey.boundary.floor": "Шаг 6/9 — пол и потолок. Что находится под полом?",
    "survey.boundary.ceiling": "Шаг 6/9 — пол и потолок. Что находится над потолком?",
    "survey.boundary.heated_neighbor": "Отапливаемый сосед",
    "survey.boundary.unheated_basement": "Холодный подвал",
    "survey.boundary.ground": "Грунт",
    "survey.boundary.outdoor": "Наружный воздух",
    "survey.boundary.unheated_attic": "Холодный чердак",
    "survey.boundary.roof": "Наружный воздух / кровля",
    "survey.adjacent.question": (
        "Температура {zone} известна? Точное значение лучше фиксированного коэффициента."
    ),
    "survey.adjacent.basement": "подвала/грунта под полом",
    "survey.adjacent.attic": "холодного чердака",
    "survey.adjacent.manual": "Ввести температуру",
    "survey.adjacent.estimate": "Оставить оценку {estimate}",
    "survey.adjacent.ground_estimate": "50% наружной ΔT",
    "survey.adjacent.unheated_estimate": "70% наружной ΔT",
    "survey.adjacent.zonal": "Нормативные зоны ШНҚ",
    "survey.adjacent.temperature": (
        "Расчётная температура смежной зоны, °C. Например, для подвала +5:"
    ),
    "survey.neighbor.below": "соседа снизу",
    "survey.neighbor.above": "соседа сверху",
    "survey.neighbor.question": "Температура {zone} такая же, как внутри объекта?",
    "survey.neighbor.same": "Такая же — потерь нет",
    "survey.neighbor.manual": "Ввести температуру соседа",
    "survey.ground.insulation": (
        "Есть утепляющий слой пола с λ < 1,2 Вт/(м·К)? "
        "Основная бетонная плита в нормативный R зоны отдельно не добавляется."
    ),
    "survey.ground.sides": (
        "Какие стороны прямоугольного пола граничат с наружными стенами? "
        "Север/юг — стороны длиной L, восток/запад — стороны шириной W."
    ),
    "survey.ground.sides.all": "Все 4 стороны",
    "survey.ground.sides.n": "Север (L)",
    "survey.ground.sides.e": "Восток (W)",
    "survey.ground.sides.s": "Юг (L)",
    "survey.ground.sides.w": "Запад (W)",
    "survey.ground.sides.ns": "Север + юг",
    "survey.ground.sides.ew": "Восток + запад",
    "survey.ground.sides.ne": "Север + восток",
    "survey.ground.sides.es": "Восток + юг",
    "survey.ground.sides.sw": "Юг + запад",
    "survey.ground.sides.wn": "Запад + север",
    "survey.ground.sides.no_n": "Без севера",
    "survey.ground.sides.no_e": "Без востока",
    "survey.ground.sides.no_s": "Без юга",
    "survey.ground.sides.no_w": "Без запада",
    "survey.ground.sides.complex": "Сложный план",
    "survey.ground.complex_help": (
        "Этот метод пока не аппроксимирует сложный контур: результат был бы ненадёжным. "
        "Разбейте план на прямоугольники и выполните отдельные расчёты."
    ),
    "survey.ground.construction": "Конструкция пола по грунту:",
    "survey.ground.solid": "Сплошной пол",
    "survey.ground.joists": "Пол на лагах",
    "survey.surface.floor": "пола",
    "survey.surface.ceiling": "перекрытия/крыши",
    "survey.surface.material": "Основной материал {surface}:",
    "survey.surface.insulated": "Есть утепление?",
    "survey.surface.insulation": "Материал утепления:",
    "survey.air.quick": (
        "Шаг 7/9 — вентиляция. Оцените воздухообмен: герметичное здание — 0,3; "
        "обычное — 0,5; старое/продуваемое — 0,8–1,0. В быстром режиме это "
        "единый невосстанавливаемый поток; рекуперация из него не вычитается."
    ),
    "survey.air.from_profile": "⭐ Из профиля: {value}",
    "survey.air.advanced": "Шаг 7/9 — вентиляция. Как вводить отдельные расчётные потоки?",
    "survey.air.unit.m3h": "Расходы, м³/ч",
    "survey.air.unit.ach": "Кратности, 1/ч",
    "survey.air.units.m3h": "м³/ч",
    "survey.air.units.ach": "1/ч",
    "survey.air.mechanical": (
        "Расход организованной механической вентиляции, {unit}. Если её нет — 0:"
    ),
    "survey.air.natural": "Расход естественной организованной вентиляции, {unit}. Нет — 0:",
    "survey.air.infiltration": "Расчётная инфильтрация через неплотности, {unit}. Нет — 0:",
    "survey.air.recovery": "Есть рекуперация механической вентиляции?",
    "survey.air.recovery_efficiency": "Паспортный КПД рекуператора, %. Например 70:",
    "survey.air.error.invalid": "Некорректный воздухообмен",
    "survey.air.error.option": "Неизвестный вариант воздухообмена",
    "survey.air.error.units_required": "Выберите единицы раздельных потоков",
    "survey.air.error.units": "Неизвестные единицы расхода",
    "survey.air.error.advanced_only": "Раздельный ввод доступен в расширенном режиме",
    "survey.air.error.recovery": "Неизвестный вариант",
    "survey.recovery.quick": (
        "Есть рекуператор? В быстром режиме он фиксируется справочно, но не уменьшает "
        "общую оценку: для этого нужны раздельные потоки расширенного режима."
    ),
    "survey.recovery.quick_note": (
        "Рекуператор не вычтен из общей оценки. Повторите расчёт в расширенном "
        "режиме, чтобы задать механическую вентиляцию отдельно."
    ),
    "survey.bridges.question": ("Шаг 8/9 — мостики холода (стыки, углы, перемычки, балконы):"),
    "survey.bridges.zero": "0% — рассчитаны отдельно",
    "survey.bridges.good": "5% — хорошее исполнение",
    "survey.bridges.normal": "10% — обычное",
    "survey.bridges.weak": "15% — много слабых узлов",
    "survey.bridges.exact": "Точно: пошагово ψ × длина",
    "survey.bridges.import": "Экспертный импорт строками |",
    "bridge.editor.name": "Название мостика холода, например «Балконная плита»:",
    "bridge.editor.length": "Суммарная длина этого мостика, м:",
    "bridge.editor.psi": "Линейный коэффициент ψ, Вт/(м·К), например 0,35:",
    "bridge.editor.saved": "Сохранённые мостики ({count}/30):\n{summary}",
    "bridge.editor.summary": "• {name}: {length} м × ψ={psi}",
    "bridge.editor.add": "➕ Добавить мостик",
    "bridge.editor.edit": "✏️ Изменить: {name}",
    "bridge.editor.delete_named": "🗑 Удалить: {name}",
    "bridge.editor.delete": "🗑 Удалить последний",
    "bridge.editor.finish": "✅ Готово",
    "bridge.editor.retry": "⚠️ {message}. Попробуйте ещё раз.",
    "bridge.editor.error.name": "Название должно содержать от 1 до 60 символов",
    "bridge.editor.error.length": "Длина должна быть от 0,01 до 10 000 м",
    "bridge.editor.error.psi": "ψ должен быть от 0 до 5 Вт/(м·К)",
    "bridge.editor.error.limit": "Можно задать не более 30 мостиков холода",
    "bridge.editor.error.limit_alert": "Достигнут лимит 30 мостиков",
    "bridge.editor.error.empty": "Список мостиков уже пуст",
    "bridge.editor.error.required": "Добавьте хотя бы один мостик",
    "bridge.editor.error.action": "Неизвестное действие",
    "bridge.editor.error.stale": "Мостик больше недоступен",
    "survey.safety.question": "Шаг 9/9 — эксплуатационный запас после всех рассчитанных потерь:",
    "survey.safety.normal": "10% — обычно",
    "survey.safety.from_profile": "⭐ Из профиля: {value}%",
    "survey.confirm.title": "✅ Проверьте исходные данные перед расчётом",
    "survey.confirm.body": (
        "{title}\n\nОбъект: {building}\nКлимат: {climate}, наружная {outdoor} °C\n"
        "Внутри: {indoor} °C\nГабариты: {length} × {width} × {height} м\n"
        "Стены брутто: {walls} м²; проёмы: {openings} м²\n"
        "Воздухообмен: {airflow}\nЗапас: {safety}%\n\n"
        "Если всё верно, нажмите «Рассчитать»."
    ),
    "survey.confirm.airflow_simple": "{value} 1/ч (упрощённо)",
    "survey.confirm.airflow_total": "{value} м³/ч суммарно",
    "survey.confirm.calculate": "Рассчитать",
    "survey.confirm.climate": "Изменить климат",
    "survey.confirm.walls": "Изменить стены",
    "survey.confirm.openings": "Изменить проёмы",
    "survey.confirm.boundaries": "Изменить пол/потолок",
    "survey.confirm.airflow": "Изменить вентиляцию",
    "survey.confirm.error.action": "Неизвестное действие",
    "summary.ready": "🔥 Расчёт готов: {name}",
    "summary.load": "Расчётная нагрузка: {value} кВт",
    "summary.range": "Рекомендуемый диапазон: {minimum}–{maximum} кВт",
    "summary.reserve": "Принятый запас: {value}%",
    "summary.temperature": "Расчётная температура: {value} °C ({scenario}, {city})",
    "summary.temperature_manual": "Расчётная температура: {value} °C (ручной ввод)",
    "summary.destinations": "Куда уходит тепло:",
    "summary.category.walls": "стены",
    "summary.category.openings": "окна и двери",
    "summary.category.boundaries": "пол и верх",
    "summary.category.airflow": "вентиляция и инфильтрация",
    "summary.category.bridges": "мостики холода",
    "summary.category.line": "• {name} — {value} кВт ({percent}%)",
    "summary.warning.title": "⚠️ Нужно уточнить:",
    "summary.warning.manual_climate": "климат введён вручную",
    "summary.warning.openings": "U части проёмов — справочное, проверьте паспорт",
    "summary.warning.materials": "λ части материалов — справочная",
    "summary.warning.assumptions": "в расчёте есть инженерные допущения — проверьте PDF",
    "summary.footer": "ГВС и годовое потребление энергии не входят. Полный протокол — в PDF.",
    "summary.untitled": "Без названия",
    "result.saved": "Расчёт №{id}",
    "result.unsaved": "⚠️ Расчёт выполнен, но не сохранён в истории.",
    "result.invalid": (
        "⚠️ Не удалось завершить расчёт: {message}. "
        "Запустите /new и проверьте исходные данные."
    ),
    "result.internal": (
        "Не удалось завершить расчёт из-за внутренней ошибки. "
        "Данные не сохранены; попробуйте /new или сообщите администратору."
    ),
    "result.pdf_caption": "PDF-отчёт U-Calc",
    "result.pdf_failed": "Текстовый расчёт готов, но PDF создать не удалось. Данные сохранены.",
    "result.new": "Новый расчёт: /new",
    "material.brick_solid": "Кирпич полнотелый",
    "material.brick_hollow": "Кирпич пустотелый",
    "material.aerated_d500": "Газоблок D500",
    "material.concrete": "Железобетон",
    "material.wood": "Древесина поперёк волокон",
    "material.mineral_wool": "Минераловатный мат",
    "material.eps": "Пенополистирол EPS",
    "material.xps": "Экструдированный пенополистирол XPS",
    "material.pu_foam": "Пенополиуретан",
    "wall.editor.name": "Название стены или группы, например «Северная стена» (до 60 символов):",
    "wall.editor.area": "Площадь стены, м², либо ширина×высота, например 18 или 6×3:",
    "wall.editor.orientation": (
        "Ориентация наружной стены. Она задаёт нормативную добавку β по "
        "приложению 9 ШНҚ 2.04.05-22:"
    ),
    "wall.editor.orientation.unknown": "Неизвестна — β=0",
    "wall.editor.orientation.north": "Север — β=10%",
    "wall.editor.orientation.north_east": "Северо-восток — β=10%",
    "wall.editor.orientation.east": "Восток — β=10%",
    "wall.editor.orientation.south_east": "Юго-восток — β=5%",
    "wall.editor.orientation.south": "Юг — β=0",
    "wall.editor.orientation.south_west": "Юго-запад — β=0",
    "wall.editor.orientation.west": "Запад — β=5%",
    "wall.editor.orientation.north_west": "Северо-запад — β=10%",
    "wall.editor.material": "Основной материал стены:",
    "wall.editor.passport": "Паспортная λ",
    "wall.editor.lambda": "Паспортная λ материала, Вт/(м·К):",
    "wall.editor.thickness": "Толщина «{material}», см:",
    "wall.editor.base_thickness": "Толщина основного материала, см:",
    "wall.editor.insulated": "У этой стены есть утеплитель?",
    "wall.editor.insulation": "Материал утеплителя:",
    "wall.editor.insulation_lambda": "Паспортная λ утеплителя, Вт/(м·К):",
    "wall.editor.insulation_thickness": "Толщина утеплителя, см:",
    "wall.editor.layers": "Слоёв в конструкции: {count}. Добавить ещё один?",
    "wall.editor.add_layer": "➕ Добавить слой",
    "wall.editor.finish_layers": "✅ Конструкция готова",
    "wall.editor.next_layer": "Материал следующего слоя:",
    "wall.editor.saved": "Сохранённые стены ({count}/12):\n{summary}",
    "wall.editor.summary": "• {name}: {area} м²; {orientation}",
    "wall.editor.add_wall": "➕ Добавить стену",
    "wall.editor.edit_wall": "✏️ Изменить: {name}",
    "wall.editor.delete_named_wall": "🗑 Удалить: {name}",
    "wall.editor.delete_wall": "🗑 Удалить последнюю",
    "wall.editor.finish": "✅ Готово",
    "wall.editor.resume_layers": "Добавьте следующий слой или завершите конструкцию кнопкой.",
    "wall.editor.retry": "⚠️ {message}. Попробуйте ещё раз.",
    "wall.editor.error.name": "Название должно содержать от 1 до 60 символов",
    "wall.editor.error.duplicate": "Название стены «{name}» уже использовано",
    "wall.editor.error.area": "Введите площадь 0,1–100 000 м² или одну пару размеров",
    "wall.editor.error.orientation": "Неизвестная ориентация стены",
    "wall.editor.error.lambda": "λ должна быть от 0,005 до 5 Вт/(м·К)",
    "wall.editor.error.thickness": "Толщина должна быть от 0,1 до 200 см",
    "wall.editor.error.layer_limit": "Конструкция может содержать не более 10 слоёв",
    "wall.editor.error.layer_limit_alert": "Достигнут лимит 10 слоёв",
    "wall.editor.error.wall_limit": "Можно задать не более 12 групп стен",
    "wall.editor.error.wall_limit_alert": "Достигнут лимит 12 стен",
    "wall.editor.error.empty": "Список стен уже пуст",
    "wall.editor.error.required": "Добавьте хотя бы одну стену",
    "wall.editor.error.material": "Неизвестный материал",
    "wall.editor.error.insulation": "Неизвестный утеплитель",
    "wall.editor.error.option": "Неизвестный вариант",
    "wall.editor.error.action": "Неизвестное действие",
    "wall.editor.error.stale": "Стена больше недоступна",
    "pdf.title": "Расчёт пиковой тепловой нагрузки",
    "pdf.object": "Объект",
    "pdf.unnamed": "Без названия",
    "pdf.date": "Дата (Asia/Tashkent)",
    "pdf.prepared_by": "Расчёт подготовлен",
    "pdf.language": "Язык",
    "pdf.calculation_id": "Calculation ID",
    "pdf.versions": "Версии",
    "pdf.versions_value": "движок {engine}; каталог {catalog}; нормы {norms}",
    "pdf.result": "Результат",
    "pdf.transmission": "Ограждения, проёмы и мостики",
    "pdf.airflow": "Вентиляция и инфильтрация",
    "pdf.design_load": "Расчётная нагрузка",
    "pdf.recommended": "Рекомендуемая мощность (+{reserve}%)",
    "pdf.selection_range": "Диапазон подбора без ГВС",
    "pdf.sum_check": (
        "Проверка суммы: расчётная нагрузка равна сумме всех строк ниже; "
        "эксплуатационный запас показан отдельно."
    ),
    "pdf.formulas": "Формулы и построчный расчёт",
    "pdf.formulas_text": (
        "Ограждения: Q = U x A x ΔT x (1 + β) x n. Воздушные потери: "
        "Q = 0,33 x L x ΔT; рекуперация применяется только к механическому потоку. "
        "Линейные мостики: Q = ψ x L x ΔT."
    ),
    "pdf.element": "Элемент",
    "pdf.type": "Тип",
    "pdf.rounding": "Поправка округления",
    "pdf.total": "ИТОГО",
    "pdf.protocol": "Полный протокол и источники",
    "pdf.disclaimer_title": "Ограничение ответственности",
    "pdf.disclaimer": (
        "Отчёт является инженерной оценкой для подбора отопительной мощности, "
        "не является официальной проектной документацией и не заменяет проверку "
        "лицензированным проектировщиком."
    ),
    "pdf.footer": "U-Calc — инженерная оценка теплопотерь",
    "pdf.page": "Страница {page}",
    "survey.resume_fallback": (
        "Шаг восстановлен. Ответьте на последний вопрос. Если клавиатура недоступна, "
        "используйте /back или /new."
    ),
    "help.text": (
        "U-Calc оценивает пиковую отопительную нагрузку по ограждениям и воздухообмену. "
        "Результат не заменяет подписанный инженерный проект. ГВС и годовое потребление "
        "энергии в расчёт не входят."
    ),
}

UZ: dict[str, str] = {
    "language.name": "O‘zbekcha",
    "menu.title": "🏠 U-Calc — issiqlik yo‘qotish hisobi",
    "menu.subtitle": "Amalni tanlang:",
    "menu.new": "➕ Yangi hisob",
    "menu.history": "📁 Obyektlarim/hisoblarim",
    "menu.profiles": "⚙️ Hisob profillari",
    "menu.language": "🌐 Til",
    "menu.help": "ℹ️ Yordam va usul",
    "menu.home": "🏠 Menyuga",
    "language.title": "Interfeys tilini tanlang:",
    "language.saved": "Til saqlandi.",
    "profiles.title": "⚙️ Hisob profillari",
    "profiles.empty": "Hozircha profil yo‘q. Birinchi profilni yarating.",
    "profiles.create": "➕ Profil yaratish",
    "profiles.prepared_by": "🖊 PDF hisoboti muallifi",
    "profiles.prepared_by_ask": (
        "PDF uchun usta yoki tashkilot nomini kiriting (120 belgigacha). "
        "Maydonni tozalash uchun «-» yuboring:"
    ),
    "profiles.prepared_by_saved": "PDF muallifi saqlandi: {name}.",
    "profiles.prepared_by_cleared": "PDF muallifi maydoni tozalandi.",
    "profiles.rename": "✏️ Nomini o‘zgartirish",
    "profiles.settings": "🎛 Parametrlarni o‘zgartirish",
    "profiles.ask_indoor": "Ichki harorat, °C (-30 dan +50 gacha):",
    "profiles.ask_air": "Hisobiy havo almashinuvini tanlang:",
    "profiles.ask_safety": "Ekspluatatsion zaxirani tanlang:",
    "profiles.settings_saved": "Profil parametrlari saqlandi.",
    "profiles.summary": (
        "Ichkarida: {indoor} °C · havo almashinuvi: {air_changes} 1/soat · zaxira: {safety}%"
    ),
    "profiles.copy": "📋 Nusxalash",
    "profiles.default": "⭐ Asosiy qilish",
    "profiles.delete": "🗑 O‘chirish",
    "profiles.ask_name": "Profil nomini kiriting (1–60 belgi):",
    "profiles.ask_copy_name": "Nusxa nomini kiriting (1–60 belgi):",
    "profiles.created": "“{name}” profili yaratildi.",
    "profiles.renamed": "Profil nomi o‘zgartirildi.",
    "profiles.copied": "“{name}” nusxasi yaratildi.",
    "profiles.default_saved": "Profil asosiy profil etib belgilandi.",
    "profiles.delete_confirm": "“{name}” profilini o‘chirasizmi? Eski hisoblar saqlanadi.",
    "profiles.deleted": "Profil o‘chirildi.",
    "profiles.not_found": "Profil topilmadi.",
    "common.back": "⬅️ Orqaga",
    "common.cancel": "✖️ Bekor qilish",
    "common.confirm_delete": "Ha, o‘chirish",
    "common.yes": "Ha",
    "common.no": "Yo‘q",
    "common.error": "⚠️ {message}",
    "common.retry": "⚠️ {message}. Qayta urinib ko‘ring.",
    "common.invalid_input": "Kiritilgan qiymatni tekshiring",
    "common.invalid_option": "Noma’lum yoki eskirgan variant",
    "common.internal": "Ichki xato",
    "common.unhandled": (
        "Bu bosqichni qayta ishlab bo‘lmadi. Hisob ma’lumotlari to‘liq saqlanmagan "
        "bo‘lishi mumkin. Qayta urinib ko‘ring yoki /new orqali yangidan boshlang."
    ),
    "common.stale": "Bu tugma eskirgan. Joriy oynani /menu yoki /resume orqali oching.",
    "safety.access_denied": "U-Calc’dan foydalanish bot egasi tomonidan cheklangan.",
    "safety.message_too_long": "Xabar juda uzun. Ko‘pi bilan {limit} ta belgi mumkin.",
    "safety.rate_limited": "Juda ko‘p amal bajarildi. Bir daqiqa kutib davom eting.",
    "safety.calculation_rate_limited": (
        "Juda ko‘p hisob ishga tushirildi. Qayta urinishdan oldin bir daqiqa kuting."
    ),
    "survey.draft_missing": "Saqlangan qoralama yo‘q. Yangisini boshlash: /new",
    "survey.draft_restored": "Qoralama tiklandi. Saqlangan qadamdan davom etamiz:",
    "survey.draft_deleted": "Qoralama o‘chirildi.",
    "survey.cancelled": "Hisob bekor qilindi. Qaytadan boshlash: /new",
    "survey.back_restored": "⬅️ Oldingi qadamga qaytdik:",
    "survey.back_missing": "Oldingi qadam yo‘q. Hisobni boshlash: /new",
    "survey.back_missing_alert": "Oldingi qadam yo‘q",
    "survey.start": (
        "🏠 U-Calc eng katta issiqlik yo‘qotilishini hisoblaydi va issiqlik qayerga "
        "ketishini ko‘rsatadi.\n\nHisob tafsilotini tanlang:{profile_note}"
    ),
    "survey.profile_applied": "\n\n⭐ “{name}” profili qo‘llandi.",
    "survey.mode.quick": "Tezkor hisob",
    "survey.mode.advanced": "Kengaytirilgan hisob",
    "survey.object.question": "1/9-qadam — obyekt. Nimani hisoblaymiz?",
    "survey.object.apartment": "Kvartira",
    "survey.object.house": "Xususiy uy",
    "survey.position.question": (
        "Kvartira qaysi qavatda? Isitiladigan qo‘shni bilan tutash orayopmalar "
        "avtomatik ravishda chiqarib tashlanadi."
    ),
    "survey.position.middle": "O‘rta qavat",
    "survey.position.first": "Birinchi qavat",
    "survey.position.last": "Oxirgi qavat",
    "survey.position.first_last": "Birinchi va oxirgi",
    "survey.object_name": ("Tarix va versiyalar uchun obyekt nomi, masalan “Yunusobod uyi”: "),
    "survey.climate.question": "2/9-qadam — iqlim. Profilni tanlang:",
    "survey.climate.custom": "Boshqa shahar (to‘liq profil)",
    "survey.climate.manual": "Faqat haroratni qo‘lda kiritish",
    "survey.climate.manual_name": "Harorat qo‘lda kiritilgan",
    "climate.tashkent": "Toshkent",
    "climate.samarkand": "Samarqand",
    "climate.nukus": "Nukus",
    "survey.outdoor_manual": ("Qishki hisobiy tashqi haroratni kiriting, °C (masalan -18):"),
    "survey.city_name": "Shahar yoki aholi punkti nomi:",
    "survey.custom.cold_mean": "Eng sovuq oyning o‘rtacha harorati, °C:",
    "survey.custom.design": "Isitish uchun qishki hisobiy harorat, °C:",
    "survey.custom.extreme": "Kuzatilgan mutlaq minimum, °C:",
    "survey.custom.hot_mean": "Eng issiq oyning o‘rtacha harorati, °C:",
    "survey.custom.hot_max": "Kuzatilgan mutlaq maksimum, °C:",
    "survey.profile_design": (
        "{city} uchun oylik o‘rtacha va ekstremal haroratlar ШНҚ 2.01.01-22 "
        "1-jadvali bilan tasdiqlangan, ammo hisobiy sovuq qiymati tasdiqlanishi kerak.\n\n"
        "B parametr haroratini kiriting, °C — 0,92 ta’minlanganlikdagi eng sovuq "
        "besh kunlik:"
    ),
    "survey.scenario.question": (
        "2/9-qadam — iqlim. {city}: hisob rejimini tanlang.\n"
        "Eng sovuq oyning o‘rtachasi {cold} °C; hisobiy sovuq {design} °C; "
        "kuzatilgan ekstremum {extreme} °C.\n"
        "Yoz uchun ma’lumot: issiq oyning o‘rtachasi {hot} °C, mutlaq maksimum "
        "{maximum} °C. Yozgi qiymatlar isitish yukiga kirmaydi.\n"
        "Iqlim zaxirasi — hisobiy qiymatdan 2 °C sovuq stress-senariy; "
        "bu aniq ob-havo prognozi emas."
    ),
    "survey.scenario.economy": "Oddiy qish",
    "survey.scenario.design": "Hisobiy sovuq",
    "survey.scenario.extreme": "Ekstremum",
    "survey.scenario.future": "Iqlim zaxirasi",
    "survey.indoor": (
        "3/9-qadam — harorat. Tashqarida {outdoor} °C. "
        "Ichkarida qanday harorat kerak, °C? Masalan 24"
    ),
    "survey.from_profile_temperature": "Profildan: {temperature} °C",
    "survey.dimensions": (
        "4/9-qadam — geometriya. Uzunlik, kenglik va balandlikni kiriting, m: 10 8 3"
    ),
    "survey.wall_method.question": (
        "4/9-qadam — devorlar. Faqat tashqi sovuq devorlarni qanday kiritamiz?"
    ),
    "survey.wall_method.area": "Umumiy maydon bilan",
    "survey.wall_method.dimensions": "Har bir devor o‘lchami",
    "survey.wall_method.perimeter": "Butun perimetr",
    "survey.wall_method.editor": "Turli konstruksiyalar — bosqichma-bosqich",
    "survey.wall_method.import": "Satrlar orqali ekspert importi |",
    "survey.wall.area": (
        "Deraza va eshiklar maydonini ayirmasdan tashqi devorlarning umumiy maydonini kiriting, m²:"
    ),
    "survey.wall.dimensions": "Har bir devorning eni×balandligini kiriting: 5x3, 4x3",
    "survey.wall.material": "4/9-qadam — devorlar. Tashqi devorning asosiy materiali:",
    "survey.wall.material_custom": "Boshqa material — pasportdagi λ",
    "survey.wall.custom_lambda": "Materialning pasportdagi λ qiymati, Vt/(m·K):",
    "survey.wall.thickness": "“{material}” qatlamining qalinligi, sm, masalan 25:",
    "survey.wall.custom_thickness": "Ushbu materialning qalinligi, sm:",
    "survey.wall.insulated": "Devor issiqlik izolyatsiyasi bilan qoplanganmi?",
    "survey.wall.insulation": "Qaysi issiqlik izolyatsiyasi?",
    "survey.wall.insulation_custom": "Boshqa izolyatsiya — pasportdagi λ",
    "survey.wall.insulation_lambda": (
        "Issiqlik izolyatsiyasining pasportdagi λ qiymati, Vt/(m·K):"
    ),
    "survey.wall.insulation_thickness": (
        "“{material}” izolyatsiyasining qalinligi, sm, masalan 5:"
    ),
    "survey.wall.custom_insulation_thickness": "Ushbu izolyatsiyaning qalinligi, sm:",
    "survey.window.count": "5/9-qadam — tirqishlar. Tashqi derazalar soni nechta? Bo‘lmasa — 0:",
    "survey.door.count": "5/9-qadam — tirqishlar. Tashqi eshiklar soni nechta? Bo‘lmasa — 0:",
    "survey.opening.area_method": "Umumiy maydon bilan",
    "survey.opening.dimensions_method": "Bitta element o‘lchami bilan",
    "survey.opening.editor_method": "Turli guruhlar va U — bosqichma-bosqich",
    "survey.opening.import_method": "Satrlar orqali ekspert importi |",
    "survey.window.method": "Derazalarni qanday kiritamiz?",
    "survey.window.area": "Barcha tashqi derazalarning umumiy maydoni, m²:",
    "survey.window.dimensions": (
        "Bitta odatiy derazaning eni × balandligi, metrda, masalan 1,4x1,5:"
    ),
    "survey.window.type": "Deraza turi:",
    "survey.door.method": "Tashqi eshiklarni qanday kiritamiz?",
    "survey.door.area": "Tashqi eshiklarning umumiy maydoni, m²:",
    "survey.door.dimensions": ("Bitta odatiy eshikning eni × balandligi, metrda, masalan 0,9x2,1:"),
    "survey.door.type": (
        "Eshik turi (U ma’lumot uchun; pasport qiymati guruhlar orqali kiritiladi):"
    ),
    "window.single": "Bir qatlamli oyna",
    "window.double_old": "Eski ikki qavatli deraza",
    "window.double": "Ikki oynali shisha paket",
    "window.triple": "Uch oynali shisha paket",
    "window.efficient": "Energiya tejamkor deraza",
    "door.wood_old": "Eski yog‘och eshik",
    "door.metal_basic": "Termik uzilishsiz metall eshik",
    "door.insulated": "Izolyatsiyalangan tashqi eshik",
    "door.efficient": "Energiya tejamkor eshik",
    "opening.windows": "derazalar",
    "opening.doors": "eshiklar",
    "opening.editor.name": (
        "{kind} guruhi nomi, masalan “Shimoliy PVX”. Jami ko‘rsatilgan: {expected}."
    ),
    "opening.editor.count": "Ushbu guruhdagi bir xil tirqishlar soni:",
    "opening.editor.dimensions": "Bitta tirqish eni × balandligi, m, masalan 1,4×1,5:",
    "opening.editor.u_value": "Tirqishning pasportdagi U qiymati, Vt/(m²·K), masalan 1,1:",
    "opening.editor.wall": "Guruh qaysi devorga tegishli?",
    "opening.editor.no_wall": "Devorga biriktirmaslik",
    "opening.editor.saved": "Saqlangan {kind} guruhlari — {used}/{expected}:\n{summary}",
    "opening.editor.summary": "• {name}: {count} dona, {area} m², U={u_value}",
    "opening.editor.add": "➕ Guruh qo‘shish",
    "opening.editor.edit": "✏️ O‘zgartirish: {name}",
    "opening.editor.delete_named": "🗑 O‘chirish: {name}",
    "opening.editor.delete": "🗑 Oxirgisini o‘chirish",
    "opening.editor.finish": "✅ Tayyor",
    "opening.editor.name_resume": "{kind} guruhi nomi. Jami ko‘rsatilgan: {expected}.",
    "opening.editor.retry": "⚠️ {message}. Qayta urinib ko‘ring.",
    "opening.editor.error.name_length": "Nom 1 dan 60 tagacha belgidan iborat bo‘lishi kerak",
    "opening.editor.error.duplicate": "“{name}” guruh nomi avval ishlatilgan",
    "opening.editor.error.integer": "Butun son kiriting",
    "opening.editor.error.count_range": "1 dan {remaining} tagacha {kind} qo‘shish mumkin",
    "opening.editor.error.dimensions": "Bitta o‘lcham juftini kiriting, masalan 1,4×1,5",
    "opening.editor.error.u_value": "U 0,1 dan 8 Vt/(m²·K) gacha bo‘lishi kerak",
    "opening.editor.error.stale_wall": "Bu devor endi mavjud emas",
    "opening.editor.error.total_area": "Tirqishlarning umumiy maydoni devorlar maydonidan katta",
    "opening.editor.error.wall_area": "“{wall}” devoridagi tirqishlar uning maydonidan katta",
    "opening.editor.error.distributed": "Ko‘rsatilgan barcha tirqishlar taqsimlangan",
    "opening.editor.error.empty": "Ro‘yxat allaqachon bo‘sh",
    "opening.editor.error.incomplete": (
        "{expected} tadan {used} tasi taqsimlangan. Qolgan tirqishlarni qo‘shing."
    ),
    "opening.editor.error.unknown_action": "Noma’lum amal",
    "opening.editor.error.stale_group": "Guruh endi mavjud emas",
    "survey.boundary.floor": "6/9-qadam — pol va shift. Pol ostida nima bor?",
    "survey.boundary.ceiling": "6/9-qadam — pol va shift. Shift ustida nima bor?",
    "survey.boundary.heated_neighbor": "Isitiladigan qo‘shni",
    "survey.boundary.unheated_basement": "Sovuq yerto‘la",
    "survey.boundary.ground": "Grunt",
    "survey.boundary.outdoor": "Tashqi havo",
    "survey.boundary.unheated_attic": "Sovuq chordoq",
    "survey.boundary.roof": "Tashqi havo / tom",
    "survey.adjacent.question": (
        "{zone} harorati ma’lummi? Aniq qiymat doimiy koeffitsiyentdan yaxshiroq."
    ),
    "survey.adjacent.basement": "yerto‘la yoki pol ostidagi gruntning",
    "survey.adjacent.attic": "sovuq chordoqning",
    "survey.adjacent.manual": "Haroratni kiritish",
    "survey.adjacent.estimate": "{estimate} bahoni qoldirish",
    "survey.adjacent.ground_estimate": "tashqi ΔT ning 50%i",
    "survey.adjacent.unheated_estimate": "tashqi ΔT ning 70%i",
    "survey.adjacent.zonal": "ШНҚ me’yoriy zonalari",
    "survey.adjacent.temperature": (
        "Tutash zonaning hisobiy harorati, °C. Masalan, yerto‘la uchun +5:"
    ),
    "survey.neighbor.below": "pastdagi qo‘shni",
    "survey.neighbor.above": "yuqoridagi qo‘shni",
    "survey.neighbor.question": "{zone} harorati obyekt ichidagi harorat bilan bir xilmi?",
    "survey.neighbor.same": "Bir xil — yo‘qotish yo‘q",
    "survey.neighbor.manual": "Qo‘shni haroratini kiritish",
    "survey.ground.insulation": (
        "Polning λ < 1,2 Vt/(m·K) bo‘lgan izolyatsiya qatlami bormi? "
        "Asosiy beton plita zonaning me’yoriy R qiymatiga alohida qo‘shilmaydi."
    ),
    "survey.ground.sides": (
        "To‘g‘ri to‘rtburchak polning qaysi tomonlari tashqi devorlarga tutashadi? "
        "Shimol/janub — L uzunlikdagi, sharq/g‘arb — W kenglikdagi tomonlar."
    ),
    "survey.ground.sides.all": "Barcha 4 tomon",
    "survey.ground.sides.n": "Shimol (L)",
    "survey.ground.sides.e": "Sharq (W)",
    "survey.ground.sides.s": "Janub (L)",
    "survey.ground.sides.w": "G‘arb (W)",
    "survey.ground.sides.ns": "Shimol + janub",
    "survey.ground.sides.ew": "Sharq + g‘arb",
    "survey.ground.sides.ne": "Shimol + sharq",
    "survey.ground.sides.es": "Sharq + janub",
    "survey.ground.sides.sw": "Janub + g‘arb",
    "survey.ground.sides.wn": "G‘arb + shimol",
    "survey.ground.sides.no_n": "Shimolsiz",
    "survey.ground.sides.no_e": "Sharqsiz",
    "survey.ground.sides.no_s": "Janubsiz",
    "survey.ground.sides.no_w": "G‘arbsiz",
    "survey.ground.sides.complex": "Murakkab reja",
    "survey.ground.complex_help": (
        "Bu usul murakkab konturni ishonchli yaqinlashtirmaydi. Rejani to‘g‘ri "
        "to‘rtburchaklarga ajrating va alohida hisoblang."
    ),
    "survey.ground.construction": "Grunt ustidagi pol konstruksiyasi:",
    "survey.ground.solid": "Yaxlit pol",
    "survey.ground.joists": "Lagali pol",
    "survey.surface.floor": "polning",
    "survey.surface.ceiling": "orayopma/tomning",
    "survey.surface.material": "{surface} asosiy materiali:",
    "survey.surface.insulated": "Issiqlik izolyatsiyasi bormi?",
    "survey.surface.insulation": "Izolyatsiya materiali:",
    "survey.air.quick": (
        "7/9-qadam — ventilyatsiya. Havo almashinuvini baholang: germetik bino — 0,3; "
        "odatdagi — 0,5; eski yoki yelvizakli — 0,8–1,0. Tezkor rejimda bu yagona, "
        "issiqligi qayta olinmaydigan oqim; rekuperatsiya undan ayrilmaydi."
    ),
    "survey.air.from_profile": "⭐ Profildan: {value}",
    "survey.air.advanced": (
        "7/9-qadam — ventilyatsiya. Alohida hisobiy oqimlar qanday kiritiladi?"
    ),
    "survey.air.unit.m3h": "Sarf, m³/soat",
    "survey.air.unit.ach": "Karralilik, 1/soat",
    "survey.air.units.m3h": "m³/soat",
    "survey.air.units.ach": "1/soat",
    "survey.air.mechanical": (
        "Tashkillashtirilgan mexanik ventilyatsiya sarfi, {unit}. Bo‘lmasa — 0:"
    ),
    "survey.air.natural": (
        "Tashkillashtirilgan tabiiy ventilyatsiya sarfi, {unit}. Bo‘lmasa — 0:"
    ),
    "survey.air.infiltration": "Tirqishlar orqali hisobiy infiltratsiya, {unit}. Bo‘lmasa — 0:",
    "survey.air.recovery": "Mexanik ventilyatsiyada rekuperatsiya bormi?",
    "survey.air.recovery_efficiency": "Rekuperatorning pasportdagi FIK qiymati, %. Masalan 70:",
    "survey.air.error.invalid": "Havo almashinuvi noto‘g‘ri",
    "survey.air.error.option": "Havo almashinuvining noma’lum varianti",
    "survey.air.error.units_required": "Alohida oqimlar uchun birliklarni tanlang",
    "survey.air.error.units": "Sarf birligi noma’lum",
    "survey.air.error.advanced_only": "Alohida kiritish faqat kengaytirilgan rejimda mavjud",
    "survey.air.error.recovery": "Noma’lum variant",
    "survey.recovery.quick": (
        "Rekuperator bormi? Tezkor rejimda u faqat ma’lumot sifatida qayd etiladi va "
        "umumiy bahoni kamaytirmaydi. Buning uchun kengaytirilgan rejimda mexanik "
        "ventilyatsiyani alohida kiriting."
    ),
    "survey.recovery.quick_note": (
        "Rekuperator umumiy bahodan ayrilmadi. Mexanik ventilyatsiyani alohida kiritish "
        "uchun hisobni kengaytirilgan rejimda takrorlang."
    ),
    "survey.bridges.question": (
        "8/9-qadam — sovuq ko‘priklari (tutashuvlar, burchaklar, to‘sinlar, balkonlar):"
    ),
    "survey.bridges.zero": "0% — alohida hisoblangan",
    "survey.bridges.good": "5% — sifatli bajarilgan",
    "survey.bridges.normal": "10% — odatdagi",
    "survey.bridges.weak": "15% — zaif tugunlar ko‘p",
    "survey.bridges.exact": "Aniq: ψ × uzunlikni bosqichma-bosqich",
    "survey.bridges.import": "Satrlar orqali ekspert importi |",
    "bridge.editor.name": "Sovuq ko‘prigi nomi, masalan “Balkon plitasi”:",
    "bridge.editor.length": "Ushbu ko‘prikning umumiy uzunligi, m:",
    "bridge.editor.psi": "Chiziqli ψ koeffitsiyenti, Vt/(m·K), masalan 0,35:",
    "bridge.editor.saved": "Saqlangan sovuq ko‘priklari ({count}/30):\n{summary}",
    "bridge.editor.summary": "• {name}: {length} m × ψ={psi}",
    "bridge.editor.add": "➕ Ko‘prik qo‘shish",
    "bridge.editor.edit": "✏️ O‘zgartirish: {name}",
    "bridge.editor.delete_named": "🗑 O‘chirish: {name}",
    "bridge.editor.delete": "🗑 Oxirgisini o‘chirish",
    "bridge.editor.finish": "✅ Tayyor",
    "bridge.editor.retry": "⚠️ {message}. Qayta urinib ko‘ring.",
    "bridge.editor.error.name": "Nom 1 dan 60 tagacha belgidan iborat bo‘lishi kerak",
    "bridge.editor.error.length": "Uzunlik 0,01 dan 10 000 m gacha bo‘lishi kerak",
    "bridge.editor.error.psi": "ψ 0 dan 5 Vt/(m·K) gacha bo‘lishi kerak",
    "bridge.editor.error.limit": "Ko‘pi bilan 30 ta sovuq ko‘prigi kiritish mumkin",
    "bridge.editor.error.limit_alert": "30 ta ko‘prik chegarasiga yetildi",
    "bridge.editor.error.empty": "Sovuq ko‘priklari ro‘yxati allaqachon bo‘sh",
    "bridge.editor.error.required": "Kamida bitta sovuq ko‘prigini qo‘shing",
    "bridge.editor.error.action": "Noma’lum amal",
    "bridge.editor.error.stale": "Ko‘prik endi mavjud emas",
    "survey.safety.question": (
        "9/9-qadam — barcha hisoblangan yo‘qotishlardan keyingi ekspluatatsion zaxira:"
    ),
    "survey.safety.normal": "10% — odatda",
    "survey.safety.from_profile": "⭐ Profildan: {value}%",
    "survey.confirm.title": "✅ Hisoblashdan oldin boshlang‘ich ma’lumotlarni tekshiring",
    "survey.confirm.body": (
        "{title}\n\nObyekt: {building}\nIqlim: {climate}, tashqarida {outdoor} °C\n"
        "Ichkarida: {indoor} °C\nO‘lchamlar: {length} × {width} × {height} m\n"
        "Devorlarning brutto maydoni: {walls} m²; tirqishlar: {openings} m²\n"
        "Havo almashinuvi: {airflow}\nZaxira: {safety}%\n\n"
        "Hammasi to‘g‘ri bo‘lsa, “Hisoblash” tugmasini bosing."
    ),
    "survey.confirm.airflow_simple": "{value} 1/soat (soddalashtirilgan)",
    "survey.confirm.airflow_total": "jami {value} m³/soat",
    "survey.confirm.calculate": "Hisoblash",
    "survey.confirm.climate": "Iqlimni o‘zgartirish",
    "survey.confirm.walls": "Devorlarni o‘zgartirish",
    "survey.confirm.openings": "Tirqishlarni o‘zgartirish",
    "survey.confirm.boundaries": "Pol/shiftni o‘zgartirish",
    "survey.confirm.airflow": "Ventilyatsiyani o‘zgartirish",
    "survey.confirm.error.action": "Noma’lum amal",
    "summary.ready": "🔥 Hisob tayyor: {name}",
    "summary.load": "Hisobiy yuklama: {value} kVt",
    "summary.range": "Tavsiya etilgan oraliq: {minimum}–{maximum} kVt",
    "summary.reserve": "Qabul qilingan zaxira: {value}%",
    "summary.temperature": "Hisobiy harorat: {value} °C ({scenario}, {city})",
    "summary.temperature_manual": "Hisobiy harorat: {value} °C (qo‘lda kiritilgan)",
    "summary.destinations": "Issiqlik qayerga ketadi:",
    "summary.category.walls": "devorlar",
    "summary.category.openings": "deraza va eshiklar",
    "summary.category.boundaries": "pol va yuqori qism",
    "summary.category.airflow": "ventilyatsiya va infiltratsiya",
    "summary.category.bridges": "sovuq ko‘priklari",
    "summary.category.line": "• {name} — {value} kVt ({percent}%)",
    "summary.warning.title": "⚠️ Aniqlashtirish kerak:",
    "summary.warning.manual_climate": "iqlim qo‘lda kiritilgan",
    "summary.warning.openings": (
        "ayrim tirqishlarning U qiymati ma’lumot uchun — pasportni tekshiring"
    ),
    "summary.warning.materials": "ayrim materiallarning λ qiymati ma’lumot uchun",
    "summary.warning.assumptions": "hisobda muhandislik farazlari bor — PDF hisobotni tekshiring",
    "summary.footer": "Issiq suv va yillik energiya sarfi kiritilmagan. To‘liq bayonnoma PDFda.",
    "summary.untitled": "Nomsiz",
    "result.saved": "Hisob №{id}",
    "result.unsaved": "⚠️ Hisob bajarildi, lekin tarixga saqlanmadi.",
    "result.invalid": (
        "⚠️ Hisobni yakunlab bo‘lmadi: {message}. "
        "/new orqali qayta boshlang va ma’lumotlarni tekshiring."
    ),
    "result.internal": (
        "Ichki xato sababli hisobni yakunlab bo‘lmadi. Ma’lumotlar saqlanmadi; "
        "/new orqali qayta urinib ko‘ring yoki administratorga xabar bering."
    ),
    "result.pdf_caption": "U-Calc PDF hisoboti",
    "result.pdf_failed": "Matnli hisob tayyor, ammo PDF yaratilmadi. Ma’lumotlar saqlandi.",
    "result.new": "Yangi hisob: /new",
    "material.brick_solid": "To‘liq g‘isht",
    "material.brick_hollow": "G‘ovak g‘isht",
    "material.aerated_d500": "D500 gazoblok",
    "material.concrete": "Temirbeton",
    "material.wood": "Tolalarga ko‘ndalang yog‘och",
    "material.mineral_wool": "Mineral paxta mat",
    "material.eps": "EPS penopolistirol",
    "material.xps": "XPS ekstrudirovka penopolistirol",
    "material.pu_foam": "Poliuretan ko‘pik",
    "wall.editor.name": "Devor yoki guruh nomi, masalan “Shimoliy devor” (60 belgigacha):",
    "wall.editor.area": "Devor maydoni, m², yoki eni×balandligi, masalan 18 yoki 6×3:",
    "wall.editor.orientation": (
        "Tashqi devor yo‘nalishi. U SHNQ 2.04.05-22 9-ilovasiga ko‘ra "
        "me’yoriy β qo‘shimchasini belgilaydi:"
    ),
    "wall.editor.orientation.unknown": "Noma’lum — β=0",
    "wall.editor.orientation.north": "Shimol — β=10%",
    "wall.editor.orientation.north_east": "Shimoli-sharq — β=10%",
    "wall.editor.orientation.east": "Sharq — β=10%",
    "wall.editor.orientation.south_east": "Janubi-sharq — β=5%",
    "wall.editor.orientation.south": "Janub — β=0",
    "wall.editor.orientation.south_west": "Janubi-g‘arb — β=0",
    "wall.editor.orientation.west": "G‘arb — β=5%",
    "wall.editor.orientation.north_west": "Shimoli-g‘arb — β=10%",
    "wall.editor.material": "Devorning asosiy materiali:",
    "wall.editor.passport": "Pasportdagi λ",
    "wall.editor.lambda": "Materialning pasportdagi λ qiymati, Vt/(m·K):",
    "wall.editor.thickness": "“{material}” qalinligi, sm:",
    "wall.editor.base_thickness": "Asosiy material qalinligi, sm:",
    "wall.editor.insulated": "Bu devorda issiqlik izolyatsiyasi bormi?",
    "wall.editor.insulation": "Izolyatsiya materiali:",
    "wall.editor.insulation_lambda": "Izolyatsiyaning pasportdagi λ qiymati, Vt/(m·K):",
    "wall.editor.insulation_thickness": "Izolyatsiya qalinligi, sm:",
    "wall.editor.layers": "Konstruksiyadagi qatlamlar: {count}. Yana qo‘shilsinmi?",
    "wall.editor.add_layer": "➕ Qatlam qo‘shish",
    "wall.editor.finish_layers": "✅ Konstruksiya tayyor",
    "wall.editor.next_layer": "Keyingi qatlam materiali:",
    "wall.editor.saved": "Saqlangan devorlar ({count}/12):\n{summary}",
    "wall.editor.summary": "• {name}: {area} m²; {orientation}",
    "wall.editor.add_wall": "➕ Devor qo‘shish",
    "wall.editor.edit_wall": "✏️ O‘zgartirish: {name}",
    "wall.editor.delete_named_wall": "🗑 O‘chirish: {name}",
    "wall.editor.delete_wall": "🗑 Oxirgisini o‘chirish",
    "wall.editor.finish": "✅ Tayyor",
    "wall.editor.resume_layers": "Keyingi qatlamni qo‘shing yoki konstruksiyani tugating.",
    "wall.editor.retry": "⚠️ {message}. Qayta urinib ko‘ring.",
    "wall.editor.error.name": "Nom 1 dan 60 tagacha belgidan iborat bo‘lishi kerak",
    "wall.editor.error.duplicate": "“{name}” devor nomi avval ishlatilgan",
    "wall.editor.error.area": "0,1–100 000 m² maydon yoki bitta o‘lcham juftini kiriting",
    "wall.editor.error.orientation": "Devor yo‘nalishi noma’lum",
    "wall.editor.error.lambda": "λ 0,005 dan 5 Vt/(m·K) gacha bo‘lishi kerak",
    "wall.editor.error.thickness": "Qalinlik 0,1 dan 200 sm gacha bo‘lishi kerak",
    "wall.editor.error.layer_limit": "Konstruksiya ko‘pi bilan 10 qatlamdan iborat bo‘lishi mumkin",
    "wall.editor.error.layer_limit_alert": "10 qatlam chegarasiga yetildi",
    "wall.editor.error.wall_limit": "Ko‘pi bilan 12 ta devor guruhini kiritish mumkin",
    "wall.editor.error.wall_limit_alert": "12 ta devor chegarasiga yetildi",
    "wall.editor.error.empty": "Devorlar ro‘yxati allaqachon bo‘sh",
    "wall.editor.error.required": "Kamida bitta devor qo‘shing",
    "wall.editor.error.material": "Noma’lum material",
    "wall.editor.error.insulation": "Noma’lum izolyatsiya",
    "wall.editor.error.option": "Noma’lum variant",
    "wall.editor.error.action": "Noma’lum amal",
    "wall.editor.error.stale": "Devor endi mavjud emas",
    "pdf.title": "Eng yuqori issiqlik yukini hisoblash",
    "pdf.object": "Obyekt",
    "pdf.unnamed": "Nomsiz",
    "pdf.date": "Sana (Asia/Tashkent)",
    "pdf.prepared_by": "Hisobni tayyorlagan",
    "pdf.language": "Til",
    "pdf.calculation_id": "Hisob ID",
    "pdf.versions": "Versiyalar",
    "pdf.versions_value": "dvigatel {engine}; katalog {catalog}; me’yorlar {norms}",
    "pdf.result": "Natija",
    "pdf.transmission": "To‘siqlar, ochiqlar va issiqlik ko‘priklari",
    "pdf.airflow": "Ventilyatsiya va infiltratsiya",
    "pdf.design_load": "Hisobiy yuklama",
    "pdf.recommended": "Tavsiya etilgan quvvat (+{reserve}%)",
    "pdf.selection_range": "Issiq suvsiz tanlash oralig‘i",
    "pdf.sum_check": (
        "Tekshiruv: hisobiy yuklama quyidagi barcha satrlar yig‘indisiga teng; "
        "ekspluatatsion zaxira alohida ko‘rsatilgan."
    ),
    "pdf.formulas": "Formulalar va satrma-satr hisob",
    "pdf.formulas_text": (
        "To‘siqlar: Q = U x A x ΔT x (1 + β) x n. Havo yo‘qotishlari: "
        "Q = 0,33 x L x ΔT; rekuperatsiya faqat mexanik oqimga qo‘llanadi. "
        "Chiziqli issiqlik ko‘priklari: Q = ψ x L x ΔT."
    ),
    "pdf.element": "Element",
    "pdf.type": "Turi",
    "pdf.rounding": "Yaxlitlash tuzatishi",
    "pdf.total": "JAMI",
    "pdf.protocol": "To‘liq bayonnoma va manbalar",
    "pdf.disclaimer_title": "Mas’uliyatni cheklash",
    "pdf.disclaimer": (
        "Hisobot isitish quvvatini tanlash uchun muhandislik bahosidir, rasmiy loyiha "
        "hujjati hisoblanmaydi va litsenziyali loyihachining tekshiruvini almashtirmaydi."
    ),
    "pdf.footer": "U-Calc — issiqlik yo‘qotishlarining muhandislik bahosi",
    "pdf.page": "Sahifa {page}",
    "survey.resume_fallback": (
        "Qadam tiklandi. Oxirgi savolga javob bering. Klaviatura ko‘rinmasa, "
        "/back yoki /new buyrug‘idan foydalaning."
    ),
    "help.text": (
        "U-Calc to‘siqlar va havo almashinuvi bo‘yicha eng katta isitish yukini baholaydi. "
        "Natija imzolangan muhandislik loyihasini almashtirmaydi. Issiq suv va yillik "
        "energiya sarfi hisobga kirmaydi."
    ),
}

CATALOGS: Mapping[str, Mapping[str, str]] = {"ru": RU, "uz": UZ}


def validate_catalogs() -> None:
    expected = set(RU)
    for locale, catalog in CATALOGS.items():
        missing = expected - set(catalog)
        extra = set(catalog) - expected
        if missing or extra:
            raise RuntimeError(
                f"Translation catalog {locale!r} differs: missing={sorted(missing)}, "
                f"extra={sorted(extra)}"
            )


def normalize_locale(locale: str | None) -> str:
    return locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE


def translate(key: str, locale: str = DEFAULT_LOCALE, **values: object) -> str:
    catalog = CATALOGS[normalize_locale(locale)]
    try:
        template = catalog[key]
    except KeyError as exc:
        raise KeyError(f"Unknown translation key: {key}") from exc
    return template.format(**values)


validate_catalogs()
