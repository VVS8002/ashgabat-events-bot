import asyncio
import json
from pathlib import Path

import httpx
import pytest

from bot.feed import FeedClient, FeedUnavailable, first_of_series, parse_page
from bot.models import Event

FIXTURE = Path(__file__).parent / "fixtures" / "events.json"
URL = "https://example.org/api/public/v1/events"


def raw():
    return json.loads(FIXTURE.read_text("utf-8"))


def make_client(handler, clock=lambda: 0.0, **kw):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return FeedClient(URL, http=http, clock=clock, **kw)


def test_parse_page_returns_events_and_cursor():
    events, cursor = parse_page(raw())
    assert len(events) == 6 and cursor is None


def test_parse_page_skips_invalid_event():
    data = raw()
    data["events"][0]["start"] = "2026-10-01T10:00:00"  # без часового пояса
    events, _ = parse_page(data)
    assert len(events) == 5


def test_parse_page_wrong_shape():
    with pytest.raises(ValueError):
        parse_page({"items": []})


def test_first_of_series_keeps_only_first():
    events = [Event.model_validate(e) for e in raw()["events"]]
    result = first_of_series(events)
    assert len(result) == 5  # две CrossTalk Debate = одна серия
    assert [e.id for e in result if e.series_key] == ["387de46a-34ec-4601-a6fd-4e475169205b"]


def test_query_params_are_sent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json=raw())

    asyncio.run(make_client(handler).get_events(when="weekend", category="education"))
    assert seen == {"lang": "ru", "limit": "100", "when": "weekend", "category": "education"}


def test_unknown_when_is_rejected():
    with pytest.raises(ValueError):
        asyncio.run(make_client(lambda r: httpx.Response(200, json=raw())).get_events(when="yesterday"))


def test_pagination_follows_cursor():
    base = raw()
    page1 = {**base, "events": base["events"][:3], "next_cursor": "abc"}
    page2 = {**base, "events": base["events"][3:], "next_cursor": None}
    cursors = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursors.append(request.url.params.get("cursor"))
        return httpx.Response(200, json=page2 if request.url.params.get("cursor") == "abc" else page1)

    result = asyncio.run(make_client(handler).get_events(when="week"))
    assert cursors == [None, "abc"]
    assert len(result.events) == 5  # 6 событий минус дубль серии


def test_cache_then_stale_fallback_then_unavailable():
    state = {"fail": False, "calls": 0, "t": 0.0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        return httpx.Response(503) if state["fail"] else httpx.Response(200, json=raw())

    async def run():
        fc = make_client(handler, clock=lambda: state["t"], ttl=300)
        assert not (await fc.get_events(when="today")).stale
        assert state["calls"] == 1

        state["t"] = 100  # TTL не истёк: на сайт не ходим
        await fc.get_events(when="today")
        assert state["calls"] == 1

        await fc.get_events(when="week")  # другой ключ: отдельный запрос
        assert state["calls"] == 2

        state["t"], state["fail"] = 1000, True  # TTL истёк, сайт лежит
        stale = await fc.get_events(when="today")
        assert stale.stale and len(stale.events) == 5

        with pytest.raises(FeedUnavailable):  # для этого ключа кэша нет
            await fc.get_events(when="tomorrow")

    asyncio.run(run())


def test_feed_rejects_insecure_scheme():
    with pytest.raises(ValueError):
        FeedClient("file:///etc/passwd")


def test_feed_rejects_payload_too_large():
    huge_json = b'{"events": []}' + b" " * (6 * 1024 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=huge_json)

    with pytest.raises(FeedUnavailable):
        asyncio.run(make_client(handler).get_events(when="today"))