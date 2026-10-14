"""Onboarding, localized main menu and button-driven calculation profiles."""

import asyncio
import math

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..i18n import translate as tr
from ..storage import CalculationProfile, CalculationRepository
from .common import product_identity

router = Router(name=__name__)


class ProfileFlow(StatesGroup):
    create_name = State()
    rename_name = State()
    copy_name = State()
    prepared_by = State()
    edit_indoor = State()
    edit_air = State()
    edit_safety = State()


def main_menu(locale: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr("menu.new", locale), callback_data="m:new")],
            [InlineKeyboardButton(text=tr("menu.history", locale), callback_data="m:history")],
            [InlineKeyboardButton(text=tr("menu.profiles", locale), callback_data="m:profiles")],
            [InlineKeyboardButton(text=tr("menu.language", locale), callback_data="m:language")],
            [InlineKeyboardButton(text=tr("menu.help", locale), callback_data="m:help")],
            [InlineKeyboardButton(text=tr("menu.privacy", locale), callback_data="m:privacy")],
        ]
    )


async def _locale(repository: CalculationRepository, user_id: int) -> str:
    settings = await asyncio.to_thread(repository.get_user_settings, user_id)
    return settings.locale


async def show_main_menu(message: Message, repository: CalculationRepository) -> None:
    locale = await _locale(repository, message.from_user.id)
    await message.answer(
        f"{tr('menu.title', locale)}\n\n{tr('menu.subtitle', locale)}",
        reply_markup=main_menu(locale),
    )


@router.message(CommandStart())
@router.message(Command("menu"))
async def start_menu(
    message: Message, state: FSMContext, repository: CalculationRepository
) -> None:
    await state.clear()
    await show_main_menu(message, repository)


@router.callback_query(F.data == "m:home")
async def home_callback(
    callback: CallbackQuery, state: FSMContext, repository: CalculationRepository
) -> None:
    await state.clear()
    await show_main_menu(callback.message, repository)
    await callback.answer()


@router.callback_query(F.data == "m:new")
async def new_calculation(
    callback: CallbackQuery,
    state: FSMContext,
    repository: CalculationRepository,
) -> None:
    from .survey import start

    await start(callback.message, state, repository)
    await callback.answer()


@router.callback_query(F.data == "m:language")
async def language_menu(callback: CallbackQuery, repository: CalculationRepository) -> None:
    locale = await _locale(repository, callback.from_user.id)
    await callback.message.answer(
        tr("language.title", locale),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Русский", callback_data="lang:ru")],
                [InlineKeyboardButton(text="O‘zbekcha", callback_data="lang:uz")],
                [InlineKeyboardButton(text=tr("common.back", locale), callback_data="m:home")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lang:"))
async def language_save(callback: CallbackQuery, repository: CalculationRepository) -> None:
    locale = callback.data.split(":", 1)[1]
    if locale not in {"ru", "uz"}:
        await callback.answer("Unknown language", show_alert=True)
        return
    await asyncio.to_thread(repository.set_locale, callback.from_user.id, locale)
    await callback.message.answer(tr("language.saved", locale), reply_markup=main_menu(locale))
    await callback.answer()


@router.callback_query(F.data == "m:help")
async def help_menu(callback: CallbackQuery, repository: CalculationRepository) -> None:
    locale = await _locale(repository, callback.from_user.id)
    await callback.message.answer(
        f"{tr('help.text', locale)}\n\n{product_identity(locale)}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=tr("menu.home", locale), callback_data="m:home")]
            ]
        ),
    )
    await callback.answer()


async def _send_privacy_prompt(message: Message, locale: str) -> None:
    await message.answer(
        tr("privacy.delete_prompt", locale),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=tr("privacy.delete_confirm", locale),
                        callback_data="privacy:delete_confirm",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=tr("common.cancel", locale),
                        callback_data="privacy:cancel",
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data == "m:privacy")
async def privacy_menu(callback: CallbackQuery, repository: CalculationRepository) -> None:
    locale = await _locale(repository, callback.from_user.id)
    await _send_privacy_prompt(callback.message, locale)
    await callback.answer()


@router.message(Command("delete_my_data"))
async def delete_my_data_command(message: Message, repository: CalculationRepository) -> None:
    await _send_privacy_prompt(message, await _locale(repository, message.from_user.id))


