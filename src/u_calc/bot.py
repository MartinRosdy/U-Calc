import asyncio
import logging
import math
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.types.error_event import ErrorEvent

from .catalog import CLIMATES, DOORS, MATERIALS, WINDOWS, ClimateProfile
from .config import Settings
from .keyboards import keyboard
from .middleware import AccessMiddleware, NavigationMiddleware
from .models import Boundary
from .parsing import (
    parse_dimensions,
    parse_door_groups,
    parse_linear_thermal_bridges,
    parse_number,
    parse_triplet,
    parse_wall_groups,
    parse_window_groups,
)
from .services.building_factory import InvalidCalculationData, climate_from_answers
from .services.calculation_service import calculate_from_answers
from .states import Survey
from .storage import CalculationRepository

router = Router(name=__name__)
logger = logging.getLogger(__name__)


def _nonnegative(text: str | None) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите число, например 12,5") from exc
    if not math.isfinite(value):
        raise ValueError("Значение должно быть конечным числом")
    if not 0 <= value <= 100_000:
        raise ValueError("Значение должно быть от 0 до 100 000")
    return value


def _temperature(text: str) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите температуру числом, например -18") from exc
    if not math.isfinite(value) or not -80 <= value <= 70:
        raise ValueError("Ожидается температура от -80 до +70 °C")
    return value


def _conductivity(text: str) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите λ числом, например 0,041") from exc
    if not math.isfinite(value) or not 0.005 <= value <= 5:
        raise ValueError("λ должна быть от 0,005 до 5 Вт/(м·К)")
    return value


async def _error(message: Message, exc: ValueError) -> None:
    await message.answer(f"⚠️ {exc}. Попробуйте ещё раз.")


async def _send_long_message(message: Message, text: str, limit: int = 3900) -> None:
    """Send text without exceeding Telegram's message length limit."""
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            await message.answer(remaining)
            return
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        await message.answer(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")


async def _ask_wall_material(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.wall_material)
    keys = ["brick_solid", "brick_hollow", "aerated_d500", "concrete", "wood"]
    items = [(MATERIALS[key].name, f"mat:{key}") for key in keys]
    items.append(("Другой материал — паспортная λ", "mat:custom"))
    await message.answer(
        "Шаг 4/9 — стены. Основной материал наружных стен:",
        reply_markup=keyboard(items, 1),
    )


async def _ask_windows(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.window_count)
    await message.answer("Шаг 5/9 — проёмы. Сколько наружных окон? Если окон нет — 0:")


async def _ask_doors(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.door_count)
    await message.answer("Шаг 5/9 — проёмы. Сколько наружных дверей? Если дверей нет — 0:")


def _parse_count(text: str) -> int:
    try:
        value = int(text.strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError("Введите целое количество, например 3") from exc
    if value < 0 or value > 500:
        raise ValueError("Количество должно быть от 0 до 500")
    return value


@router.message(CommandStart())
@router.message(Command("new"))
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Survey.calculation_mode)
    await message.answer(
        "🏠 U-Calc рассчитает пиковые теплопотери и покажет, куда уходит тепло.\n\n"
        "Выберите уровень детализации:",
        reply_markup=keyboard(
            [
                ("Быстрый расчёт", "mode:quick"),
                ("Расширенный расчёт", "mode:advanced"),
            ],
            1,
            navigation=False,
        ),
    )


@router.callback_query(Survey.calculation_mode, F.data.startswith("mode:"))
async def calculation_mode(callback: CallbackQuery, state: FSMContext) -> None:
    mode = callback.data.split(":", 1)[1]
    if mode not in {"quick", "advanced"}:
        await callback.answer("Неизвестный режим", show_alert=True)
        return
    await state.update_data(calculation_mode=mode)
    await state.set_state(Survey.building_type)
    await callback.message.answer(
        "Шаг 1/9 — объект. Что рассчитываем?",
        reply_markup=keyboard([("Квартиру", "type:apartment"), ("Частный дом", "type:house")]),
    )
    await callback.answer()


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Команды:\n/new — новый расчёт\n/history — последние расчёты\n"
        "/report N — открыть сохранённый расчёт №N\n"
        "/delete_history — удалить свою историю\n"
        "/back — предыдущий шаг\n/cancel — отменить\n/help — справка\n\n"
        "Бот считает Q = U × A × ΔT для ограждений и 0,33 × n × V × ΔT для воздухообмена. "
        "Результат — требуемая мощность в расчётный мороз, а не месячное потребление."
    )


@router.message(Command("history"))
async def history(message: Message, repository: CalculationRepository, settings: Settings) -> None:
    records = await asyncio.to_thread(repository.recent, message.from_user.id, 5)
    if not records:
        await message.answer("История пока пуста. Начните расчёт командой /new")
        return
    lines = ["🗂 Последние расчёты:"]
    for record in records:
        created = (
            datetime.fromisoformat(record.created_at)
            .astimezone(settings.timezone)
            .strftime("%d.%m.%Y %H:%M")
        )
        kind = "квартира" if record.building_type == "apartment" else "дом"
        lines.append(
            f"• №{record.id} · {created} · {kind} · {record.recommended_kw:.2f} кВт с запасом"
        )
    await message.answer("\n".join(lines))


@router.message(Command("report"))
async def saved_report(message: Message, repository: CalculationRepository) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip().isdigit():
        await message.answer("Укажите номер: /report 12")
        return
    calculation_id = int(parts[1].strip())
    record = await asyncio.to_thread(repository.get_for_user, message.from_user.id, calculation_id)
    if record is None:
        await message.answer("Расчёт с таким номером не найден в вашей истории.")
        return
    await _send_long_message(message, f"Расчёт №{record.id}\n\n{record.report}")


@router.message(Command("delete_history"))
async def delete_history_prompt(message: Message) -> None:
    await message.answer(
        "Удалить все ваши сохранённые расчёты? Это действие нельзя отменить.",
        reply_markup=keyboard(
            [
                ("Да, удалить", "delete_history:confirm"),
                ("Отмена", "delete_history:cancel"),
            ],
            1,
        ),
    )


@router.callback_query(F.data.startswith("delete_history:"))
async def delete_history(callback: CallbackQuery, repository: CalculationRepository) -> None:
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await callback.message.answer("Удаление отменено.")
    elif action == "confirm":
        deleted = await asyncio.to_thread(repository.delete_for_user, callback.from_user.id)
        await callback.message.answer(f"Удалено расчётов: {deleted}.")
    else:
        await callback.answer("Неизвестное действие", show_alert=True)
        return
    await callback.answer()


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Расчёт отменён. Чтобы начать заново: /new")


