"""Защитные проверки FeedClient, добавленные при аудите безопасности."""
import asyncio

import httpx
import pytest

from bot.feed import FeedClient


def test_rejects_non_http_url():
    with pytest.raises(ValueError):
        FeedClient("ftp://example.org/events")


def test_origin_is_scheme_plus_host():
    fc = FeedClient("https://www.ashgabatevents.com/api/public/v1/events?x=1")
    assert fc.origin == "https://www.ashgabatevents.com"


@pytest.mark.parametrize("bad", ["../etc/passwd", "UPPER", "a b", "a/b", "a.b", "x" * 41, ""])
def test_rejects_malformed_category(bad):
    fc = FeedClient("https://example.org/api")
    with pytest.raises(ValueError):
        asyncio.run(fc.get_events(category=bad))


def test_oversized_response_is_rejected():
    big = b'{"events":[' + b"0" * (6 * 1024 * 1024) + b"]}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big, headers={"content-type": "application/json"})

    fc = FeedClient("https://example.org/api", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(Exception):  # оборачивается в FeedUnavailable при отсутствии кэша
        asyncio.run(fc.get_events(when="today"))


def test_cursor_loop_does_not_hang():
    def handler(request: httpx.Request) -> httpx.Response:
        # Сайт зациклил курсор: всегда просит перейти на cursor=same
        return httpx.Response(200, json={"events": [], "next_cursor": "same"})

    fc = FeedClient("https://example.org/api", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)), max_pages=50)
    result = asyncio.run(fc.get_events(when="today"))
    assert result.events == []  # не зависло, вернуло пустой список после обнаружения петли
