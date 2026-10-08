from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .i18n import translate as tr


def keyboard(
    items: list[tuple[str, str]],
    columns: int = 2,
    *,
    navigation: bool = True,
    locale: str = "ru",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(items), columns):
        page = items[index : index + columns]
        rows.append([InlineKeyboardButton(text=text, callback_data=data) for text, data in page])
    if navigation:
        rows.append(
            [
                InlineKeyboardButton(text=tr("common.back", locale), callback_data="nav:back"),
                InlineKeyboardButton(text=tr("common.cancel", locale), callback_data="nav:cancel"),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
