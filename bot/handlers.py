"""Обработчики команд и callback_query."""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .feed import FeedClient
from .keyboards import CATEGORIES, MENU, SUBSCRIBE, UNSUBSCRIBE, decode_page
from .service import categories_view, list_view, menu_view
from .storage import Storage

log = logging.getLogger(__name__)


def create_router(feed: FeedClient, storage: Storage, tz: ZoneInfo) -> Router:
    """Создаёт роутер со всеми обработчиками бота."""
    router = Router(name="main_router")

    async def _safe_edit(call: CallbackQuery, text: str, markup) -> None:
        try:
            if call.message:
                await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except TelegramBadRequest as exc:
            # Игнорируем ошибку, если пользователь нажал на уже активную страницу/кнопку
            if "message is not modified" not in exc.message.lower():
                log.warning("failed to edit message: %s", exc)
        except TelegramRetryAfter:
            # Пользователь слишком быстро нажимает кнопки: Telegram просит паузу
            pass

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        subscribed = await storage.is_subscribed(message.chat.id)
        view = menu_view(subscribed)
        await message.answer(view.text, reply_markup=view.markup, parse_mode="HTML")

    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        subscribed = await storage.is_subscribed(message.chat.id)
        view = menu_view(subscribed)
        await message.answer(view.text, reply_markup=view.markup, parse_mode="HTML")

    @router.callback_query(F.data == MENU)
    async def on_menu(call: CallbackQuery) -> None:
        if call.message:
            subscribed = await storage.is_subscribed(call.message.chat.id)
            view = menu_view(subscribed)
            await _safe_edit(call, view.text, view.markup)
        await call.answer()

    @router.callback_query(F.data == SUBSCRIBE)
    async def on_subscribe(call: CallbackQuery) -> None:
        if call.message:
            await storage.subscribe(call.message.chat.id)
            view = menu_view(subscribed=True)
            await _safe_edit(call, view.text, view.markup)
        await call.answer("Вы подписались на ежедневный дайджест! 🔔")

    @router.callback_query(F.data == UNSUBSCRIBE)
    async def on_unsubscribe(call: CallbackQuery) -> None:
        if call.message:
            await storage.unsubscribe(call.message.chat.id)
            view = menu_view(subscribed=False)
            await _safe_edit(call, view.text, view.markup)
        await call.answer("Вы отписались от дайджеста. 🔕")

    @router.callback_query(F.data == CATEGORIES)
    async def on_categories(call: CallbackQuery) -> None:
        view = await categories_view(feed)
        await _safe_edit(call, view.text, view.markup)
        await call.answer()

    @router.callback_query(F.data.startswith("l:"))
    async def on_page(call: CallbackQuery) -> None:
        if not call.data:
            await call.answer()
            return
        decoded = decode_page(call.data)
        if decoded is None:
            await call.answer("Неверный запрос", show_alert=True)
            return
        scope, page = decoded
        today = datetime.now(tz).date()
        view = await list_view(feed, scope, page, today)
        await _safe_edit(call, view.text, view.markup)
        await call.answer()

    return router
