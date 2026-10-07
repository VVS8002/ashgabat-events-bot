import asyncio
import logging
import sys

from bot.feed import FeedClient
from datetime import date
from bot.ordering import sort_for_display

if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # чтобы эмодзи в названиях не ломали вывод в Windows
logging.basicConfig(level=logging.INFO)


async def main():
    async with FeedClient("https://www.ashgabatevents.com/api/public/v1/events") as fc:
        for when in ("today", "weekend", "week"):
            r = await fc.get_events(when=when)
            print(f"\n== {when}: {len(r.events)} событий (stale={r.stale})")
            for e in sort_for_display(r.events, date.today()):
                price = e.price.text if e.price else "-"
                print(f"- {e.date_text} | {e.time_text} | {e.title[:50]} | {price}")


if __name__ == "__main__":
    asyncio.run(main())