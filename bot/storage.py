"""Подписчики дайджеста. Храним только chat_id и дату последней рассылки, переписку не храним."""
from datetime import date
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
    chat_id        INTEGER PRIMARY KEY,
    last_sent_date TEXT
)
"""


class Storage:
    def __init__(self, path: str) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def __aenter__(self) -> "Storage":
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        await self._db.execute(SCHEMA)
        await self._db.commit()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "use 'async with Storage(...)'"
        return self._db

    async def subscribe(self, chat_id: int) -> bool:
        """True, если подписчик новый; повторная подписка ничего не меняет."""
        cur = await self.db.execute("INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)", (chat_id,))
        await self.db.commit()
        return cur.rowcount == 1

    async def unsubscribe(self, chat_id: int) -> bool:
        """Удаляет строку целиком. True, если подписчик был."""
        cur = await self.db.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        await self.db.commit()
        return cur.rowcount == 1

    async def is_subscribed(self, chat_id: int) -> bool:
        cur = await self.db.execute("SELECT 1 FROM subscribers WHERE chat_id = ?", (chat_id,))
        return await cur.fetchone() is not None

    async def due_for_digest(self, today: date) -> list[int]:
        """Кому сегодня ещё не отправляли (защита от повторной рассылки после перезапуска)."""
        cur = await self.db.execute(
            "SELECT chat_id FROM subscribers WHERE last_sent_date IS NULL OR last_sent_date < ?",
            (today.isoformat(),),
        )
        return [row[0] for row in await cur.fetchall()]

    async def mark_sent(self, chat_id: int, today: date) -> None:
        await self.db.execute("UPDATE subscribers SET last_sent_date = ? WHERE chat_id = ?", (today.isoformat(), chat_id))
        await self.db.commit()

    async def count(self) -> int:
        cur = await self.db.execute("SELECT COUNT(*) FROM subscribers")
        row = await cur.fetchone()
        return row[0] if row else 0