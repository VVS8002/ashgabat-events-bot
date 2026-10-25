from datetime import date, datetime, time

from .models import Category, Event

TIME_MAX = time.max


def _day(v: date | datetime) -> date:
    return v.date() if isinstance(v, datetime) else v


def sort_for_display(events: list[Event], today: date) -> list[Event]:
    def key(e: Event):
        start_day = _day(e.start)
        if start_day < today:
            end_day = _day(e.end) if e.end else start_day
            return (1, end_day, start_day, TIME_MAX)
        t = e.start.time() if isinstance(e.start, datetime) and e.start_time_known else TIME_MAX
        return (0, start_day, t, start_day)

    return sorted(events, key=key)


def collect_categories(events: list[Event], limit: int = 12) -> list[Category]:
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for e in events:
        slug = e.category.slug
        counts[slug] = counts.get(slug, 0) + 1
        if slug not in labels:
            labels[slug] = e.category.label
    ranked = sorted(counts, key=lambda slug: (-counts[slug], labels[slug]))
    return [Category(slug=slug, label=labels[slug]) for slug in ranked[:limit]]
