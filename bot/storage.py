from datetime import date
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
    chat_id        INTEGER PRIMARY KEY,
    last_sent_date TEXT
)
"""


def _check_chat_id(chat_id: int) -> int:
    if not isinstance(chat_id, int):
        raise TypeError(f"chat_id must be int, got {type(chat_id).__name__}")
    if not (-9_223_372_036_854_775_808 <= chat_id <= 9_223_372_036_854_775_807):
        raise ValueError(f"chat_id out of 64-bit integer range: {chat_id}")
    return chat_id


class Storage:
    def __init__(self, path: str) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def __aenter__(self) -> "Storage":
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        await self._db.execute("PRAGMA busy_timeout = 5000")
        if self._path != ":memory:":
            await self._db.execute("PRAGMA journal_mode = WAL")
        await self._db.execute(SCHEMA)
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_subscribers_last_sent ON subscribers (last_sent_date)")
        await self._db.commit()
        return self

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aexit__(self, *exc) -> None:
        await self.close()

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not connected; use 'async with Storage(...)'")
        return self._db

    async def subscribe(self, chat_id: int) -> bool:
        _check_chat_id(chat_id)
        cur = await self.db.execute("INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)", (chat_id,))
        await self.db.commit()
        return cur.rowcount == 1

    async def unsubscribe(self, chat_id: int) -> bool:
        _check_chat_id(chat_id)
        cur = await self.db.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        await self.db.commit()
        return cur.rowcount == 1

    async def is_subscribed(self, chat_id: int) -> bool:
        _check_chat_id(chat_id)
        cur = await self.db.execute("SELECT 1 FROM subscribers WHERE chat_id = ?", (chat_id,))
        return await cur.fetchone() is not None

    async def due_for_digest(self, today: date) -> list[int]:
        cur = await self.db.execute(
            "SELECT chat_id FROM subscribers WHERE last_sent_date IS NULL OR last_sent_date < ?",
            (today.isoformat(),),
        )
        return [row[0] for row in await cur.fetchall()]

    async def mark_sent(self, chat_id: int, today: date) -> None:
        _check_chat_id(chat_id)
        await self.db.execute("UPDATE subscribers SET last_sent_date = ? WHERE chat_id = ?", (today.isoformat(), chat_id))
        await self.db.commit()

    async def mark_sent_many(self, chat_ids: list[int] | set[int], today: date) -> None:
        if not chat_ids:
            return
        iso = today.isoformat()
        params = [(iso, _check_chat_id(cid)) for cid in chat_ids]
        await self.db.executemany("UPDATE subscribers SET last_sent_date = ? WHERE chat_id = ?", params)
        await self.db.commit()

    async def count(self) -> int:
        cur = await self.db.execute("SELECT COUNT(*) FROM subscribers")
        row = await cur.fetchone()
        return row[0] if row else 0