async def _go_back(state: FSMContext) -> bool:
    data = await state.get_data()
    stack = list(data.get("_back_stack", []))
    if not stack:
        return False
    snapshot = stack.pop()
    restored = dict(snapshot["data"])
    restored["_back_stack"] = stack
    await state.set_data(restored)
    await state.set_state(snapshot["state"])
    return True


@router.message(Command("back"))
async def back_command(message: Message, state: FSMContext) -> None:
    if await _go_back(state):
        await message.answer(
            "⬅️ Вернулись к предыдущему шагу. Введите новое значение или выберите "
            "вариант на предыдущей клавиатуре."
        )
    else:
        await message.answer("Предыдущего шага нет. Начать расчёт: /new")


@router.callback_query(F.data == "nav:back")
async def back_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if await _go_back(state):
        await callback.message.answer(
            "⬅️ Вернулись к предыдущему шагу. Измените ответ на предыдущей клавиатуре."
        )
        await callback.answer()
    else:
        await callback.answer("Предыдущего шага нет", show_alert=True)


@router.callback_query(F.data == "nav:cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Расчёт отменён. Чтобы начать заново: /new")
    await callback.answer()


@router.callback_query(Survey.building_type, F.data.startswith("type:"))
async def building_type(callback: CallbackQuery, state: FSMContext) -> None:
    kind = callback.data.split(":", 1)[1]
    if kind not in {"apartment", "house"}:
        await callback.answer("Неизвестный тип объекта", show_alert=True)
        return
    await state.update_data(building_type=kind)
    if kind == "apartment":
        await state.set_state(Survey.apartment_position)
        await callback.message.answer(
            "Где расположена квартира? Перекрытия с отапливаемыми соседями "
            "будут автоматически исключены.",
            reply_markup=keyboard(
                [
                    ("Средний этаж", "position:middle"),
                    ("Первый этаж", "position:first"),
                    ("Последний этаж", "position:last"),
                    ("Первый и последний", "position:first_last"),
                ],
                1,
            ),
        )
        await callback.answer()
        return
    await state.update_data(apartment_position=None)
    await _ask_climate(callback.message, state)
    await callback.answer()


async def _ask_climate(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.climate)
    items = [(profile.name, f"climate:{key}") for key, profile in CLIMATES.items()]
    items.extend(
        [
            ("Другой город (полный профиль)", "climate:custom"),
            ("Только температура вручную", "climate:manual"),
        ]
    )
    await message.answer("Шаг 2/9 — климат. Выберите профиль:", reply_markup=keyboard(items, 1))


@router.callback_query(Survey.apartment_position, F.data.startswith("position:"))
async def apartment_position(callback: CallbackQuery, state: FSMContext) -> None:
    position = callback.data.split(":", 1)[1]
    if position not in {"middle", "first", "last", "first_last"}:
        await callback.answer("Неизвестное положение квартиры", show_alert=True)
        return
    await state.update_data(apartment_position=position)
    await _ask_climate(callback.message, state)
    await callback.answer()


@router.callback_query(Survey.climate, F.data.startswith("climate:"))
async def climate(callback: CallbackQuery, state: FSMContext) -> None:
    climate_key = callback.data.split(":", 1)[1]
    if climate_key not in {*CLIMATES, "manual", "custom"}:
        await callback.answer("Неизвестный климат", show_alert=True)
        return
    await state.update_data(climate_key=climate_key)
    if climate_key == "manual":
        await state.set_state(Survey.custom_outdoor)
        await callback.message.answer(
            "Введите расчётную наружную температуру зимой, °C (например -18):"
        )
    elif climate_key == "custom":
        await state.set_state(Survey.custom_city_name)
        await callback.message.answer("Название города или населённого пункта:")
    else:
        profile = CLIMATES[climate_key]
        await _ask_scenario(callback.message, state, profile)
    await callback.answer()


async def _ask_scenario(message: Message, state: FSMContext, profile: "ClimateProfile") -> None:
    await state.set_state(Survey.scenario)
    await message.answer(
        f"Шаг 2/9 — климат. {profile.name}: выберите режим расчёта.\n"
        f"Средний холодный месяц {profile.cold_month_mean_c:g} °C; "
        f"расчётный мороз {profile.design_c:g} °C; "
        f"наблюдавшийся экстремум {profile.observed_extreme_c:g} °C.\n"
        f"Для справки о лете: средний жаркий месяц {profile.hot_month_mean_c:g} °C, "
        f"абсолютный максимум {profile.observed_maximum_c:g} °C. "
        "Летние значения в нагрузку отопления не входят.\n"
        "Климатический резерв — стресс-сценарий на 2 °C холоднее расчётного, "
        "а не прогноз конкретной погоды.",
        reply_markup=keyboard(
            [
                ("Обычная зима", "scenario:economy"),
                ("Расчётный мороз", "scenario:design"),
                ("Экстремум", "scenario:extreme"),
                ("Климатический резерв", "scenario:future"),
            ],
            1,
        ),
    )


@router.callback_query(Survey.scenario, F.data.startswith("scenario:"))
async def scenario(callback: CallbackQuery, state: FSMContext) -> None:
    scenario_key = callback.data.split(":", 1)[1]
    data = await state.get_data()
    profile = climate_from_answers(data)
    if profile is None:
        await callback.answer("Климатический профиль не найден", show_alert=True)
        return
    try:
        outdoor = profile.outdoor_temperature(scenario_key)
    except ValueError:
        await callback.answer("Неизвестный климатический сценарий", show_alert=True)
        return
    await state.update_data(scenario=scenario_key, outdoor=outdoor)
    await state.set_state(Survey.indoor)
    await callback.message.answer(
        f"Шаг 3/9 — температура. Снаружи {outdoor:g} °C. "
        "Какая температура нужна внутри, °C? Например 24"
    )
    await callback.answer()


@router.message(Survey.custom_outdoor)
async def custom_outdoor(message: Message, state: FSMContext) -> None:
    try:
        outdoor = _temperature(message.text)
        if outdoor > 15:
            raise ValueError("для отопления ожидается температура не выше +15 °C")
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(outdoor=outdoor, scenario="manual")
    await state.set_state(Survey.indoor)
    await message.answer("Шаг 3/9 — температура внутри, °C. Например 24:")


