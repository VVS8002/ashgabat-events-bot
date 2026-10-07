import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from bot.models import Event
from bot.ordering import sort_for_display

FIXTURE = Path(__file__).parent / "fixtures" / "events.json"
EVENTS = [Event.model_validate(e) for e in json.loads(FIXTURE.read_text("utf-8"))["events"]]
ASHGABAT = timezone(timedelta(hours=5))


def order(result):
    return [EVENTS.index(e) for e in result]


def test_ongoing_event_goes_last():
    # 8 октября: выставка на весь месяц (индекс 0) уже идёт, остальные начнутся
    assert order(sort_for_display(EVENTS, date(2026, 10, 8))) == [1, 2, 3, 4, 5, 0]


def test_input_order_does_not_matter():
    result = sort_for_display(list(reversed(EVENTS)), date(2026, 10, 8))
    assert order(result) == [1, 2, 3, 4, 5, 0]


def test_timed_events_sorted_by_time_within_day():
    evening = EVENTS[2]  # 9 октября, 17:00
    morning = evening.model_copy(update={"id": "m", "start": datetime(2026, 10, 9, 9, 0, tzinfo=ASHGABAT)})
    assert sort_for_display([evening, morning], date(2026, 10, 9)) == [morning, evening]


def test_unknown_time_goes_after_timed_events_of_same_day():
    timed = EVENTS[2]
    unknown = timed.model_copy(update={"id": "u", "start": date(2026, 10, 9), "start_time_known": False})
    assert sort_for_display([unknown, timed], date(2026, 10, 9)) == [timed, unknown]


def test_ongoing_events_sorted_by_soonest_end():
    base = EVENTS[0]
    long_one = base.model_copy(update={"id": "x", "start": date(2026, 10, 1), "end": date(2026, 10, 31)})
    short_one = base.model_copy(update={"id": "y", "start": date(2026, 10, 5), "end": date(2026, 10, 20)})
    assert sort_for_display([long_one, short_one], date(2026, 10, 7)) == [short_one, long_one]