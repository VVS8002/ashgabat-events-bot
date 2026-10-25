import asyncio
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter

from .feed import FeedClient, FeedUnavailable
from .keyboards import pager_kb, scope_when
from .ordering import sort_for_display
from .render import render_page
from .storage import Storage

log = logging.getLogger(__name__)

DIGEST_TITLE = "☀️ Сегодня"
BATCH_COMMIT_SIZE = 20


async def _send(bot: Bot, chat_id: int, text: str, markup) -> None:
    try:
        await bot.send_message(chat_id, text, reply_markup=markup)
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after)
        await bot.send_message(chat_id, text, reply_markup=markup)


async def send_digest(
    bot: Bot,
    feed: FeedClient,
    storage: Storage,
    tz: ZoneInfo,
    *,
    now: datetime | None = None,
    pause: float = 0.05,
    digest_at: time | None = None,
    window: timedelta = timedelta(hours=3),
) -> int:
    now = (now or datetime.now(tz)).astimezone(tz)
    today = now.date()
    if digest_at is not None:
        start = datetime.combine(today, digest_at, tzinfo=tz)
        if not (start <= now < start + window):
            return 0
    chat_ids = await storage.due_for_digest(today)
    if not chat_ids:
        return 0

    try:
        result = await feed.get_events(when="today")
    except FeedUnavailable as exc:
        log.warning("digest skipped, feed unavailable: %s", exc)
        return 0

    events = sort_for_display(result.events, today)
    if not events:
        await storage.mark_sent_many(chat_ids, today)
        return 0

    page = render_page(events, title=DIGEST_TITLE, stale=result.stale, site_origin=feed.origin)
    markup = pager_kb(scope_when("today"), page)

    sent = 0
    batch: list[int] = []
    try:
        for chat_id in chat_ids:
            try:
                await _send(bot, chat_id, page.text, markup)
                batch.append(chat_id)
                sent += 1
                if len(batch) >= BATCH_COMMIT_SIZE:
                    try:
                        await storage.mark_sent_many(batch, today)
                        batch.clear()
                    except Exception as exc:
                        log.warning("failed to mark digest sent: %s", exc)
            except TelegramForbiddenError:
                await storage.unsubscribe(chat_id)
            except TelegramAPIError as exc:
                log.warning("digest delivery failed: %s", type(exc).__name__)
            except Exception as exc:
                log.warning("digest delivery failed: %s", type(exc).__name__)
            await asyncio.sleep(pause)
    finally:
        if batch:
            try:
                await storage.mark_sent_many(batch, today)
            except Exception as exc:
                log.warning("failed to mark digest sent in finally: %s", exc)
    return sent
