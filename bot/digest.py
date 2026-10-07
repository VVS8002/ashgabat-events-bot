"""Ежедневная подборка подписчикам. Запускается планировщиком раз в сутки утром."""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from .feed import FeedClient, FeedUnavailable
from .keyboards import pager_kb, scope_when
from .ordering import sort_for_display
from .render import render_page
from .storage import Storage

log = logging.getLogger(__name__)

DIGEST_TITLE = "☀️ Сегодня"
DEAD_REASONS = ("chat not found", "deactivated", "blocked", "kicked", "not a member", "user is deactivated")
_digest_lock = asyncio.Lock()


async def _send(bot: Bot, chat_id: int, text: str, markup) -> None:
    try:
        await bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
    except TelegramRetryAfter as exc:  # Telegram просит подождать: ждём и пробуем один раз ещё
        if exc.retry_after > 30:
            log.warning("retry_after too large (%s s); skipping chat %s for now", exc.retry_after, chat_id)
            raise
        await asyncio.sleep(exc.retry_after)
        await bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")


async def send_digest(
    bot: Bot,
    feed: FeedClient,
    storage: Storage,
    tz: ZoneInfo,
    *,
    now: datetime | None = None,
    pause: float = 0.05,  # ~20 сообщений в секунду, лимит Telegram около 30
) -> int:
    """Возвращает число отправленных сообщений."""
    if _digest_lock.locked():
        log.warning("digest already in progress; skipping duplicate concurrent run")
        return 0

    async with _digest_lock:
        today = (now or datetime.now(tz)).date()
        chat_ids = await storage.due_for_digest(today)  # кому ещё не отправляли сегодня
        if not chat_ids:
            return 0

        try:
            result = await feed.get_events(when="today")
        except FeedUnavailable as exc:
            log.warning("digest skipped, feed unavailable: %s", exc)
            return 0  # никого не отмечаем: при следующем запуске попробуем снова

        events = sort_for_display(result.events, today)
        if not events:  # на сегодня ничего нет: молчим, но отмечаем, чтобы перезапуск днём не слал «поздний» дайджест
            for chat_id in chat_ids:
                await storage.mark_sent(chat_id, today)
            return 0

        page = render_page(events, title=DIGEST_TITLE, stale=result.stale)
        markup = pager_kb(scope_when("today"), page)

        sent = 0
        for chat_id in chat_ids:
            try:
                await _send(bot, chat_id, page.text, markup)
                await storage.mark_sent(chat_id, today)
                sent += 1
            except TelegramForbiddenError:  # пользователь заблокировал бота
                await storage.unsubscribe(chat_id)
            except TelegramBadRequest as exc:  # пользователь удалил аккаунт или чат не найден
                if any(r in exc.message.lower() for r in DEAD_REASONS):
                    await storage.unsubscribe(chat_id)
                else:
                    log.warning("digest delivery bad request: %s", exc.message)
            except TelegramAPIError as exc:
                log.warning("digest delivery failed: %s", type(exc).__name__)  # chat_id в лог не пишем
            except Exception as exc:
                log.exception("unexpected error delivering digest: %s", type(exc).__name__)
            await asyncio.sleep(pause)
        return sent