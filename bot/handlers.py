import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
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
DEBOUNCE_INTERVAL = 0.2


def create_router(feed: FeedClient, storage: Storage, tz: ZoneInfo) -> Router:
    router = Router(name="main_router")
    user_last_action: dict[int, float] = {}

    def _is_spam(user_id: int) -> bool:
        now = time.monotonic()
        last = user_last_action.get(user_id, 0.0)
        if now - last < DEBOUNCE_INTERVAL:
            return True
        if len(user_last_action) > 10_000:
            user_last_action.clear()
        user_last_action[user_id] = now
        return False

    def _chat_id(call: CallbackQuery) -> int | None:
        return call.message.chat.id if call.message else None

    async def _show(call: CallbackQuery, view: View) -> None:
        if isinstance(call.message, Message):
            try:
                await call.message.edit_text(view.text, reply_markup=view.markup)
            except TelegramBadRequest as exc:
                if "message is not modified" not in exc.message.lower():
                    log.warning("failed to edit message: %s", exc.message)
            except TelegramRetryAfter:
                log.info("edit skipped: flood control")
            except TelegramAPIError as exc:
                log.warning("failed to edit message: %s", exc)
            return
        chat_id = _chat_id(call)
        if chat_id is not None:
            try:
                await call.bot.send_message(chat_id, view.text, reply_markup=view.markup)
            except TelegramAPIError as exc:
                log.warning("failed to send message for inaccessible call: %s", exc)

    @router.message(CommandStart())
    @router.message(Command("help", "menu"))
    async def on_start(message: Message) -> None:
        if message.chat.type != "private":
            return
        view = menu_view(await storage.is_subscribed(message.chat.id))
        await message.answer(view.text, reply_markup=view.markup)

    @router.message(Command("stop"))
    async def on_stop(message: Message) -> None:
        if message.chat.type != "private":
            return
        removed = await storage.unsubscribe(message.chat.id)
        await message.answer(UNSUBSCRIBED_TEXT if removed else NOT_SUBSCRIBED_TEXT)

    @router.callback_query(F.data == MENU)
    async def on_menu(call: CallbackQuery) -> None:
        if call.from_user and _is_spam(call.from_user.id):
            await call.answer()
            return
        await call.answer()
        chat_id = _chat_id(call)
        if chat_id is not None:
            await _show(call, menu_view(await storage.is_subscribed(chat_id)))

    @router.callback_query(F.data == SUBSCRIBE)
    async def on_subscribe(call: CallbackQuery) -> None:
        if call.from_user and _is_spam(call.from_user.id):
            await call.answer()
            return
        chat_id = _chat_id(call)
        if chat_id is None:
            await call.answer()
            return
        if call.message and call.message.chat.type != "private":
            await call.answer("Доступно только в личном чате", show_alert=True)
            return
        await storage.subscribe(chat_id)
        await call.answer(SUBSCRIBED_TOAST)
        await _show(call, menu_view(subscribed=True))

    @router.callback_query(F.data == UNSUBSCRIBE)
    async def on_unsubscribe(call: CallbackQuery) -> None:
        if call.from_user and _is_spam(call.from_user.id):
            await call.answer()
            return
        chat_id = _chat_id(call)
        if chat_id is None:
            await call.answer()
            return
        if call.message and call.message.chat.type != "private":
            await call.answer("Доступно только в личном чате", show_alert=True)
            return
        await storage.unsubscribe(chat_id)
        await call.answer(UNSUBSCRIBED_TOAST)
        await _show(call, menu_view(subscribed=False))

    @router.callback_query(F.data == CATEGORIES)
    async def on_categories(call: CallbackQuery) -> None:
        if call.from_user and _is_spam(call.from_user.id):
            await call.answer()
            return
        await call.answer()
        await _show(call, await categories_view(feed))

    @router.callback_query(F.data.startswith("l:"))
    async def on_page(call: CallbackQuery) -> None:
        if call.from_user and _is_spam(call.from_user.id):
            await call.answer()
            return
        decoded = decode_page(call.data or "")
        if decoded is None:
            await call.answer(BAD_REQUEST_TOAST, show_alert=True)
            return
        await call.answer()
        scope, page = decoded
        await _show(call, await list_view(feed, scope, page, datetime.now(tz).date()))

    @router.message()
    async def on_other(message: Message) -> None:
        if message.chat.type != "private":
            return
        view = menu_view(await storage.is_subscribed(message.chat.id))
        await message.answer(view.text, reply_markup=view.markup)

    return router
