from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: SecretStr
    feed_url: str = "https://www.ashgabatevents.com/api/public/v1/events"
    timezone_name: str = "Asia/Ashgabat"
    digest_time: str = "09:00"
    feed_ttl_seconds: int = 300
    db_path: str = "data/bot.sqlite3"
    log_level: str = "INFO"
    proxy_url: str | None = None

    @field_validator("bot_token", mode="before")
    @classmethod
    def _strip_token(cls, v):
        if isinstance(v, str):
            v = v.strip()
        return v

    @field_validator("timezone_name")
    @classmethod
    def _known_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {v}") from exc
        return v

    @field_validator("digest_time")
    @classmethod
    def _valid_digest_time(cls, v: str) -> str:
        time.fromisoformat(v)
        return v

    @field_validator("feed_ttl_seconds")
    @classmethod
    def _positive_ttl(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("feed_ttl_seconds must be positive")
        return v

    @field_validator("feed_url")
    @classmethod
    def _valid_feed_url(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("feed_url must start with http:// or https://")
        return v

    @field_validator("db_path")
    @classmethod
    def _valid_db_path(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("db_path cannot be empty")
        return v

    @field_validator("proxy_url")
    @classmethod
    def _valid_proxy_url(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not any(v.startswith(proto) for proto in ("http://", "https://", "socks5://", "socks5h://")):
                raise ValueError("proxy_url must use http://, https://, socks5://, or socks5h:// protocol")
        return v

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, v: str) -> str:
        v_upper = v.strip().upper()
        if v_upper not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"unknown log_level: {v}")
        return v_upper

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    @property
    def digest_at(self) -> time:
        return time.fromisoformat(self.digest_time)