import asyncio
import json
from datetime import date
from pathlib import Path

from bot.feed import FeedResult, FeedUnavailable
from bot.models import Event
from bot.render import STALE_NOTE
from bot.service import ERROR_TEXT, categories_view, list_view, menu_view

FIXTURE = Path(__file__).parent / "fixtures" / "events.json"
EVENTS = [Event.model_validate(e) for e in json.loads(FIXTURE.read_text("utf-8"))["events"]]
TODAY = date(2026, 10, 8)


class FakeFeed:
    def __init__(self, events=None, stale=False, fail=False):
        self.events, self.stale, self.fail, self.calls = events or [], stale, fail, []
        self.origin = "https://www.ashgabatevents.com"

    async def get_events(self, *, when=None, category=None):
        self.calls.append((when, category))
        if self.fail:
            raise FeedUnavailable("down")
        return FeedResult(self.events, self.stale)


def buttons(view):
    return [(b.text, b.callback_data) for row in view.markup.inline_keyboard for b in row]


def test_list_view_for_period():
    feed = FakeFeed(EVENTS)
    view = asyncio.run(list_view(feed, "w.today", 0, TODAY))
    assert feed.calls == [("today", None)]
    assert view.text.startswith("<b>Сегодня</b>") and "CrossTalk Debate." in view.text
    assert ("🏠 Меню", "menu") in buttons(view)


def test_ongoing_event_moves_to_last_page():
    first = asyncio.run(list_view(FakeFeed(EVENTS), "w.week", 0, TODAY))
    second = asyncio.run(list_view(FakeFeed(EVENTS), "w.week", 1, TODAY))
    assert "ОКТЯБРЬ в AÝAL" not in first.text  # месячная выставка не вытесняет остальные с первой страницы
    assert "ОКТЯБРЬ в AÝAL" in second.text


def test_list_view_for_category_uses_its_label_and_no_period():
    feed = FakeFeed([e for e in EVENTS if e.category.slug == "workshops"])
    view = asyncio.run(list_view(feed, "c.workshops", 0, TODAY))
    assert feed.calls == [(None, "workshops")]
    assert view.text.startswith("<b>Мастер-классы</b>")


def test_list_view_marks_stale_data():
    view = asyncio.run(list_view(FakeFeed(EVENTS, stale=True), "w.week", 0, TODAY))
    assert STALE_NOTE in view.text


def test_list_view_when_site_is_down():
    view = asyncio.run(list_view(FakeFeed(fail=True), "w.week", 0, TODAY))
    assert view.text == ERROR_TEXT and buttons(view) == [("🏠 Меню", "menu")]


def test_list_view_rejects_forged_scope():
    feed = FakeFeed(EVENTS)
    view = asyncio.run(list_view(feed, "w.yesterday", 0, TODAY))
    assert view.text == ERROR_TEXT and feed.calls == []  # на сайт даже не ходили


def test_categories_view():
    view = asyncio.run(categories_view(FakeFeed(EVENTS)))
    assert ("Образование", "l:c.education:0") in buttons(view)
    assert view.text == "Выберите категорию:"


def test_categories_view_without_events_and_when_down():
    assert "Пока нет событий" in asyncio.run(categories_view(FakeFeed([]))).text
    assert asyncio.run(categories_view(FakeFeed(fail=True))).text == ERROR_TEXT


def test_menu_view_reflects_subscription():
    assert ("🔕 Отписаться от дайджеста", "unsub") in buttons(menu_view(True))
    assert ("🔔 Подписаться на дайджест", "sub") in buttons(menu_view(False))
