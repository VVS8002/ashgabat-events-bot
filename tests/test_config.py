from datetime import time

import pytest
from pydantic import ValidationError

from bot.config import Settings


def make(**kw):
    return Settings(_env_file=None, bot_token="123:secret", **kw)  # _env_file=None: тест не зависит от вашего .env


def test_defaults_match_ashgabat():
    s = make()
    assert s.timezone_name == "Asia/Ashgabat" and str(s.tz) == "Asia/Ashgabat"
    assert s.digest_at == time(9, 0)
    assert s.feed_url.endswith("/api/public/v1/events")


def test_token_is_hidden_in_repr():
    assert "secret" not in repr(make())


def test_unknown_timezone_fails_at_startup():
    with pytest.raises(ValidationError):
        make(timezone_name="Mars/Olympus")


def test_bad_digest_time_fails_at_startup():
    with pytest.raises(ValidationError):
        make(digest_time="25:99")


def test_insecure_feed_url_rejected():
    with pytest.raises(ValidationError):
        make(feed_url="ftp://example.com/events")


def test_empty_db_path_rejected():
    with pytest.raises(ValidationError):
        make(db_path="   ")


def test_invalid_proxy_scheme_rejected():
    with pytest.raises(ValidationError):
        make(proxy_url="gopher://proxy.lan:8080")