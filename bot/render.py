"""Тексты карточек для Telegram (parse_mode=HTML). Весь текст из API экранируется."""
import html
import re
from dataclasses import dataclass
from math import ceil

from .models import Event

PER_PAGE = 5
MAX_TITLE = 120
MAX_VENUE = 100
MAX_PRICE = 60

# Опасные скрытые символы и символы изменения направления текста (BiDi override),
# используемые для спуфинга текста и ссылок
DANGEROUS_CHARS = re.compile(r"[\u202a-\u202e\u2066-\u2069\x00-\x08\x0b\x0c\x0e-\x1f]")

EMPTY_TEXT = "Пока ничего не нашлось. Попробуйте другой период или категорию."
STALE_NOTE = "⚠️ Данные могли устареть: сайт сейчас недоступен."

WHEN_LABELS = {
    "today": "Сегодня",
    "tomorrow": "Завтра",
    "weekend": "Выходные",
    "week": "Эта неделя",
    "nextweek": "Следующая неделя",
}


def _esc(text: str) -> str:
    return html.escape(text, quote=False)  # Telegram HTML: нужны только & < >


def _cut(text: str, limit: int) -> str:
    text = DANGEROUS_CHARS.sub("", text)  # удаляем скрытые и BiDi-символы
    text = " ".join(text.split())  # схлопываем переводы строк и лишние пробелы
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _when_line(e: Event) -> str:
    # Время «не указано» пользователю не нужно: показываем только дату
    if e.start_time_known and e.time_text:
        return f"{e.date_text}, {e.time_text}"
    return e.date_text


def render_event(e: Event) -> str:
    lines = [f"<b>{_esc(_cut(e.title, MAX_TITLE))}</b>", f"🗓 {_esc(_when_line(e))}"]

    venue = (e.venue.text or e.venue.name) if e.venue else None
    if venue and venue.strip():
        lines.append(f"📍 {_esc(_cut(venue, MAX_VENUE))}")

    price = e.price.text if e.price and e.price.text and e.price.text.strip() else "Цена не указана"
    lines.append(f"💰 {_esc(_cut(price, MAX_PRICE))}")

    url = e.url.strip()
    if url.startswith("/"):
        url = f"https://www.ashgabatevents.com{url}"
    elif not url.startswith(("http://", "https://")):
        url = "https://www.ashgabatevents.com"
    url = url[:1024]
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
    parts = [head] + ([STALE_NOTE] if stale else []) + [render_event(e) for e in chunk]
    return Page("\n\n".join(parts), page, pages)