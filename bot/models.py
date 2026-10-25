from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator


def _parse_when(v):
    if isinstance(v, str):
        v = v.strip()
        return date.fromisoformat(v) if len(v) == 10 else datetime.fromisoformat(v)
    return v


When = Annotated[date | datetime, BeforeValidator(_parse_when)]


class Venue(BaseModel):
    name: str | None = None
    address: str | None = None
    text: str | None = None


class Category(BaseModel):
    slug: str
    label: str


class Price(BaseModel):
    kind: str
    is_free: bool = False
    amount: float | None = None
    currency: str | None = None
    text: str


class Event(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    summary: str | None = None
    summary_truncated: bool = False
    start: When
    start_time_known: bool = True
    end: When | None = None
    end_time_known: bool | None = None
    date_text: str
    time_text: str
    venue: Venue | None = None
    category: Category
    price: Price | None = None
    image_url: str | None = None
    url: str
    series_key: str | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _timed_values_must_have_offset(self) -> "Event":
        for v in (self.start, self.end):
            if isinstance(v, datetime) and (v.tzinfo is None or v.utcoffset() is None):
                raise ValueError("datetime must include a UTC offset")
        return self