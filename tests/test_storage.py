import asyncio
from datetime import date

import pytest

from bot.storage import Storage

D1, D2 = date(2026, 10, 7), date(2026, 10, 8)


def test_storage_rejects_invalid_chat_id():
    async def run():
        async with Storage(":memory:") as s:
            with pytest.raises(TypeError):
                await s.subscribe("not_an_int")  # type: ignore
            with pytest.raises(ValueError):
                await s.subscribe(10**25)  # exceeds 64-bit

    asyncio.run(run())


def test_subscribe_is_idempotent():
    async def run():
        async with Storage(":memory:") as s:
            assert await s.subscribe(111) is True
            assert await s.subscribe(111) is False  # повтор ничего не меняет
            assert await s.count() == 1 and await s.is_subscribed(111)

    asyncio.run(run())


def test_unsubscribe_removes_row_completely():
    async def run():
        async with Storage(":memory:") as s:
            await s.subscribe(111)
            assert await s.unsubscribe(111) is True
            assert await s.unsubscribe(111) is False
            assert await s.count() == 0 and not await s.is_subscribed(111)
            assert await s.due_for_digest(D1) == []

    asyncio.run(run())


def test_digest_is_sent_once_per_day():
    async def run():
        async with Storage(":memory:") as s:
            await s.subscribe(1)
            await s.subscribe(2)
            assert sorted(await s.due_for_digest(D1)) == [1, 2]

            await s.mark_sent(1, D1)
            assert await s.due_for_digest(D1) == [2]
            assert sorted(await s.due_for_digest(D2)) == [1, 2]

    asyncio.run(run())


def test_mark_sent_many():
    async def run():
        async with Storage(":memory:") as s:
            await s.subscribe(1)
            await s.subscribe(2)
            await s.subscribe(3)
            await s.mark_sent_many([1, 2], D1)
            assert await s.due_for_digest(D1) == [3]
            await s.mark_sent_many([], D1)
            assert await s.due_for_digest(D1) == [3]

    asyncio.run(run())



def test_data_survives_restart(tmp_path):
    path = str(tmp_path / "sub" / "bot.sqlite3")  # вложенной папки ещё нет

    async def run():
        async with Storage(path) as s:
            await s.subscribe(42)
        async with Storage(path) as s:
            assert await s.is_subscribed(42)

    asyncio.run(run())