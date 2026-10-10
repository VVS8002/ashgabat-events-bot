"""Клавиатуры и коды callback_data. Лимит Telegram на callback_data: 64 байта."""
import re

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .feed import WHEN_VALUES
from .models import Category
from .render import WHEN_LABELS, Page

SLUG_RE = re.compile(r"^[a-z0-9_-]{1,40}$")  # данные из callback приходят от пользователя: не доверяем
MAX_CALLBACK_BYTES = 64

MENU = "menu"
CATEGORIES = "cats"
SUBSCRIBE = "sub"
UNSUBSCRIBE = "unsub"


def scope_when(when: str) -> str:
    return f"w.{when}"


def scope_category(slug: str) -> str:
    return f"c.{slug}"


def parse_scope(scope: str) -> tuple[str | None, str | None] | None:
    """'w.today' -> ('today', None); 'c.education' -> (None, 'education'); мусор -> None."""
    kind, _, value = scope.partition(".")
    if kind == "w" and value in WHEN_VALUES:
        return value, None
    if kind == "c" and SLUG_RE.match(value):
        return None, value
    return None


def encode_page(scope: str, page: int) -> str:
    data = f"l:{scope}:{page}"
    if len(data.encode()) > MAX_CALLBACK_BYTES:
     raise ValueError(f"callback_data too long for Telegram: {data!r}")
    return data


MAX_PAGE_NUMBER = 10_000


def decode_page(data: str) -> tuple[str, int] | None:
    if not isinstance(data, str):
        return None
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "l" or parse_scope(parts[1]) is None:
        return None
    try:
        page = int(parts[2])
    except ValueError:
        return None
    return (parts[1], page) if 0 <= page <= MAX_PAGE_NUMBER else None


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def menu_kb(subscribed: bool) -> InlineKeyboardMarkup:
    toggle = _btn("🔕 Отписаться от дайджеста", UNSUBSCRIBE) if subscribed else _btn("🔔 Подписаться на дайджест", SUBSCRIBE)
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(WHEN_LABELS["today"], encode_page(scope_when("today"), 0)),
         _btn(WHEN_LABELS["weekend"], encode_page(scope_when("weekend"), 0))],
        [_btn(WHEN_LABELS["week"], encode_page(scope_when("week"), 0)),
         _btn("🗂 Категории", CATEGORIES)],
        [toggle],
    ])


def categories_kb(categories: list[Category]) -> InlineKeyboardMarkup:
    buttons = [
        _btn(c.label, encode_page(scope_category(c.slug), 0))
        for c in categories if SLUG_RE.match(c.slug)  # такую категорию в callback не закодировать
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([_btn("🏠 Меню", MENU)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pager_kb(scope: str, page: Page) -> InlineKeyboardMarkup:
    nav = []
    if page.has_prev:
        nav.append(_btn("◀️ Назад", encode_page(scope, page.page - 1)))
    if page.has_next:
        nav.append(_btn("Далее ▶️", encode_page(scope, page.page + 1)))
    rows = ([nav] if nav else []) + [[_btn("🏠 Меню", MENU)]]
    return InlineKeyboardMarkup(inline_keyboard=rows)