@router.callback_query(F.data.startswith("privacy:"))
async def privacy_action(
    callback: CallbackQuery,
    state: FSMContext,
    repository: CalculationRepository,
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await callback.message.answer(
            tr("privacy.delete_cancelled", locale), reply_markup=main_menu(locale)
        )
    elif action == "delete_confirm":
        deleted = await asyncio.to_thread(
            repository.delete_all_user_data, callback.from_user.id
        )
        await state.clear()
        await callback.message.answer(
            tr(
                "privacy.deleted",
                locale,
                calculations=deleted.calculations,
                profiles=deleted.profiles,
                drafts=deleted.drafts,
            )
        )
    else:
        await callback.answer(tr("common.invalid_option", locale), show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data == "m:history")
async def history_menu(callback: CallbackQuery, repository: CalculationRepository) -> None:
    locale = await _locale(repository, callback.from_user.id)
    records = await asyncio.to_thread(repository.recent, callback.from_user.id, 10)
    if records:
        lines = [tr("menu.history", locale)]
        lines.extend(
            f"• №{item.id} · {item.object_name} · {item.recommended_kw:.2f} kW" for item in records
        )
    else:
        lines = [tr("history.empty", locale)]
    history_rows = [
        [
            InlineKeyboardButton(
                text=tr("history.open", locale, id=item.id, name=item.object_name[:32]),
                callback_data=f"h:view:{item.id}",
            )
        ]
        for item in records
    ]
    await callback.message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=history_rows
            + [
                [InlineKeyboardButton(text=tr("menu.new", locale), callback_data="m:new")],
                [InlineKeyboardButton(text=tr("menu.home", locale), callback_data="m:home")],
            ]
        ),
    )
    await callback.answer()


