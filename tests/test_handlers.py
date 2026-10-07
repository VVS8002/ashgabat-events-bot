import asyncio
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest

from bot.feed import FeedResult
from bot.handlers import create_router
from bot.models import Event
from bot.storage import Storage

FIXTURE = Path(__file__).parent / "fixtures" / "events.json"
EVENTS = [Event.model_validate(e) for e in json.loads(FIXTURE.read_text("utf-8"))["events"]]
TZ = ZoneInfo("Asia/Ashgabat")


class FakeFeed:
    async def get_events(self, *, when=None, category=None):
        return FeedResult(EVENTS, stale=False)


def make_message(chat_id=123):
    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.answer = AsyncMock()
    return msg


def make_callback(chat_id=123, data="menu"):
    call = MagicMock()
    call.data = data
    call.message = MagicMock()
    call.message.chat = MagicMock()
    call.message.chat.id = chat_id
    call.message.edit_text = AsyncMock()
    call.answer = AsyncMock()
    return call


def test_start_and_help_commands():
    async def run():
        async with Storage(":memory:") as storage:
            feed = FakeFeed()
            router = create_router(feed, storage, TZ)

            on_start = router.message.handlers[0].callback
            msg = make_message(100)
            await on_start(msg)
            msg.answer.assert_called_once()
            args, kwargs = msg.answer.call_args
            assert "Афиша событий" in args[0]
            assert kwargs.get("parse_mode") == "HTML"

            on_help = router.message.handlers[1].callback
            msg_help = make_message(100)
            await on_help(msg_help)
            msg_help.answer.assert_called_once()

    asyncio.run(run())


def test_subscribe_and_unsubscribe_callbacks():
    async def run():
        async with Storage(":memory:") as storage:
            feed = FakeFeed()
            router = create_router(feed, storage, TZ)

            # Find handlers by callback
            sub_handler = next(h.callback for h in router.callback_query.handlers if h.callback.__name__ == "on_subscribe")
            unsub_handler = next(h.callback for h in router.callback_query.handlers if h.callback.__name__ == "on_unsubscribe")

            call = make_callback(200, "sub")
            await sub_handler(call)
            assert await storage.is_subscribed(200) is True
            call.answer.assert_called_once_with("Вы подписались на ежедневный дайджест! 🔔")
            call.message.edit_text.assert_called_once()

            call_unsub = make_callback(200, "unsub")
            await unsub_handler(call_unsub)
            assert await storage.is_subscribed(200) is False
            call_unsub.answer.assert_called_once_with("Вы отписались от дайджеста. 🔕")

    asyncio.run(run())


def test_categories_and_menu_callbacks():
    async def run():
        async with Storage(":memory:") as storage:
            feed = FakeFeed()
            router = create_router(feed, storage, TZ)

            menu_handler = next(h.callback for h in router.callback_query.handlers if h.callback.__name__ == "on_menu")
            cats_handler = next(h.callback for h in router.callback_query.handlers if h.callback.__name__ == "on_categories")

            call_cats = make_callback(300, "cats")
            await cats_handler(call_cats)
            call_cats.message.edit_text.assert_called_once()
            assert "Выберите категорию:" in call_cats.message.edit_text.call_args[0][0]

            call_menu = make_callback(300, "menu")
            await menu_handler(call_menu)
            call_menu.message.edit_text.assert_called_once()
            assert "Афиша событий" in call_menu.message.edit_text.call_args[0][0]

    asyncio.run(run())


def test_page_pagination_and_invalid_data():
    async def run():
        async with Storage(":memory:") as storage:
            feed = FakeFeed()
            router = create_router(feed, storage, TZ)

            page_handler = next(h.callback for h in router.callback_query.handlers if h.callback.__name__ == "on_page")

            # Valid page callback
            call_valid = make_callback(400, "l:w.today:0")
            await page_handler(call_valid)
            call_valid.message.edit_text.assert_called_once()
            call_valid.answer.assert_called_once_with()

            # Invalid page callback
            call_invalid = make_callback(400, "l:invalid_data")
            await page_handler(call_invalid)
            call_invalid.answer.assert_called_once_with("Неверный запрос", show_alert=True)

    asyncio.run(run())


def test_message_not_modified_is_suppressed():
    async def run():
        async with Storage(":memory:") as storage:
            feed = FakeFeed()
            router = create_router(feed, storage, TZ)

            menu_handler = next(h.callback for h in router.callback_query.handlers if h.callback.__name__ == "on_menu")
            call = make_callback(500, "menu")
            call.message.edit_text.side_effect = TelegramBadRequest(MagicMock(), "Bad Request: message is not modified")

            # Should not raise exception
            await menu_handler(call)
            call.answer.assert_called_once()

    asyncio.run(run())
