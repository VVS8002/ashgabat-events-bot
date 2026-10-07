"""Клиент API заказчика: when/category, пагинация по cursor, одно событие на серию, кэш."""
import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from .models import Event

log = logging.getLogger(__name__)

WHEN_VALUES = {"today", "tomorrow", "weekend", "week", "nextweek"}


class FeedUnavailable(Exception):
    """Сайт недоступен и в кэше для этого запроса пусто."""


@dataclass(frozen=True)
class FeedResult:
    events: list[Event]
    stale: bool  # True = показываем кэш, потому что свежие данные получить не удалось


def parse_page(raw) -> tuple[list[Event], str | None]:
    """Одна страница ответа -> (события, next_cursor). Битые события пропускаются."""
    if not isinstance(raw, dict) or not isinstance(raw.get("events"), list):
        raise ValueError("unexpected feed shape")
    events: list[Event] = []
    for item in raw["events"]:
        try:
            events.append(Event.model_validate(item))
        except ValidationError as exc:
            ident = item.get("id") if isinstance(item, dict) else None
            log.warning("skip invalid event id=%s: %s", ident, exc.errors()[0]["msg"])
    return events, raw.get("next_cursor")


def first_of_series(events: list[Event]) -> list[Event]:
    """У повторяющихся событий общий series_key: оставляем только первое из серии."""
    seen: set[str] = set()
    out: list[Event] = []
    for e in events:
        if e.series_key:
            if e.series_key in seen:
                continue
            seen.add(e.series_key)
        out.append(e)
    return out


class FeedClient:
    def __init__(
        self,
        url: str,
        *,
        lang: str = "ru",
        limit: int = 100,
        max_pages: int = 5,
        ttl: int = 300,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url, self._lang, self._limit = url, lang, limit
        self._max_pages, self._ttl, self._clock = max_pages, ttl, clock
        self._http = http or httpx.AsyncClient(timeout=15.0, follow_redirects=True)
        self._cache: dict[tuple, tuple[list[Event], float]] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_events(self, *, when: str | None = None, category: str | None = None) -> FeedResult:
        if when is not None and when not in WHEN_VALUES:
            raise ValueError(f"unknown 'when': {when!r}")
        key = (when, category)
        async with self._locks.setdefault(key, asyncio.Lock()):  # один запрос на ключ, а не на каждое нажатие
            cached = self._cache.get(key)
            if cached and self._clock() - cached[1] < self._ttl:
                return FeedResult(cached[0], stale=False)
            try:
                events = await self._fetch_all(when, category)
            except Exception as exc:  # сеть, HTTP-статус, не-JSON, неверная форма
                if cached:
                    log.warning("feed refresh failed (%s); serving stale cache", exc)
                    return FeedResult(cached[0], stale=True)
                raise FeedUnavailable(str(exc)) from exc
            self._cache[key] = (events, self._clock())
            return FeedResult(events, stale=False)

    async def _fetch_all(self, when: str | None, category: str | None) -> list[Event]:
                
        params: dict[str, str | int] = {}
        if when:
            params["when"] = when
        if category:
            params["category"] = category
        params["lang"] = self._lang
        params["limit"] = self._limit

        events: list[Event] = []
        cursor: str | None = None
        for _ in range(self._max_pages):
            query = {**params, **({"cursor": cursor} if cursor else {})}
            resp = await self._http.get(self._url, params=query)
            resp.raise_for_status()
            page, cursor = parse_page(resp.json())
            events.extend(page)
            if not cursor:
                break
        else:
            log.warning("feed has more pages than max_pages=%s; list truncated", self._max_pages)
        return first_of_series(events)