"""Тексты карточек для Telegram (parse_mode=HTML). Весь текст из API экранируется."""
import html
import re
from dataclasses import dataclass
from math import ceil
from urllib.parse import urlsplit, urlunsplit

from .models import Event

PER_PAGE = 5
MAX_TITLE = 120
MAX_VENUE = 100
MAX_PRICE = 60
MAX_DATE_LINE = 80
MAX_RAW_URL = 2000  # дальше даже не парсим: явно мусор или атака

# Опасные скрытые символы, символы изменения направления текста (BiDi override) и невидимые
# символы-разделители, используемые для спуфинга текста и ссылок. U+200D (ZWJ) не трогаем:
# он склеивает составные эмодзи (например, в названиях событий).
DANGEROUS_CHARS = re.compile(
    r"[\u202a-\u202e\u2066-\u2069\x00-\x08\x0b\x0c\x0e-\x1f\u200b\u2060\ufeff]"
)

EMPTY_TEXT = "Пока ничего не нашлось. Попробуйте другой период или категорию."
STALE_NOTE = "⚠ Данные могли устареть: сайт сейчас недоступен."

WHEN_LABELS = {
    "today": "Сегодня",
    "tomorrow": "Завтра",
    "weekend": "Выходные",
    "week": "Эта неделя",
    "nextweek": "Следующая неделя",
}

# Используется, только если вызывающий код не передал site_origin явно (production-код в
# service.py и digest.py всегда передаёт его из FeedClient.origin, т.е. из настоящего FEED_URL).
DEFAULT_SITE_ORIGIN = "https://www.ashgabatevents.com"


def _esc(text: str) -> str:
    return html.escape(text, quote=False)  # Telegram HTML: нужны только & < >


def _cut(text: str, limit: int) -> str:
    text = DANGEROUS_CHARS.sub("", text)  # удаляем скрытые и BiDi-символы
    text = " ".join(text.split())  # схлопываем переводы строк и лишние пробелы
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _when_line(e: Event) -> str:
    # date_text/time_text приходят с сайта как есть: чистим и ограничиваем длину так же,
    # как остальные текстовые поля, а не доверяем им как «служебным» строкам.
    date_part = _cut(e.date_text, MAX_DATE_LINE)
    if e.start_time_known and e.time_text:
        return f"{date_part}, {_cut(e.time_text, 30)}"
    return date_part


def _safe_url(raw_url: str, site_origin: str) -> str:
    """Ссылка «Подробнее на сайте» ведёт на страницу события у заказчика — и больше никуда.
    Пропускаем только https-ссылки на тот же хост, что и site_origin; относительный путь
    («/ru/events/...») достраиваем до site_origin. Всё остальное (javascript:, другой домен,
    http без «s», мусор) заменяется ссылкой на главную сайта."""
    raw_url = raw_url.strip()[:MAX_RAW_URL]
    if raw_url.startswith("/"):
        raw_url = site_origin.rstrip("/") + raw_url

    try:
        parts = urlsplit(raw_url)
        origin_parts = urlsplit(site_origin)
    except ValueError:
        return site_origin

    if parts.scheme == "https" and parts.netloc == origin_parts.netloc and parts.netloc:
        return urlunsplit(parts)
    return site_origin


def render_event(e: Event, *, site_origin: str = DEFAULT_SITE_ORIGIN) -> str:
    lines = [f"<b>{_esc(_cut(e.title, MAX_TITLE))}</b>", f"🗓 {_esc(_when_line(e))}"]

    venue = (e.venue.text or e.venue.name) if e.venue else None
    if venue and venue.strip():
        lines.append(f"📍 {_esc(_cut(venue, MAX_VENUE))}")

    price = e.price.text if e.price and e.price.text and e.price.text.strip() else "Цена не указана"
    lines.append(f"💰 {_esc(_cut(price, MAX_PRICE))}")

    url = _safe_url(e.url, site_origin)
    lines.append(f'<a href="{html.escape(url, quote=True)}">Подробнее на сайте</a>')
    return "\n".join(lines)


@dataclass(frozen=True)
class Page:
    text: str
    page: int
    pages: int

    @property
    def has_prev(self) -> bool:
        return self.page > 0

    @property
    def has_next(self) -> bool:
        return self.page < self.pages - 1


def render_page(
    events: list[Event],
    *,
    title: str,
    page: int = 0,
    per_page: int = PER_PAGE,
    stale: bool = False,
    site_origin: str = DEFAULT_SITE_ORIGIN,
) -> Page:
    head = f"<b>{_esc(title)}</b>"
    if not events:
        parts = [head, EMPTY_TEXT] + ([STALE_NOTE] if stale else [])
        return Page("\n\n".join(parts), 0, 1)

    per_page = max(1, per_page)
    pages = ceil(len(events) / per_page)
    page = max(0, min(page, pages - 1))  # номер страницы из кнопки не доверяем слепо
    chunk = events[page * per_page : (page + 1) * per_page]

    head += f"\nНайдено: {len(events)}" + (f" · стр. {page + 1}/{pages}" if pages > 1 else "")
    parts = [head] + ([STALE_NOTE] if stale else []) + [render_event(e, site_origin=site_origin) for e in chunk]
    return Page("\n\n".join(parts), page, pages)
