"""Точка входа: запуск Telegram бота и планировщика дайджеста."""
import asyncio
import logging
import sys

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Settings
from .digest import send_digest
from .feed import FeedClient
from .handlers import create_router
from .storage import Storage

log = logging.getLogger("ashgabat_events_bot")


async def main() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    log.info("Starting Ashgabat Events Bot...")

    bot_session = AiohttpSession(proxy=settings.proxy_url) if settings.proxy_url else None
    bot_properties = DefaultBotProperties(parse_mode=ParseMode.HTML)
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        session=bot_session,
        default=bot_properties,
    )

    http_client = (
        httpx.AsyncClient(proxy=settings.proxy_url, timeout=15.0, follow_redirects=True)
        if settings.proxy_url
        else None
    )

    storage = Storage(settings.db_path)
    feed = FeedClient(
        url=settings.feed_url,
        ttl=settings.feed_ttl_seconds,
        http=http_client,
    )

    await storage.__aenter__()

    dp = Dispatcher()
    router = create_router(feed, storage, settings.tz)
    dp.include_router(router)

    scheduler = AsyncIOScheduler(timezone=settings.tz)
    scheduler.add_job(
        send_digest,
        "cron",
        hour=settings.digest_at.hour,
        minute=settings.digest_at.minute,
        timezone=settings.tz,
        args=[bot, feed, storage, settings.tz],
        name="daily_digest",
    )
    scheduler.start()
    log.info("Scheduler started: digest set for %s (%s)", settings.digest_time, settings.timezone_name)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        log.info("Shutting down bot...")
        scheduler.shutdown(wait=False)
        await feed.aclose()
        await storage.close()
        await bot.session.close()
        log.info("Cleanup completed.")


if __name__ == "__main__":
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")
