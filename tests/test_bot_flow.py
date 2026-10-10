"""Прогон обработчиков через настоящий Dispatcher aiogram с подставной сессией (сеть не нужна)."""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import logging

import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, InaccessibleMessage, Message, MessageEntity, Update, User

from bot.feed import FeedResult
from bot.handlers import NOT_SUBSCRIBED_TEXT, UNSUBSCRIBED_TEXT, create_router
from bot.models import Event
from bot.storage import Storage

FIXTURE = Path(__file__).parent / "fixtures" / "events.json"
EVENTS = [Event.model_validate(e) for e in json.loads(FIXTURE.read_text("utf-8"))["events"]]
TZ = ZoneInfo("Asia/Ashgabat")
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=TZ)
USER = User(id=5, is_bot=False, first_name="T")
CHAT = Chat(id=5, type="private")


class MockSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        if False:
            yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(message_id=99, date=NOW, chat=Chat(id=method.chat_id, type="private"))
        return True


class FakeFeed:
    def __init__(self):
        self.calls = []
        self.origin = "https://www.ashgabatevents.com"

    async def get_events(self, *, when=None, category=None):
        self.calls.append((when, category))
        return FeedResult(EVENTS, stale=False)


def message_update(text):
    entities = [MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))] if text.startswith("/") else None
    msg = Message(message_id=1, date=NOW, chat=CHAT, from_user=USER, text=text, entities=entities)
    return Update(update_id=1, message=msg)


def callback_update(data, accessible=True):
    msg = Message(message_id=1, date=NOW, chat=CHAT, from_user=USER, text="old") if accessible \
        else InaccessibleMessage(chat=CHAT, message_id=1)
    return Update(update_id=1, callback_query=CallbackQuery(id="1", from_user=USER, chat_instance="c", data=data, message=msg))


class EditFailsSession(MockSession):
    """Telegram отвечает ошибкой на editMessageText (текст из параметра)."""

    reason = "Bad Request: message is not modified: specified new message content and reply markup are exactly the same"

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, EditMessageText):
            raise TelegramBadRequest(method, self.reason)
        return await super().make_request(bot, method, timeout)


def run(update, subscribed=False, session_cls=MockSession):
    async def go():
        session, feed = session_cls(), FakeFeed()
        bot = Bot("42:TEST", session=session)
        async with Storage(":memory:") as storage:
            if subscribed:
                await storage.subscribe(5)
            dp = Dispatcher()
            dp.include_router(create_router(feed, storage, TZ))
            await dp.feed_update(bot, update)
            return session.calls, feed.calls, await storage.is_subscribed(5)

    return asyncio.run(go())


def kinds(calls):
    return [type(c) for c in calls]


def test_stop_unsubscribes_and_confirms():
    calls, _, subscribed = run(message_update("/stop"), subscribed=True)
    assert not subscribed and calls[0].text == UNSUBSCRIBED_TEXT


def test_stop_when_not_subscribed():
    calls, _, subscribed = run(message_update("/stop"))
    assert not subscribed and calls[0].text == NOT_SUBSCRIBED_TEXT


def test_start_shows_menu_and_any_text_does_too():
    for text in ("/start", "/menu", "привет"):
        calls, *_ = run(message_update(text))
        assert kinds(calls) == [SendMessage] and calls[0].reply_markup is not None, text


def test_page_button_answers_first_then_edits():
    calls, feed_calls, _ = run(callback_update("l:w.today:0"))
    assert kinds(calls) == [AnswerCallbackQuery, EditMessageText]  # «часики» гасим до обращения к сайту
    assert feed_calls == [("today", None)]


def test_old_inaccessible_message_gets_a_new_message_instead_of_crash():
    calls, *_ = run(callback_update("l:w.week:1", accessible=False))
    assert kinds(calls) == [AnswerCallbackQuery, SendMessage] and calls[1].chat_id == 5


@pytest.mark.parametrize("data", ["l:w.yesterday:0", "l:invalid_data", "l:c.UPPER:0", "l:w.today:-1", "l:w.today:x"])
def test_forged_callback_is_rejected_without_touching_the_site(data):
    calls, feed_calls, _ = run(callback_update(data))
    assert kinds(calls) == [AnswerCallbackQuery] and calls[0].show_alert is True and feed_calls == []


def test_subscribe_and_unsubscribe_buttons():
    calls, _, subscribed = run(callback_update("sub"))
    assert subscribed and kinds(calls) == [AnswerCallbackQuery, EditMessageText]

    _, _, subscribed = run(callback_update("unsub"), subscribed=True)
    assert not subscribed


def test_subscribe_from_inaccessible_message_still_works():
    calls, _, subscribed = run(callback_update("sub", accessible=False))
    assert subscribed and kinds(calls) == [AnswerCallbackQuery, SendMessage]


def test_categories_button():
    calls, feed_calls, _ = run(callback_update("cats"))
    assert kinds(calls) == [AnswerCallbackQuery, EditMessageText] and feed_calls == [(None, None)]


def test_message_not_modified_is_silently_ignored(caplog):
    with caplog.at_level(logging.WARNING):
        calls, *_ = run(callback_update("menu"), session_cls=EditFailsSession)  # не должно упасть
    assert AnswerCallbackQuery in kinds(calls) and caplog.records == []  # и не шуметь в логе


def test_other_edit_errors_are_logged_but_do_not_crash_the_handler(caplog):
    class Gone(EditFailsSession):
        reason = "Bad Request: message to edit not found"

    with caplog.at_level(logging.WARNING):
        calls, *_ = run(callback_update("menu"), session_cls=Gone)
    assert AnswerCallbackQuery in kinds(calls)
    assert any("failed to edit message" in r.getMessage() for r in caplog.records)
