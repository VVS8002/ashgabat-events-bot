import asyncio
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage

from bot.digest import send_digest
from bot.feed import FeedResult, FeedUnavailable
from bot.models import Event
from bot.storage import Storage

FIXTURE = Path(__file__).parent / "fixtures" / "events.json"
EVENTS = [Event.model_validate(e) for e in json.loads(FIXTURE.read_text("utf-8"))["events"]]
TZ = ZoneInfo("Asia/Ashgabat")
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=TZ)


class FakeFeed:
    def __init__(self, events=None, fail=False):
        self.events, self.fail = events if events is not None else EVENTS, fail

    async def get_events(self, *, when=None, category=None):
        if self.fail:
            raise FeedUnavailable("down")
        return FeedResult(self.events, stale=False)


class FakeBot:
    def __init__(self, blocked=(), flaky=()):
        self.sent, self.blocked, self.flaky = [], set(blocked), set(flaky)

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        if chat_id in self.blocked:
            raise TelegramForbiddenError(SendMessage(chat_id=chat_id, text=text), "Forbidden: bot was blocked by the user")
        if chat_id in self.flaky:
            self.flaky.discard(chat_id)  # в первый раз Telegram просит подождать
            raise TelegramRetryAfter(SendMessage(chat_id=chat_id, text=text), "Too Many Requests", 0)
        self.sent.append(chat_id)


async def run(bot, feed, chats=(1, 2, 3), twice=False):
    async with Storage(":memory:") as s:
        for c in chats:
            await s.subscribe(c)
        first = await send_digest(bot, feed, s, TZ, now=NOW, pause=0)
        second = await send_digest(bot, feed, s, TZ, now=NOW, pause=0) if twice else None
        return first, second, await s.due_for_digest(NOW.date()), await s.count()


def test_sent_to_everyone_and_only_once_per_day():
    bot = FakeBot()
    first, second, due, _ = asyncio.run(run(bot, FakeFeed(), twice=True))
    assert (first, second, due) == (3, 0, []) and bot.sent == [1, 2, 3]


def test_blocked_user_is_unsubscribed_others_still_get_it():
    bot = FakeBot(blocked={2})
    first, _, due, count = asyncio.run(run(bot, FakeFeed()))
    assert first == 2 and bot.sent == [1, 3] and count == 2 and due == []


def test_retry_after_is_retried_once():
    bot = FakeBot(flaky={1})
    first, *_ = asyncio.run(run(bot, FakeFeed(), chats=(1,)))
    assert first == 1 and bot.sent == [1]


def test_no_events_today_means_silence_but_marked_as_done():
    bot = FakeBot()
    first, _, due, _ = asyncio.run(run(bot, FakeFeed(events=[])))
    assert first == 0 and bot.sent == [] and due == []


def test_site_down_sends_nothing_and_keeps_subscribers_due():
    bot = FakeBot()
    first, _, due, _ = asyncio.run(run(bot, FakeFeed(fail=True)))
    assert first == 0 and bot.sent == [] and sorted(due) == [1, 2, 3]  # при следующем запуске попробуем снова


# ---- окно рассылки: функцию можно вызывать каждые 10 минут ----
from datetime import time, timedelta  # noqa: E402

AT = time(9, 0)


def at(hh, mm):
    return datetime(2026, 10, 8, hh, mm, tzinfo=TZ)


async def run_at(bot, feed, moments):
    async with Storage(":memory:") as s:
        await s.subscribe(1)
        results = [await send_digest(bot, feed, s, TZ, now=m, pause=0, digest_at=AT) for m in moments]
        return results, await s.due_for_digest(NOW.date())


def test_nothing_before_digest_time_and_after_window():
    bot = FakeBot()
    results, due = asyncio.run(run_at(bot, FakeFeed(), [at(8, 59), at(12, 0), at(15, 30)]))
    assert results == [0, 0, 0] and bot.sent == [] and due == [1]


def test_sent_once_inside_window_despite_frequent_checks():
    bot = FakeBot()
    results, due = asyncio.run(run_at(bot, FakeFeed(), [at(9, 0), at(9, 10), at(9, 20), at(11, 50)]))
    assert results == [1, 0, 0, 0] and bot.sent == [1] and due == []


def test_site_down_at_nine_is_retried_ten_minutes_later():
    class FlakyFeed(FakeFeed):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def get_events(self, *, when=None, category=None):
            self.calls += 1
            self.fail = self.calls == 1  # первый запрос неудачный
            return await super().get_events(when=when, category=category)

    bot = FakeBot()
    results, due = asyncio.run(run_at(bot, FlakyFeed(), [at(9, 0), at(9, 10)]))
    assert results == [0, 1] and bot.sent == [1] and due == []


def test_catch_up_after_restart_inside_window():
    bot = FakeBot()
    results, _ = asyncio.run(run_at(bot, FakeFeed(), [at(9, 42)]))  # бот включили в 9:42
    assert results == [1]
