import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import Settings
from .digest import send_digest
from .feed import FeedClient
from .handlers import create_router
from .storage import Storage

log = logging.getLogger("events_bot")

DIGEST_CHECK_MINUTES = 10


async def main() -> None:
    settings = Settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    log.info("Starting bot")

    session = AiohttpSession(proxy=settings.proxy_url) if settings.proxy_url else AiohttpSession()
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    feed = FeedClient(settings.feed_url, ttl=settings.feed_ttl_seconds)
    scheduler = AsyncIOScheduler(timezone=settings.tz)

    try:
        async with Storage(settings.db_path) as storage:
            dp = Dispatcher()
            dp.include_router(create_router(feed, storage, settings.tz))

            scheduler.add_job(
                send_digest,
                IntervalTrigger(minutes=DIGEST_CHECK_MINUTES, timezone=settings.tz),
                args=[bot, feed, storage, settings.tz],
                kwargs={"digest_at": settings.digest_at},
                next_run_time=datetime.now(settings.tz),
                max_instances=1,
                coalesce=True,
                name="daily_digest",
            )
            scheduler.start()
            log.info("Digest window opens at %s (%s)", settings.digest_time, settings.timezone_name)

            await dp.start_polling(bot)
            if scheduler.running:
                scheduler.shutdown(wait=True)
    finally:
        log.info("Shutting down")
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await feed.aclose()
        await bot.session.close()


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot stopped")


if __name__ == "__main__":
    run()