@router.message(Survey.custom_city_name)
async def custom_city_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not 2 <= len(name) <= 80:
        await _error(message, ValueError("название должно содержать от 2 до 80 символов"))
        return
    await state.update_data(custom_city_name=name)
    await state.set_state(Survey.custom_cold_mean)
    await message.answer("Средняя температура самого холодного месяца, °C:")


@router.message(Survey.custom_cold_mean)
async def custom_cold_mean(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(custom_cold_mean=value)
    await state.set_state(Survey.custom_design)
    await message.answer("Расчётная зимняя температура для отопления, °C:")


@router.message(Survey.custom_design)
async def custom_design(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
        data = await state.get_data()
        if value >= data["custom_cold_mean"]:
            raise ValueError("расчётный мороз должен быть холоднее среднемесячной температуры")
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(custom_design=value)
    await state.set_state(Survey.custom_extreme)
    await message.answer("Абсолютный наблюдавшийся минимум, °C:")


@router.message(Survey.custom_extreme)
async def custom_extreme(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
        data = await state.get_data()
        if value > data["custom_design"]:
            raise ValueError("рекордный минимум не может быть теплее расчётного мороза")
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(custom_extreme=value)
    await state.set_state(Survey.custom_hot_mean)
    await message.answer("Средняя температура самого жаркого месяца, °C:")


@router.message(Survey.custom_hot_mean)
async def custom_hot_mean(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(custom_hot_mean=value)
    await state.set_state(Survey.custom_hot_max)
    await message.answer("Абсолютный наблюдавшийся максимум, °C:")


@router.message(Survey.custom_hot_max)
async def custom_hot_max(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
        data = await state.get_data()
        if value < data["custom_hot_mean"]:
            raise ValueError("абсолютный максимум не может быть ниже среднего жаркого месяца")
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(custom_hot_max=value)
    data = await state.get_data()
    profile = climate_from_answers(data)
    if profile is None:  # Defensive guard for corrupted FSM data.
        await _error(message, ValueError("не удалось собрать климатический профиль"))
        return
    await _ask_scenario(message, state, profile)


@router.message(Survey.indoor)
async def indoor(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text)
        data = await state.get_data()
        if value <= data["outdoor"]:
            raise ValueError("внутренняя температура должна быть выше наружной")
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(indoor=value)
    await state.set_state(Survey.dimensions)
    await message.answer("Шаг 4/9 — геометрия. Введите длину, ширину и высоту, м: 10 8 3")


@router.message(Survey.dimensions)
async def dimensions(message: Message, state: FSMContext) -> None:
    try:
        length, width, height = parse_triplet(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(
        length=length, width=width, height=height, volume=length * width * height
    )
    await state.set_state(Survey.wall_method)
    await message.answer(
        "Шаг 4/9 — стены. Как задать только наружные холодные стены?",
        reply_markup=keyboard(
            [
                ("Общей площадью", "walls:area"),
                ("Размер каждой стены", "walls:dimensions"),
                ("Весь периметр", "walls:perimeter"),
                ("Разные конструкции", "walls:groups"),
            ],
            1,
        ),
    )


@router.callback_query(Survey.wall_method, F.data.startswith("walls:"))
async def wall_method(callback: CallbackQuery, state: FSMContext) -> None:
    method = callback.data.split(":", 1)[1]
    if method not in {"area", "dimensions", "groups", "perimeter"}:
        await callback.answer("Неизвестный способ ввода стен", show_alert=True)
        return
    if method == "area":
        await state.set_state(Survey.wall_area)
        await callback.message.answer(
            "Введите общую площадь наружных стен до вычета окон и дверей, м²:"
        )
    elif method == "dimensions":
        await state.set_state(Survey.wall_dimensions)
        await callback.message.answer("Введите ширину×высоту каждой стены: 5x3, 4x3")
    elif method == "groups":
        await state.set_state(Survey.wall_groups)
        await callback.message.answer(
            "Каждая конструкция — с новой строки:\n"
            "Название | площадь или ширина×высота | материал | толщина см | "
            "утеплитель | толщина см\n\n"
            "Пример:\n"
            "Север | 10x3 | кирпич | 25 | минвата | 5\n"
            "Торец | 18 | газоблок | 30 | нет | 0\n\n"
            "Материалы: кирпич, пустотелый кирпич, газоблок, бетон, дерево. "
            "Утеплители: минвата, пенопласт, XPS, ППУ. Для паспортного материала "
            "введите вместо названия λ=0,12. Площади указываются до вычета окон."
        )
    else:
        data = await state.get_data()
        area = 2 * (data["length"] + data["width"]) * data["height"]
        await state.update_data(wall_gross_area=area)
        await _ask_wall_material(callback.message, state)
    await callback.answer()


@router.message(Survey.wall_area)
async def wall_area(message: Message, state: FSMContext) -> None:
    try:
        area = parse_number(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(wall_gross_area=area)
    await _ask_wall_material(message, state)


@router.message(Survey.wall_dimensions)
async def wall_dimensions(message: Message, state: FSMContext) -> None:
    try:
        area = sum(width * height for width, height in parse_dimensions(message.text))
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(wall_gross_area=area)
    await _ask_wall_material(message, state)


@router.message(Survey.wall_groups)
async def wall_groups(message: Message, state: FSMContext) -> None:
    try:
        groups = parse_wall_groups(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(
        wall_groups=groups,
        wall_gross_area=sum(item["gross_area_m2"] for item in groups),
        wall_material=None,
        wall_thickness=0.0,
        insulation_material=None,
        insulation_thickness=0.0,
    )
    await _ask_windows(message, state)


@router.callback_query(Survey.wall_material, F.data.startswith("mat:"))
async def wall_material(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    if key == "custom":
        await state.set_state(Survey.wall_custom_lambda)
        await callback.message.answer("Паспортная теплопроводность материала λ, Вт/(м·К):")
        await callback.answer()
        return
    if key not in MATERIALS:
        await callback.answer("Неизвестный материал", show_alert=True)
        return
    await state.update_data(wall_material=key)
    await state.set_state(Survey.wall_thickness)
    await callback.message.answer(
        f"Толщина слоя «{MATERIALS[key].name}» в сантиметрах, например 25:"
    )
    await callback.answer()


@router.message(Survey.wall_custom_lambda)
async def wall_custom_lambda(message: Message, state: FSMContext) -> None:
    try:
        value = _conductivity(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(wall_material="custom", wall_conductivity=value)
    await state.set_state(Survey.wall_thickness)
    await message.answer("Толщина этого материала в сантиметрах:")


@router.message(Survey.wall_thickness)
async def wall_thickness(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(wall_thickness=value / 100)
    await state.set_state(Survey.insulated)
    await message.answer(
        "Стена утеплена?", reply_markup=keyboard([("Да", "ins:yes"), ("Нет", "ins:no")])
    )


@router.callback_query(Survey.insulated, F.data.startswith("ins:"))
async def insulated(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.data not in {"ins:yes", "ins:no"}:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return
    if callback.data == "ins:no":
        await state.update_data(insulation_material=None, insulation_thickness=0.0)
        await _ask_windows(callback.message, state)
    else:
        await state.set_state(Survey.insulation_material)
        keys = ["mineral_wool", "eps", "xps", "pu_foam"]
        items = [(MATERIALS[key].name, f"imat:{key}") for key in keys]
        items.append(("Другой утеплитель — паспортная λ", "imat:custom"))
        await callback.message.answer(
            "Какой утеплитель?",
            reply_markup=keyboard(items, 1),
        )
    await callback.answer()


@router.callback_query(Survey.insulation_material, F.data.startswith("imat:"))
async def insulation_material(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    if key == "custom":
        await state.set_state(Survey.insulation_custom_lambda)
        await callback.message.answer("Паспортная теплопроводность утеплителя λ, Вт/(м·К):")
        await callback.answer()
        return
    if key not in {"mineral_wool", "eps", "xps", "pu_foam"}:
        await callback.answer("Неизвестный утеплитель", show_alert=True)
        return
    await state.update_data(insulation_material=key)
    await state.set_state(Survey.insulation_thickness)
    await callback.message.answer(f"Толщина «{MATERIALS[key].name}» в сантиметрах, например 5:")
    await callback.answer()


@router.message(Survey.insulation_custom_lambda)
async def insulation_custom_lambda(message: Message, state: FSMContext) -> None:
    try:
        value = _conductivity(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(
        insulation_material="custom",
        insulation_conductivity=value,
    )
    await state.set_state(Survey.insulation_thickness)
    await message.answer("Толщина этого утеплителя в сантиметрах:")


@router.message(Survey.insulation_thickness)
async def insulation_thickness(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(insulation_thickness=value / 100)
    await _ask_windows(message, state)


@router.message(Survey.window_count)
async def window_count(message: Message, state: FSMContext) -> None:
    try:
        count = _parse_count(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(window_count=count)
    if count == 0:
        await state.update_data(window_area=0.0, window_type="double")
        await _ask_doors(message, state)
        return
    await state.set_state(Survey.window_method)
    await message.answer(
        "Как задать окна?",
        reply_markup=keyboard(
            [
                ("Суммарной площадью", "window_method:area"),
                ("Размером одного окна", "window_method:dimensions"),
                ("Разные группы и U", "window_method:groups"),
            ],
            1,
        ),
    )


@router.callback_query(Survey.window_method, F.data.startswith("window_method:"))
async def window_method(callback: CallbackQuery, state: FSMContext) -> None:
    method = callback.data.split(":", 1)[1]
    if method not in {"area", "dimensions", "groups"}:
        await callback.answer("Неизвестный способ ввода окон", show_alert=True)
        return
    if method == "area":
        await state.set_state(Survey.window_area)
        await callback.message.answer("Суммарная площадь всех наружных окон, м²:")
    elif method == "dimensions":
        await state.set_state(Survey.window_dimensions)
        await callback.message.answer(
            "Ширина × высота одного типового окна в метрах, например 1,4x1,5:"
        )
    else:
        await state.set_state(Survey.window_groups)
        await callback.message.answer(
            "Каждая группа окон — с новой строки:\n"
            "Название | количество | ширина×высота, м | паспортный U | "
            "название стены (необязательно)\n\n"
            "Пример:\n"
            "ПВХ север | 3 | 1,4x1,5 | 1,1 | Север\n"
            "Окно кухни | 1 | 1,2x1,4 | 1,6 | Торец\n\n"
            "Название стены должно совпадать с расширенным списком стен. "
            "Если его не указать, площадь распределится пропорционально."
        )
    await callback.answer()


async def _accept_window_area(message: Message, state: FSMContext, area: float) -> None:
    data = await state.get_data()
    if area <= 0:
        raise ValueError("площадь окон должна быть больше нуля")
    if area > data["wall_gross_area"]:
        raise ValueError("площадь окон больше площади стен")
    await state.update_data(window_area=area)
    await state.set_state(Survey.window_type)
    await message.answer(
        "Тип окон:",
        reply_markup=keyboard([(item.name, f"window:{key}") for key, item in WINDOWS.items()], 1),
    )


@router.message(Survey.window_area)
async def window_area(message: Message, state: FSMContext) -> None:
    try:
        await _accept_window_area(message, state, _nonnegative(message.text))
    except ValueError as exc:
        await _error(message, exc)


@router.message(Survey.window_dimensions)
async def window_dimensions(message: Message, state: FSMContext) -> None:
    try:
        dimensions = parse_dimensions(message.text)
        if len(dimensions) != 1:
            raise ValueError("укажите размер одного типового окна")
        data = await state.get_data()
        area = dimensions[0][0] * dimensions[0][1] * data["window_count"]
        await _accept_window_area(message, state, area)
    except ValueError as exc:
        await _error(message, exc)


@router.message(Survey.window_groups)
async def window_groups(message: Message, state: FSMContext) -> None:
    try:
        groups = parse_window_groups(message.text)
        data = await state.get_data()
        if sum(group["count"] for group in groups) != data["window_count"]:
            raise ValueError("сумма количества в группах не совпадает с указанным числом окон")
        area = sum(group["area_m2"] for group in groups)
        if area > data["wall_gross_area"]:
            raise ValueError("площадь окон больше площади стен")
        wall_groups_data = data.get("wall_groups") or []
        known_walls = {group["name"].casefold(): group["name"] for group in wall_groups_data}
        gross_by_wall = {group["name"]: group["gross_area_m2"] for group in wall_groups_data}
        assigned_by_wall: dict[str, float] = {}
        for group in groups:
            if group["wall_name"]:
                canonical = known_walls.get(group["wall_name"].casefold())
                if canonical is None:
                    raise ValueError(
                        f"для группы «{group['name']}» не найдена стена «{group['wall_name']}»"
                    )
                group["wall_name"] = canonical
                assigned_by_wall[canonical] = (
                    assigned_by_wall.get(canonical, 0.0) + group["area_m2"]
                )
        for wall_name, assigned_area in assigned_by_wall.items():
            if assigned_area > gross_by_wall[wall_name]:
                raise ValueError(f"окна на стене «{wall_name}» больше площади этой стены")
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(window_groups=groups, window_area=area, window_type=None)
    await _ask_doors(message, state)


@router.callback_query(Survey.window_type, F.data.startswith("window:"))
async def window_type(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    if key not in WINDOWS:
        await callback.answer("Неизвестный тип окна", show_alert=True)
        return
    await state.update_data(window_type=key)
    await _ask_doors(callback.message, state)
    await callback.answer()


@router.message(Survey.door_count)
async def door_count(message: Message, state: FSMContext) -> None:
    try:
        count = _parse_count(message.text)
        if count > 100:
            raise ValueError("количество дверей должно быть от 0 до 100")
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(door_count=count)
    if count == 0:
        await state.update_data(door_area=0.0, door_groups=[], door_u_value=None)
        await _advance_after_openings(message, state)
        return
    await state.set_state(Survey.door_method)
    await message.answer(
        "Как задать наружные двери?",
        reply_markup=keyboard(
            [
                ("Суммарной площадью", "door_method:area"),
                ("Размером одной двери", "door_method:dimensions"),
                ("Разные группы и U", "door_method:groups"),
            ],
            1,
        ),
    )


@router.callback_query(Survey.door_method, F.data.startswith("door_method:"))
async def door_method(callback: CallbackQuery, state: FSMContext) -> None:
    method = callback.data.split(":", 1)[1]
    if method == "area":
        await state.set_state(Survey.door_area)
        await callback.message.answer("Суммарная площадь наружных дверей, м²:")
    elif method == "dimensions":
        await state.set_state(Survey.door_dimensions)
        await callback.message.answer(
            "Ширина × высота одной типовой двери в метрах, например 0,9x2,1:"
        )
    elif method == "groups":
        await state.set_state(Survey.door_groups)
        await callback.message.answer(
            "Каждая группа дверей — с новой строки:\n"
            "Название | количество | ширина×высота, м | паспортный U | стена (необязательно)\n\n"
            "Пример:\nВходная | 1 | 0,9x2,1 | 1,4 | Север"
        )
    else:
        await callback.answer("Неизвестный способ ввода", show_alert=True)
        return
    await callback.answer()


async def _ask_door_type(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.door_type)
    items = [(item.name, f"door_type:{key}") for key, item in DOORS.items()]
    await message.answer(
        "Тип двери (справочное U; паспортное значение задаётся через группы):",
        reply_markup=keyboard(items, 1),
    )


@router.message(Survey.door_area)
async def door_area(message: Message, state: FSMContext) -> None:
    try:
        area = _nonnegative(message.text)
        data = await state.get_data()
        if area <= 0:
            raise ValueError("площадь дверей должна быть больше нуля")
        if area + data["window_area"] > data["wall_gross_area"]:
            raise ValueError("окна и двери больше площади стен")
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(door_area=area, door_groups=[])
    await _ask_door_type(message, state)


@router.message(Survey.door_dimensions)
async def door_dimensions(message: Message, state: FSMContext) -> None:
    try:
        dimensions = parse_dimensions(message.text)
        if len(dimensions) != 1:
            raise ValueError("укажите размер одной типовой двери")
        data = await state.get_data()
        area = dimensions[0][0] * dimensions[0][1] * data["door_count"]
        if area + data["window_area"] > data["wall_gross_area"]:
            raise ValueError("окна и двери больше площади стен")
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(door_area=area, door_groups=[])
    await _ask_door_type(message, state)


@router.message(Survey.door_groups)
async def door_groups(message: Message, state: FSMContext) -> None:
    try:
        groups = parse_door_groups(message.text)
        data = await state.get_data()
        if sum(group["count"] for group in groups) != data["door_count"]:
            raise ValueError("сумма количества в группах не совпадает с числом дверей")
        area = sum(group["area_m2"] for group in groups)
        if area + data["window_area"] > data["wall_gross_area"]:
            raise ValueError("окна и двери больше площади стен")
        known_walls = {
            group["name"].casefold(): group["name"] for group in (data.get("wall_groups") or [])
        }
        gross_by_wall = {
            group["name"]: group["gross_area_m2"] for group in (data.get("wall_groups") or [])
        }
        assigned: dict[str, float] = {}
        for group in groups:
            if group["wall_name"]:
                canonical = known_walls.get(group["wall_name"].casefold())
                if canonical is None:
                    raise ValueError(f"не найдена стена «{group['wall_name']}»")
                group["wall_name"] = canonical
                assigned[canonical] = assigned.get(canonical, 0) + group["area_m2"]
        window_assigned: dict[str, float] = {}
        for group in data.get("window_groups") or []:
            if group.get("wall_name"):
                wall = group["wall_name"]
                window_assigned[wall] = window_assigned.get(wall, 0) + group["area_m2"]
        for wall, door_area_on_wall in assigned.items():
            if door_area_on_wall + window_assigned.get(wall, 0) > gross_by_wall[wall]:
                raise ValueError(f"окна и двери на стене «{wall}» больше её площади")
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(door_groups=groups, door_area=area, door_u_value=None)
    await _advance_after_openings(message, state)


@router.callback_query(Survey.door_type, F.data.startswith("door_type:"))
async def door_type(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    if key not in DOORS:
        await callback.answer("Неизвестный тип двери", show_alert=True)
        return
    await state.update_data(door_u_value=DOORS[key].u_value)
    await _advance_after_openings(callback.message, state)
    await callback.answer()


async def _advance_after_openings(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    position = data.get("apartment_position")
    advanced = data.get("calculation_mode") == "advanced"
    if position == "middle":
        await state.update_data(floor_boundary="heated", ceiling_boundary="heated")
        if advanced:
            await _ask_heated_neighbor_mode(message, state, "floor")
            return
        await _ask_air_changes(message, state)
        return
    if position == "last":
        await state.update_data(floor_boundary="heated")
        if advanced:
            await _ask_heated_neighbor_mode(message, state, "floor")
            return
        await _ask_ceiling(message, state)
        return
    if position == "first":
        await state.update_data(ceiling_boundary="heated")
    await state.set_state(Survey.floor_boundary)
    await message.answer(
        "Шаг 6/9 — пол и потолок. Что находится под полом?",
        reply_markup=keyboard(
            [
                ("Отапливаемый сосед", "floor:heated"),
                ("Холодный подвал", "floor:unheated"),
                ("Грунт", "floor:ground"),
                ("Наружный воздух", "floor:outdoor"),
            ],
            1,
        ),
    )


@router.callback_query(Survey.floor_boundary, F.data.startswith("floor:"))
async def floor_boundary(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    if value not in {item.value for item in Boundary}:
        await callback.answer("Неизвестное условие под полом", show_alert=True)
        return
    await state.update_data(floor_boundary=value)
    if value == "heated":
        await _ask_heated_neighbor_mode(callback.message, state, "floor")
    elif value in {"unheated", "ground"}:
        await _ask_adjacent_mode(callback.message, state, "floor", value)
    else:
        await _ask_surface_material(callback.message, state, "floor")
    await callback.answer()


async def _ask_ceiling(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("ceiling_boundary") == "heated":
        if data.get("calculation_mode") == "advanced" and not data.get("ceiling_neighbor_done"):
            await _ask_heated_neighbor_mode(message, state, "ceiling")
            return
        await _ask_air_changes(message, state)
        return
    await state.set_state(Survey.ceiling_boundary)
    await message.answer(
        "Шаг 6/9 — пол и потолок. Что находится над потолком?",
        reply_markup=keyboard(
            [
                ("Отапливаемый сосед", "ceiling:heated"),
                ("Холодный чердак", "ceiling:unheated"),
                ("Наружный воздух / кровля", "ceiling:outdoor"),
            ],
            1,
        ),
    )


@router.callback_query(Survey.ceiling_boundary, F.data.startswith("ceiling:"))
async def ceiling_boundary(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    if value not in {"heated", "unheated", "outdoor"}:
        await callback.answer("Неизвестное условие над потолком", show_alert=True)
        return
    await state.update_data(ceiling_boundary=value)
    if value == "heated":
        await _ask_heated_neighbor_mode(callback.message, state, "ceiling")
    elif value == "unheated":
        await _ask_adjacent_mode(callback.message, state, "ceiling", value)
    else:
        await _ask_surface_material(callback.message, state, "ceiling")
    await callback.answer()


async def _ask_adjacent_mode(
    message: Message,
    state: FSMContext,
    surface: str,
    boundary: str,
) -> None:
    await state.update_data(active_surface=surface, active_boundary=boundary)
    await state.set_state(Survey.surface_adjacent_mode)
    zone = "подвала/грунта под полом" if surface == "floor" else "холодного чердака"
    estimate = "50% наружной ΔT" if boundary == "ground" else "70% наружной ΔT"
    choices = [
        ("Ввести температуру", f"adjacent:{surface}:manual"),
        (f"Оставить оценку {estimate}", f"adjacent:{surface}:estimate"),
    ]
    if surface == "floor" and boundary == "ground":
        choices.insert(0, ("Нормативные зоны ШНҚ", "adjacent:floor:zonal"))
    await message.answer(
        f"Температура {zone} известна? Точное значение лучше фиксированного коэффициента.",
        reply_markup=keyboard(choices, 1),
    )


async def _ask_heated_neighbor_mode(message: Message, state: FSMContext, surface: str) -> None:
    await state.update_data(active_surface=surface, active_boundary="heated")
    await state.set_state(Survey.surface_adjacent_mode)
    zone = "соседа снизу" if surface == "floor" else "соседа сверху"
    await message.answer(
        f"Температура {zone} такая же, как внутри объекта?",
        reply_markup=keyboard(
            [
                ("Такая же — потерь нет", f"adjacent:{surface}:same"),
                ("Ввести температуру соседа", f"adjacent:{surface}:manual"),
            ],
            1,
        ),
    )


async def _ask_ground_insulation(message: Message, state: FSMContext) -> None:
    await state.update_data(active_surface="floor")
    await state.set_state(Survey.surface_insulated)
    await message.answer(
        "Есть утепляющий слой пола с λ < 1,2 Вт/(м·К)? "
        "Основная бетонная плита в нормативный R зоны отдельно не добавляется.",
        reply_markup=keyboard([("Да", "sins:yes"), ("Нет", "sins:no")]),
    )


@router.callback_query(Survey.surface_adjacent_mode, F.data.startswith("adjacent:"))
async def surface_adjacent_mode(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        _, surface, mode = callback.data.split(":", 2)
    except ValueError:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    data = await state.get_data()
    if surface != data.get("active_surface"):
        await callback.answer("Устаревшая кнопка", show_alert=True)
        return
    allowed_modes = {"manual", "estimate"}
    if data.get("active_boundary") == "ground":
        allowed_modes.add("zonal")
    if data.get("active_boundary") == "heated":
        allowed_modes.add("same")
    if mode not in allowed_modes:
        await callback.answer("Неизвестный режим смежной зоны", show_alert=True)
        return
    if mode == "same" and data.get("active_boundary") == "heated":
        await state.update_data(
            **{
                f"{surface}_adjacent_temperature": None,
                f"{surface}_neighbor_done": True,
            }
        )
        await _finish_surface(callback.message, state, surface)
    elif mode == "manual":
        if surface == "floor":
            await state.update_data(floor_ground_method="temperature")
        await state.set_state(Survey.surface_adjacent_temperature)
        await callback.message.answer(
            "Расчётная температура смежной зоны, °C. Например, для подвала +5:"
        )
    else:
        if surface == "floor":
            method = "zonal" if mode == "zonal" else "factor"
            await state.update_data(floor_ground_method=method)
        await state.update_data(**{f"{surface}_adjacent_temperature": None})
        if mode == "zonal" and surface == "floor":
            await _ask_ground_insulation(callback.message, state)
        else:
            await _ask_surface_material(callback.message, state, surface)
    await callback.answer()


@router.message(Survey.surface_adjacent_temperature)
async def surface_adjacent_temperature(message: Message, state: FSMContext) -> None:
    try:
        value = _temperature(message.text)
        data = await state.get_data()
        if value >= data["indoor"]:
            raise ValueError("температура смежной зоны должна быть ниже температуры внутри")
    except ValueError as exc:
        await _error(message, exc)
        return
    surface = data["active_surface"]
    await state.update_data(
        **{
            f"{surface}_adjacent_temperature": value,
            f"{surface}_neighbor_done": data.get("active_boundary") == "heated",
        }
    )
    await _ask_surface_material(message, state, surface)


async def _ask_surface_material(message: Message, state: FSMContext, surface: str) -> None:
    await state.update_data(active_surface=surface)
    await state.set_state(Survey.surface_material)
    title = "пола" if surface == "floor" else "перекрытия/крыши"
    keys = ["concrete", "brick_solid", "aerated_d500", "wood"]
    items = [(MATERIALS[key].name, f"smat:{key}") for key in keys]
    items.append(("Другой материал — паспортная λ", "smat:custom"))
    await message.answer(
        f"Основной материал {title}:",
        reply_markup=keyboard(items, 1),
    )


@router.callback_query(Survey.surface_material, F.data.startswith("smat:"))
async def surface_material(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    surface = data["active_surface"]
    key = callback.data.split(":", 1)[1]
    if key == "custom":
        await state.set_state(Survey.surface_custom_lambda)
        await callback.message.answer("Паспортная теплопроводность материала λ, Вт/(м·К):")
        await callback.answer()
        return
    if key not in MATERIALS:
        await callback.answer("Неизвестный материал", show_alert=True)
        return
    await state.update_data(**{f"{surface}_material": key})
    await state.set_state(Survey.surface_thickness)
    await callback.message.answer(f"Толщина слоя «{MATERIALS[key].name}» в сантиметрах:")
    await callback.answer()


@router.message(Survey.surface_custom_lambda)
async def surface_custom_lambda(message: Message, state: FSMContext) -> None:
    try:
        value = _conductivity(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    data = await state.get_data()
    surface = data["active_surface"]
    await state.update_data(**{f"{surface}_material": "custom", f"{surface}_conductivity": value})
    await state.set_state(Survey.surface_thickness)
    await message.answer("Толщина этого материала в сантиметрах:")


@router.message(Survey.surface_thickness)
async def surface_thickness(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    data = await state.get_data()
    surface = data["active_surface"]
    await state.update_data(**{f"{surface}_thickness": value / 100})
    await state.set_state(Survey.surface_insulated)
    await message.answer(
        "Есть утепление?",
        reply_markup=keyboard([("Да", "sins:yes"), ("Нет", "sins:no")]),
    )


@router.callback_query(Survey.surface_insulated, F.data.startswith("sins:"))
async def surface_insulated(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.data not in {"sins:yes", "sins:no"}:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return
    data = await state.get_data()
    surface = data["active_surface"]
    if callback.data == "sins:no":
        await state.update_data(
            **{f"{surface}_insulation_material": None, f"{surface}_insulation_thickness": 0.0}
        )
        await _finish_surface(callback.message, state, surface)
    else:
        await state.set_state(Survey.surface_insulation_material)
        keys = ["mineral_wool", "eps", "xps", "pu_foam"]
        items = [(MATERIALS[key].name, f"simat:{key}") for key in keys]
        items.append(("Другой утеплитель — паспортная λ", "simat:custom"))
        await callback.message.answer(
            "Материал утепления:",
            reply_markup=keyboard(items, 1),
        )
    await callback.answer()


@router.callback_query(Survey.surface_insulation_material, F.data.startswith("simat:"))
async def surface_insulation_material(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    surface = data["active_surface"]
    key = callback.data.split(":", 1)[1]
    if key == "custom":
        await state.set_state(Survey.surface_insulation_custom_lambda)
        await callback.message.answer("Паспортная теплопроводность утеплителя λ, Вт/(м·К):")
        await callback.answer()
        return
    if key not in {"mineral_wool", "eps", "xps", "pu_foam"}:
        await callback.answer("Неизвестный утеплитель", show_alert=True)
        return
    await state.update_data(**{f"{surface}_insulation_material": key})
    await state.set_state(Survey.surface_insulation_thickness)
    await callback.message.answer(f"Толщина «{MATERIALS[key].name}» в сантиметрах:")
    await callback.answer()


@router.message(Survey.surface_insulation_custom_lambda)
async def surface_insulation_custom_lambda(message: Message, state: FSMContext) -> None:
    try:
        value = _conductivity(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    data = await state.get_data()
    surface = data["active_surface"]
    await state.update_data(
        **{
            f"{surface}_insulation_material": "custom",
            f"{surface}_insulation_conductivity": value,
        }
    )
    await state.set_state(Survey.surface_insulation_thickness)
    await message.answer("Толщина этого утеплителя в сантиметрах:")


@router.message(Survey.surface_insulation_thickness)
async def surface_insulation_thickness(message: Message, state: FSMContext) -> None:
    try:
        value = parse_number(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    data = await state.get_data()
    surface = data["active_surface"]
    await state.update_data(**{f"{surface}_insulation_thickness": value / 100})
    await _finish_surface(message, state, surface)


async def _finish_surface(message: Message, state: FSMContext, surface: str) -> None:
    if surface == "floor":
        await _ask_ceiling(message, state)
    else:
        await _ask_air_changes(message, state)


async def _ask_air_changes(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.air_changes)
    await message.answer(
        "Шаг 7/9 — вентиляция. Оцените воздухообмен: герметичное здание — 0,3; "
        "обычное — 0,5; "
        "старое/продуваемое — 0,8–1,0.",
        reply_markup=keyboard(
            [("0,3", "ach:0.3"), ("0,5", "ach:0.5"), ("0,8", "ach:0.8"), ("1,0", "ach:1.0")]
        ),
    )


@router.callback_query(Survey.air_changes, F.data.startswith("ach:"))
async def air_changes(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        ach = float(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Некорректный воздухообмен", show_alert=True)
        return
    if ach not in {0.3, 0.5, 0.8, 1.0}:
        await callback.answer("Неизвестный вариант воздухообмена", show_alert=True)
        return
    await state.update_data(air_changes=ach)
    await state.set_state(Survey.heat_recovery)
    await callback.message.answer(
        "Есть рекуперация тепла организованной вентиляции?",
        reply_markup=keyboard([("Нет", "recovery:no"), ("Да", "recovery:yes")], 2),
    )
    await callback.answer()


@router.callback_query(Survey.heat_recovery, F.data.startswith("recovery:"))
async def heat_recovery(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    if value == "no":
        await state.update_data(heat_recovery_efficiency=0.0)
        await _ask_thermal_bridges(callback.message, state)
    elif value == "yes":
        await state.set_state(Survey.heat_recovery_efficiency)
        await callback.message.answer("Паспортный КПД рекуператора, %. Например 70:")
    else:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return
    await callback.answer()


@router.message(Survey.heat_recovery_efficiency)
async def heat_recovery_efficiency(message: Message, state: FSMContext) -> None:
    try:
        efficiency = (
            parse_number(
                message.text,
                minimum=1,
                maximum=95,
                label="КПД рекуператора, %",
            )
            / 100
        )
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(heat_recovery_efficiency=efficiency)
    await _ask_thermal_bridges(message, state)


async def _ask_thermal_bridges(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.thermal_bridges)
    await message.answer(
        "Шаг 8/9 — мостики холода (стыки, углы, перемычки, балконы):",
        reply_markup=keyboard(
            [
                ("0% — рассчитаны отдельно", "bridges:0"),
                ("5% — хорошее исполнение", "bridges:0.05"),
                ("10% — обычное", "bridges:0.10"),
                ("15% — много слабых узлов", "bridges:0.15"),
                ("Точно: ψ × длина", "bridges:exact"),
            ],
            1,
        ),
    )


@router.callback_query(Survey.thermal_bridges, F.data.startswith("bridges:"))
async def thermal_bridges(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    value = callback.data.split(":", 1)[1]
    if value == "exact":
        await state.set_state(Survey.thermal_bridge_details)
        await callback.message.answer(
            "Каждый мостик — с новой строки:\n"
            "Название | длина, м | ψ, Вт/(м·К)\n\n"
            "Пример:\nБалконная плита | 4,5 | 0,35\nПеремычки | 8 | 0,12"
        )
        await callback.answer()
        return
    if value not in {"0", "0.05", "0.10", "0.15"}:
        await callback.answer("Неизвестная поправка", show_alert=True)
        return
    await state.update_data(
        thermal_bridge_factor=float(value),
        linear_thermal_bridges=[],
    )
    await _ask_safety_factor(callback.message, state)
    await callback.answer()


@router.message(Survey.thermal_bridge_details)
async def thermal_bridge_details(message: Message, state: FSMContext) -> None:
    try:
        bridges = parse_linear_thermal_bridges(message.text)
    except ValueError as exc:
        await _error(message, exc)
        return
    await state.update_data(
        thermal_bridge_factor=0.0,
        linear_thermal_bridges=bridges,
    )
    await _ask_safety_factor(message, state)


async def _ask_safety_factor(message: Message, state: FSMContext) -> None:
    await state.set_state(Survey.safety_factor)
    await message.answer(
        "Шаг 9/9 — эксплуатационный запас после всех рассчитанных потерь:",
        reply_markup=keyboard(
            [
                ("0%", "safety:1.0"),
                ("10% — обычно", "safety:1.10"),
                ("15%", "safety:1.15"),
                ("20%", "safety:1.20"),
            ],
            2,
        ),
    )


@router.callback_query(Survey.safety_factor, F.data.startswith("safety:"))
async def safety_factor(
    callback: CallbackQuery,
    state: FSMContext,
    repository: CalculationRepository,
) -> None:
    try:
        factor = float(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Некорректный коэффициент запаса", show_alert=True)
        return
    if factor not in {1.0, 1.10, 1.15, 1.20}:
        await callback.answer("Неизвестный коэффициент запаса", show_alert=True)
        return
    await state.update_data(safety_factor=factor)
    state_data = await state.get_data()
    data = {key: value for key, value in state_data.items() if not key.startswith("_")}
    try:
        bundle = calculate_from_answers(data)
    except InvalidCalculationData as exc:
        await callback.message.answer(
            f"⚠️ Не удалось завершить расчёт: {exc}. Запустите /new и проверьте исходные данные."
        )
        await callback.answer()
        return
    except Exception:
        logger.exception(
            "Unexpected calculation failure user_id=%s",
            callback.from_user.id,
        )
        await callback.message.answer(
            "Не удалось завершить расчёт из-за внутренней ошибки. "
            "Данные не сохранены; попробуйте /new или сообщите администратору."
        )
        await callback.answer()
        return

    try:
        calculation_id = await asyncio.to_thread(
            repository.save,
            callback.from_user.id,
            data,
            bundle.result.total_kw,
            bundle.result.recommended_kw,
            bundle.report,
        )
    except Exception:
        logger.exception("Database save failed user_id=%s", callback.from_user.id)
        await _send_long_message(
            callback.message,
            "⚠️ Расчёт выполнен, но не сохранён в истории.\n\n" + bundle.report,
        )
    else:
        await _send_long_message(
            callback.message,
            f"Расчёт №{calculation_id}\n\n{bundle.report}",
        )
    await callback.message.answer("Новый расчёт: /new")
    await state.clear()
    await callback.answer()


@router.errors()
async def global_error_handler(event: ErrorEvent) -> bool:
    update = event.update
    message = update.message
    callback = update.callback_query
    user = (message or callback).from_user if (message or callback) else None
    exception = event.exception
    logger.error(
        "Unhandled Telegram update error user_id=%s update_id=%s",
        getattr(user, "id", None),
        update.update_id,
        exc_info=(type(exception), exception, exception.__traceback__),
    )
    text = (
        "Не удалось обработать этот шаг. Данные расчёта могли сохраниться не полностью. "
        "Попробуйте ещё раз или начните заново командой /new."
    )
    try:
        if callback:
            await callback.answer("Внутренняя ошибка", show_alert=True)
            if callback.message:
                await callback.message.answer(text)
        elif message:
            await message.answer(text)
    except Exception:
        logger.exception("Failed to notify user about handler error")
    return True


async def run(settings: Settings | None = None) -> None:
    settings = settings or Settings.from_env()
    repository = CalculationRepository(settings.database_path)
    await asyncio.to_thread(repository.initialize)
    dispatcher = Dispatcher(repository=repository, settings=settings)
    access = AccessMiddleware(settings)
    navigation = NavigationMiddleware()
    dispatcher.message.outer_middleware(access)
    dispatcher.callback_query.outer_middleware(access)
    dispatcher.message.middleware(navigation)
    dispatcher.callback_query.middleware(navigation)
    dispatcher.include_router(router)
    await dispatcher.start_polling(
        Bot(settings.bot_token),
        allowed_updates=dispatcher.resolve_used_update_types(),
    )


def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(level=settings.logging_level)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
