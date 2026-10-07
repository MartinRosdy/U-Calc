from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def keyboard(
    items: list[tuple[str, str]],
    columns: int = 2,
    *,
    navigation: bool = True,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(items), columns):
        page = items[index : index + columns]
        rows.append([InlineKeyboardButton(text=text, callback_data=data) for text, data in page])
    if navigation:
        rows.append(
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back"),
                InlineKeyboardButton(text="✖️ Отмена", callback_data="nav:cancel"),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
