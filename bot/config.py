"""Настройки из переменных окружения / файла .env."""
from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: SecretStr  # токен не попадёт в логи и repr
    feed_url: str = "https://www.ashgabatevents.com/api/public/v1/events"
    # Не называем TZ: это зарезервированная переменная ОС, на сервере там часто UTC
    timezone_name: str = "Asia/Ashgabat"
    digest_time: str = "09:00"  # локальное время дайджеста, HH:MM
    feed_ttl_seconds: int = 300
    db_path: str = "data/bot.sqlite3"
    log_level: str = "INFO"
    proxy_url: str | None = None  # для разработки, если api.telegram.org недоступен напрямую

    @field_validator("timezone_name")
    @classmethod
    def _known_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)  # упадёт сразу при старте, а не в 9 утра
        except (ZoneInfoNotFoundError, ValueError) as exc:  # первый наследует KeyError, pydantic его не ловит
            raise ValueError(f"unknown timezone: {v}") from exc
        return v

    @field_validator("digest_time")
    @classmethod
    def _valid_digest_time(cls, v: str) -> str:
        time.fromisoformat(v)  # ожидаем HH:MM
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    @property
    def digest_at(self) -> time:
        return time.fromisoformat(self.digest_time)