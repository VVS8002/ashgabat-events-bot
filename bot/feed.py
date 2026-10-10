"""Клиент API заказчика: when/category, пагинация по cursor, одно событие на серию, кэш."""
import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from urllib.parse import urlsplit

from .models import Event

log = logging.getLogger(__name__)

WHEN_VALUES = {"today", "tomorrow", "weekend", "week", "nextweek"}
CATEGORY_RE = re.compile(r"^[a-z0-9_-]{1,40}$")  # тот же формат, что в bot/keyboards.py (SLUG_RE)
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 МБ макс. размер одного ответа от API
MAX_CACHE_ENTRIES = 256  # ограничение размера кэша для защиты памяти
DEFAULT_HEADERS = {
    "User-Agent": "AshgabatEventsBot/1.0 (+https://www.ashgabatevents.com)",
    "Accept": "application/json",
}


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
            msg = exc.errors()[0].get("msg", str(exc)) if exc.errors() else str(exc)
            log.warning("skip invalid event id=%s: %s", ident, msg)
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
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError(f"invalid feed url scheme: {url!r}")
        self._url, self._lang, self._limit = url, lang, limit
        self._max_pages, self._ttl, self._clock = max_pages, ttl, clock
        self._http = http or httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers=DEFAULT_HEADERS,
        )
        self._cache: dict[tuple, tuple[list[Event], float]] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}

    async def __aenter__(self) -> "FeedClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def origin(self) -> str:
        """Схема + хост сайта, выведенные из feed_url. Используется рендером, чтобы не
        доверять произвольным ссылкам из ленты (защита от подмены домена)."""
        parts = urlsplit(self._url)
        return f"{parts.scheme}://{parts.netloc}"

    async def get_events(self, *, when: str | None = None, category: str | None = None) -> FeedResult:
        if when is not None and when not in WHEN_VALUES:
            raise ValueError(f"unknown 'when': {when!r}")
        if category is not None and not CATEGORY_RE.match(category):
            # На практике сюда ничего постороннего не попадает: вызывающий код (keyboards.decode_page)
            # уже проверяет формат. Проверяем повторно здесь, чтобы FeedClient был безопасен сам по
            # себе — например, если его начнут вызывать из нового места без этой проверки.
            raise ValueError(f"invalid category slug: {category!r}")
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
            if len(self._cache) >= MAX_CACHE_ENTRIES and key not in self._cache:
                oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
                self._cache.pop(oldest_key, None)
                self._locks.pop(oldest_key, None)
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
        seen_cursors: set[str] = set()
        for _ in range(self._max_pages):
            query = {**params, **({"cursor": cursor} if cursor else {})}
            resp = await self._http.get(self._url, params=query)
            resp.raise_for_status()
            if len(resp.content) > MAX_RESPONSE_BYTES:
                raise ValueError("feed response payload exceeded maximum allowed size")
            page, cursor = parse_page(resp.json())
            events.extend(page)
            if not cursor:
                break
            if cursor in seen_cursors:
                log.warning("feed pagination loop detected for cursor=%s; stopping pagination", cursor)
                break
            seen_cursors.add(cursor)
        else:
            log.warning("feed has more pages than max_pages=%s; list truncated", self._max_pages)
        return first_of_series(events)
