import json
from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from bot.models import Event

FIXTURE = Path(__file__).parent / "fixtures" / "events.json"


def raw_events():
    return json.loads(FIXTURE.read_text("utf-8"))["events"]


def load():
    return [Event.model_validate(e) for e in raw_events()]


def test_all_events_parse():
    assert len(load()) == 6


def test_multi_day_event_has_date_only_bounds():
    e = load()[0]
    assert e.start == date(2026, 10, 1) and not isinstance(e.start, datetime)
    assert e.end == date(2026, 10, 31)
    assert e.start_time_known is False


def test_timed_event_is_aware_with_ashgabat_offset():
    e = load()[2]
    assert isinstance(e.start, datetime)
    assert e.start.utcoffset().total_seconds() == 5 * 3600
    assert e.end is not None


def test_event_without_end():
    assert load()[1].end is None


def test_price_and_category():
    e = load()[2]
    assert e.price.is_free and e.price.text == "Бесплатно"
    assert e.category.slug == "education" and e.category.label == "Образование"


def test_series_key_shared_by_recurring_events():
    ev = load()
    assert ev[1].series_key == ev[5].series_key
    assert ev[0].series_key is None


def test_naive_datetime_is_rejected():
    bad = raw_events()[1]
    bad["start"] = "2026-10-08T16:00:00"  # без часового пояса
    with pytest.raises(ValidationError):
        Event.model_validate(bad)