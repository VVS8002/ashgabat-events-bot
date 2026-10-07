"""Запуск Telegram бота из корневого каталога проекта."""
import asyncio
import sys

from bot.main import main

if __name__ == "__main__":
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
