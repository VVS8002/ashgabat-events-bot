"""Порядок показа: сначала то, что начнётся (по дате и времени), потом то, что уже идёт."""
from datetime import date, datetime, time

from .models import Event


def _day(v: date | datetime) -> date:
    return v.date() if isinstance(v, datetime) else v


def sort_for_display(events: list[Event], today: date) -> list[Event]:
    """today = сегодняшняя дата в Ашхабаде. Месячные выставки не должны вытеснять вечерние события."""

    def key(e: Event):
        start_day = _day(e.start)
        if start_day < today:  # уже идёт: те, что скоро закончатся, первыми
            end_day = _day(e.end) if e.end else start_day
            return (1, end_day, start_day, time.max)
        # В пределах дня: сначала со временем, затем «время не указано»
        t = e.start.time() if isinstance(e.start, datetime) and e.start_time_known else time.max
        return (0, start_day, t, start_day)

    return sorted(events, key=key)