def _profiles_keyboard(profiles: list[CalculationProfile], locale: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=("⭐ " if profile.is_default else "") + profile.name,
                callback_data=f"p:view:{profile.id}",
            )
        ]
        for profile in profiles
    ]
    rows.extend(
        [
            [InlineKeyboardButton(text=tr("profiles.create", locale), callback_data="p:create")],
            [
                InlineKeyboardButton(
                    text=tr("profiles.prepared_by", locale),
                    callback_data="p:prepared_by",
                )
            ],
            [InlineKeyboardButton(text=tr("menu.home", locale), callback_data="m:home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_profiles(message: Message, repository: CalculationRepository, user_id: int) -> None:
    locale = await _locale(repository, user_id)
    profiles = await asyncio.to_thread(repository.list_profiles, user_id)
    suffix = "" if profiles else f"\n\n{tr('profiles.empty', locale)}"
    await message.answer(
        tr("profiles.title", locale) + suffix,
        reply_markup=_profiles_keyboard(profiles, locale),
    )


@router.message(Command("profiles"))
async def profiles_command(message: Message, repository: CalculationRepository) -> None:
    await _show_profiles(message, repository, message.from_user.id)


@router.callback_query(F.data == "m:profiles")
async def profiles_menu(callback: CallbackQuery, repository: CalculationRepository) -> None:
    await _show_profiles(callback.message, repository, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "p:prepared_by")
async def prepared_by_start(
    callback: CallbackQuery,
    state: FSMContext,
    repository: CalculationRepository,
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    await state.set_state(ProfileFlow.prepared_by)
    await callback.message.answer(tr("profiles.prepared_by_ask", locale))
    await callback.answer()


@router.message(ProfileFlow.prepared_by)
async def prepared_by_save(
    message: Message,
    state: FSMContext,
    repository: CalculationRepository,
) -> None:
    locale = await _locale(repository, message.from_user.id)
    value = (message.text or "").strip()
    if value == "-":
        value = ""
    try:
        await asyncio.to_thread(repository.set_prepared_by, message.from_user.id, value)
    except ValueError as exc:
        await message.answer(tr("common.error", locale, message=str(exc)))
        return
    await state.clear()
    key = "profiles.prepared_by_saved" if value else "profiles.prepared_by_cleared"
    await message.answer(tr(key, locale, name=value))
    await _show_profiles(message, repository, message.from_user.id)


@router.callback_query(F.data == "p:create")
async def profile_create_start(
    callback: CallbackQuery, state: FSMContext, repository: CalculationRepository
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    await state.set_state(ProfileFlow.create_name)
    await callback.message.answer(tr("profiles.ask_name", locale))
    await callback.answer()


@router.message(ProfileFlow.create_name)
async def profile_create_name(
    message: Message, state: FSMContext, repository: CalculationRepository
) -> None:
    locale = await _locale(repository, message.from_user.id)
    try:
        profile = await asyncio.to_thread(
            repository.create_profile,
            message.from_user.id,
            message.text or "",
            {"indoor": 24.0, "air_changes": 0.5, "safety_factor": 1.10},
        )
    except ValueError as exc:
        await message.answer(tr("common.error", locale, message=str(exc)))
        return
    await state.clear()
    await message.answer(tr("profiles.created", locale, name=profile.name))
    await _show_profiles(message, repository, message.from_user.id)


@router.callback_query(F.data.startswith("p:view:"))
async def profile_view(callback: CallbackQuery, repository: CalculationRepository) -> None:
    locale = await _locale(repository, callback.from_user.id)
    profile_id = int(callback.data.rsplit(":", 1)[1])
    profile = await asyncio.to_thread(repository.get_profile, callback.from_user.id, profile_id)
    if profile is None:
        await callback.answer(tr("profiles.not_found", locale), show_alert=True)
        return
    marker = "⭐" if profile.is_default else "⚙️"
    indoor = float(profile.settings.get("indoor", 24.0))
    air_changes = float(profile.settings.get("air_changes", 0.5))
    safety = (float(profile.settings.get("safety_factor", 1.1)) - 1) * 100
    await callback.message.answer(
        f"{marker} {profile.name}\n"
        + tr(
            "profiles.summary",
            locale,
            indoor=f"{indoor:g}",
            air_changes=f"{air_changes:g}",
            safety=f"{safety:.0f}",
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=tr("profiles.settings", locale),
                        callback_data=f"p:settings:{profile.id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=tr("profiles.rename", locale),
                        callback_data=f"p:rename:{profile.id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=tr("profiles.copy", locale),
                        callback_data=f"p:copy:{profile.id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=tr("profiles.default", locale),
                        callback_data=f"p:default:{profile.id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=tr("profiles.delete", locale),
                        callback_data=f"p:delete:{profile.id}",
                    )
                ],
                [InlineKeyboardButton(text=tr("common.back", locale), callback_data="m:profiles")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("p:settings:"))
async def profile_settings_start(
    callback: CallbackQuery,
    state: FSMContext,
    repository: CalculationRepository,
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    profile_id = int(callback.data.rsplit(":", 1)[1])
    profile = await asyncio.to_thread(repository.get_profile, callback.from_user.id, profile_id)
    if profile is None:
        await callback.answer(tr("profiles.not_found", locale), show_alert=True)
        return
    await state.update_data(profile_id=profile_id)
    await state.set_state(ProfileFlow.edit_indoor)
    await callback.message.answer(tr("profiles.ask_indoor", locale))
    await callback.answer()


@router.message(ProfileFlow.edit_indoor)
async def profile_settings_indoor(
    message: Message,
    state: FSMContext,
    repository: CalculationRepository,
) -> None:
    locale = await _locale(repository, message.from_user.id)
    try:
        value = float((message.text or "").strip().replace(",", "."))
        if not math.isfinite(value) or not -30 <= value <= 50:
            raise ValueError
    except ValueError:
        await message.answer(
            tr("common.error", locale, message="Температура должна быть от -30 до +50 °C")
        )
        return
    await state.update_data(profile_indoor=value)
    await state.set_state(ProfileFlow.edit_air)
    await message.answer(
        tr("profiles.ask_air", locale),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="0,3", callback_data="pset:air:0.3"),
                    InlineKeyboardButton(text="0,5", callback_data="pset:air:0.5"),
                ],
                [
                    InlineKeyboardButton(text="0,8", callback_data="pset:air:0.8"),
                    InlineKeyboardButton(text="1,0", callback_data="pset:air:1.0"),
                ],
            ]
        ),
    )


@router.callback_query(ProfileFlow.edit_air, F.data.startswith("pset:air:"))
async def profile_settings_air(
    callback: CallbackQuery,
    state: FSMContext,
    repository: CalculationRepository,
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    try:
        value = float(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer(tr("common.stale", locale), show_alert=True)
        return
    if value not in {0.3, 0.5, 0.8, 1.0}:
        await callback.answer(tr("common.stale", locale), show_alert=True)
        return
    await state.update_data(profile_air_changes=value)
    await state.set_state(ProfileFlow.edit_safety)
    await callback.message.answer(
        tr("profiles.ask_safety", locale),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="0%", callback_data="pset:safety:1.0"),
                    InlineKeyboardButton(text="10%", callback_data="pset:safety:1.1"),
                ],
                [
                    InlineKeyboardButton(text="15%", callback_data="pset:safety:1.15"),
                    InlineKeyboardButton(text="20%", callback_data="pset:safety:1.2"),
                ],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(ProfileFlow.edit_safety, F.data.startswith("pset:safety:"))
async def profile_settings_safety(
    callback: CallbackQuery,
    state: FSMContext,
    repository: CalculationRepository,
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    try:
        factor = float(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer(tr("common.stale", locale), show_alert=True)
        return
    if factor not in {1.0, 1.1, 1.15, 1.2}:
        await callback.answer(tr("common.stale", locale), show_alert=True)
        return
    data = await state.get_data()
    saved = await asyncio.to_thread(
        repository.update_profile_settings,
        callback.from_user.id,
        int(data["profile_id"]),
        {
            "indoor": data["profile_indoor"],
            "air_changes": data["profile_air_changes"],
            "safety_factor": factor,
        },
    )
    await state.clear()
    await callback.message.answer(
        tr("profiles.settings_saved", locale) if saved else tr("profiles.not_found", locale)
    )
    await callback.answer()
    await _show_profiles(callback.message, repository, callback.from_user.id)


@router.callback_query(F.data.startswith("p:rename:"))
async def profile_rename_start(
    callback: CallbackQuery, state: FSMContext, repository: CalculationRepository
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    await state.update_data(profile_id=int(callback.data.rsplit(":", 1)[1]))
    await state.set_state(ProfileFlow.rename_name)
    await callback.message.answer(tr("profiles.ask_name", locale))
    await callback.answer()


@router.message(ProfileFlow.rename_name)
async def profile_rename_name(
    message: Message, state: FSMContext, repository: CalculationRepository
) -> None:
    locale = await _locale(repository, message.from_user.id)
    profile_id = int((await state.get_data())["profile_id"])
    try:
        renamed = await asyncio.to_thread(
            repository.rename_profile, message.from_user.id, profile_id, message.text or ""
        )
    except ValueError as exc:
        await message.answer(tr("common.error", locale, message=str(exc)))
        return
    await state.clear()
    await message.answer(
        tr("profiles.renamed", locale) if renamed else tr("profiles.not_found", locale)
    )
    await _show_profiles(message, repository, message.from_user.id)


@router.callback_query(F.data.startswith("p:copy:"))
async def profile_copy_start(
    callback: CallbackQuery, state: FSMContext, repository: CalculationRepository
) -> None:
    locale = await _locale(repository, callback.from_user.id)
    await state.update_data(profile_id=int(callback.data.rsplit(":", 1)[1]))
    await state.set_state(ProfileFlow.copy_name)
    await callback.message.answer(tr("profiles.ask_copy_name", locale))
    await callback.answer()


@router.message(ProfileFlow.copy_name)
async def profile_copy_name(
    message: Message, state: FSMContext, repository: CalculationRepository
) -> None:
    locale = await _locale(repository, message.from_user.id)
    profile_id = int((await state.get_data())["profile_id"])
    try:
        profile = await asyncio.to_thread(
            repository.duplicate_profile,
            message.from_user.id,
            profile_id,
            message.text or "",
        )
    except ValueError as exc:
        await message.answer(tr("common.error", locale, message=str(exc)))
        return
    await state.clear()
    if profile is None:
        await message.answer(tr("profiles.not_found", locale))
    else:
        await message.answer(tr("profiles.copied", locale, name=profile.name))
    await _show_profiles(message, repository, message.from_user.id)


@router.callback_query(F.data.startswith("p:default:"))
async def profile_default(callback: CallbackQuery, repository: CalculationRepository) -> None:
    locale = await _locale(repository, callback.from_user.id)
    profile_id = int(callback.data.rsplit(":", 1)[1])
    saved = await asyncio.to_thread(
        repository.set_default_profile, callback.from_user.id, profile_id
    )
    await callback.message.answer(
        tr("profiles.default_saved", locale) if saved else tr("profiles.not_found", locale)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("p:delete:"))
async def profile_delete_prompt(callback: CallbackQuery, repository: CalculationRepository) -> None:
    locale = await _locale(repository, callback.from_user.id)
    profile_id = int(callback.data.rsplit(":", 1)[1])
    profile = await asyncio.to_thread(repository.get_profile, callback.from_user.id, profile_id)
    if profile is None:
        await callback.answer(tr("profiles.not_found", locale), show_alert=True)
        return
    await callback.message.answer(
        tr("profiles.delete_confirm", locale, name=profile.name),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=tr("common.confirm_delete", locale),
                        callback_data=f"p:delete_ok:{profile.id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=tr("common.cancel", locale),
                        callback_data=f"p:view:{profile.id}",
                    )
                ],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("p:delete_ok:"))
async def profile_delete(callback: CallbackQuery, repository: CalculationRepository) -> None:
    locale = await _locale(repository, callback.from_user.id)
    profile_id = int(callback.data.rsplit(":", 1)[1])
    deleted = await asyncio.to_thread(repository.delete_profile, callback.from_user.id, profile_id)
    await callback.message.answer(
        tr("profiles.deleted", locale) if deleted else tr("profiles.not_found", locale)
    )
    await callback.answer()
    await _show_profiles(callback.message, repository, callback.from_user.id)
