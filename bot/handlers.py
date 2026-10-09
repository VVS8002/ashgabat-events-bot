"""Обработчики команд и кнопок."""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .feed import FeedClient
from .keyboards import CATEGORIES, MENU, SUBSCRIBE, UNSUBSCRIBE, decode_page
from .service import View, categories_view, list_view, menu_view
from .storage import Storage

log = logging.getLogger(__name__)

UNSUBSCRIBED_TEXT = "Вы отписались от ежедневной подборки. Вернуться можно через /start."
NOT_SUBSCRIBED_TEXT = "Вы и не были подписаны на ежедневную подборку."
SUBSCRIBED_TOAST = "Вы подписались на ежедневную подборку 🔔"
UNSUBSCRIBED_TOAST = "Вы отписались от подборки 🔕"
BAD_REQUEST_TOAST = "Неверный запрос"


def create_router(feed: FeedClient, storage: Storage, tz: ZoneInfo) -> Router:
    router = Router(name="main_router")

    def _chat_id(call: CallbackQuery) -> int | None:
        # И у Message, и у InaccessibleMessage есть .chat; None бывает только у inline-сообщений
        return call.message.chat.id if call.message else None

    async def _show(call: CallbackQuery, view: View) -> None:
        """Обновляет сообщение с кнопкой. Если оно недоступно (старше 48 часов, например старый
        дайджест), у него нет edit_text: присылаем экран новым сообщением."""
        if isinstance(call.message, Message):
            try:
                await call.message.edit_text(view.text, reply_markup=view.markup)
            except TelegramBadRequest as exc:
                if "message is not modified" not in exc.message.lower():
                    log.warning("failed to edit message: %s", exc.message)
            except TelegramRetryAfter:
                log.info("edit skipped: flood control")
            return
        chat_id = _chat_id(call)
        if chat_id is not None:
            await call.bot.send_message(chat_id, view.text, reply_markup=view.markup)

    # ---- команды ----

    @router.message(CommandStart())
    @router.message(Command("help", "menu"))
    async def on_start(message: Message) -> None:
        view = menu_view(await storage.is_subscribed(message.chat.id))
        await message.answer(view.text, reply_markup=view.markup)

    @router.message(Command("stop"))
    async def on_stop(message: Message) -> None:
        removed = await storage.unsubscribe(message.chat.id)
        await message.answer(UNSUBSCRIBED_TEXT if removed else NOT_SUBSCRIBED_TEXT)

    # ---- кнопки ----
    # call.answer() вызываем ДО долгой работы: иначе при медленном сайте Telegram считает запрос
    # просроченным, а у пользователя крутится «часики» на кнопке.

    @router.callback_query(F.data == MENU)
    async def on_menu(call: CallbackQuery) -> None:
        await call.answer()
        chat_id = _chat_id(call)
        if chat_id is not None:
            await _show(call, menu_view(await storage.is_subscribed(chat_id)))

    @router.callback_query(F.data == SUBSCRIBE)
    async def on_subscribe(call: CallbackQuery) -> None:
        chat_id = _chat_id(call)
        if chat_id is None:
            await call.answer()
            return
        await storage.subscribe(chat_id)
        await call.answer(SUBSCRIBED_TOAST)
        await _show(call, menu_view(subscribed=True))

    @router.callback_query(F.data == UNSUBSCRIBE)
    async def on_unsubscribe(call: CallbackQuery) -> None:
        chat_id = _chat_id(call)
        if chat_id is None:
            await call.answer()
            return
        await storage.unsubscribe(chat_id)
        await call.answer(UNSUBSCRIBED_TOAST)
        await _show(call, menu_view(subscribed=False))

    @router.callback_query(F.data == CATEGORIES)
    async def on_categories(call: CallbackQuery) -> None:
        await call.answer()
        await _show(call, await categories_view(feed))

    @router.callback_query(F.data.startswith("l:"))
    async def on_page(call: CallbackQuery) -> None:
        decoded = decode_page(call.data or "")
        if decoded is None:
            await call.answer(BAD_REQUEST_TOAST, show_alert=True)
            return
        await call.answer()
        scope, page = decoded
        await _show(call, await list_view(feed, scope, page, datetime.now(tz).date()))

    # ---- любой другой текст: подсказка с меню (регистрируется последним) ----

    @router.message()
    async def on_other(message: Message) -> None:
        view = menu_view(await storage.is_subscribed(message.chat.id))
        await message.answer(view.text, reply_markup=view.markup)

    return router
