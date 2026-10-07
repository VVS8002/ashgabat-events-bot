import json
from pathlib import Path

from bot.keyboards import (
    categories_kb, decode_page, encode_page, menu_kb, pager_kb, parse_scope, scope_category, scope_when,
)
from bot.models import Category, Event
from bot.ordering import collect_categories
from bot.render import Page

FIXTURE = Path(__file__).parent / "fixtures" / "events.json"
EVENTS = [Event.model_validate(e) for e in json.loads(FIXTURE.read_text("utf-8"))["events"]]


def flat(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


def test_page_callback_roundtrip():
    for scope in (scope_when("week"), scope_category("education")):
        assert decode_page(encode_page(scope, 3)) == (scope, 3)


def test_decode_rejects_garbage():
    for bad in ("", "l", "l:w.today", "l:w.today:abc", "l:w.today:-1", "x:w.today:1", "l:w.yesterday:0",
                "l:c.UPPER:0", "l:c.a b:0", "l:w.today:1:2"):
        assert decode_page(bad) is None, bad


def test_parse_scope():
    assert parse_scope("w.today") == ("today", None)
    assert parse_scope("c.workshops") == (None, "workshops")
    assert parse_scope("c.") is None and parse_scope("c.x/../y") is None


def test_longest_callback_fits_telegram_limit():
    data = encode_page(scope_category("a" * 40), 999)
    assert len(data.encode()) <= 64


def test_menu_toggles_subscription_button():
    assert ("🔔 Подписаться на дайджест", "sub") in flat(menu_kb(subscribed=False))
    assert ("🔕 Отписаться от дайджеста", "unsub") in flat(menu_kb(subscribed=True))
    assert ("Сегодня", "l:w.today:0") in flat(menu_kb(False))


def test_pager_buttons_follow_page_flags():
    middle = flat(pager_kb("w.week", Page("x", page=1, pages=3)))
    assert ("◀️ Назад", "l:w.week:0") in middle and ("Далее ▶️", "l:w.week:2") in middle
    first = flat(pager_kb("w.week", Page("x", page=0, pages=3)))
    assert all("Назад" not in text for text, _ in first)
    only = flat(pager_kb("w.week", Page("x", page=0, pages=1)))
    assert only == [("🏠 Меню", "menu")]


def test_categories_from_events_and_keyboard():
    cats = collect_categories(EVENTS)
    assert [c.slug for c in cats] == ["education", "workshops", "community"]  # по убыванию числа событий
    kb = categories_kb(cats + [Category(slug="Bad Slug!", label="Битая")])
    texts = [t for t, _ in flat(kb)]
    assert "Образование" in texts and "Битая" not in texts  # некодируемую категорию пропускаем
    assert flat(kb)[-1] == ("🏠 Меню", "menu")