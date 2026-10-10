"""Сборка экранов бота: текст + клавиатура. Не зависит от обработчиков aiogram, поэтому легко тестируется."""
import logging
from dataclasses import dataclass
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .feed import FeedClient, FeedUnavailable
from .keyboards import MENU, categories_kb, menu_kb, pager_kb, parse_scope
from .ordering import collect_categories, sort_for_display
from .render import WHEN_LABELS, render_page

log = logging.getLogger(__name__)

WELCOME_TEXT = "<b>Афиша событий</b>\n\nВыберите период или категорию. Бот показывает только события с сайта."
ERROR_TEXT = "Не удалось получить данные с сайта. Попробуйте чуть позже."
NO_CATEGORIES_TEXT = "Пока нет событий, по которым можно выбрать категорию."
PICK_CATEGORY_TEXT = "Выберите категорию:"


@dataclass(frozen=True)
class View:
    text: str
    markup: InlineKeyboardMarkup


def _menu_only_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Меню", callback_data=MENU)]])


def menu_view(subscribed: bool) -> View:
    return View(WELCOME_TEXT, menu_kb(subscribed))


async def list_view(feed: FeedClient, scope: str, page: int, today: date) -> View:
    parsed = parse_scope(scope)
    if parsed is None:  # через decode_page сюда не попасть, но проверка дешёвая
        return View(ERROR_TEXT, _menu_only_kb())
    when, category = parsed
    try:
        result = await feed.get_events(when=when, category=category)
    except FeedUnavailable as exc:
        log.warning("feed unavailable: %s", exc)
        return View(ERROR_TEXT, _menu_only_kb())

    events = sort_for_display(result.events, today)
    if when:
        title = WHEN_LABELS[when]
    else:
        title = events[0].category.label if events else "Категория"
    rendered = render_page(events, title=title, page=page, stale=result.stale, site_origin=feed.origin)
    return View(rendered.text, pager_kb(scope, rendered))


async def categories_view(feed: FeedClient) -> View:
    try:
        result = await feed.get_events()  # все ближайшие события: из них собираем список категорий
    except FeedUnavailable as exc:
        log.warning("feed unavailable: %s", exc)
        return View(ERROR_TEXT, _menu_only_kb())
    categories = collect_categories(result.events)
    if not categories:
        return View(NO_CATEGORIES_TEXT, _menu_only_kb())
    return View(PICK_CATEGORY_TEXT, categories_kb(categories))
