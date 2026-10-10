import json
from pathlib import Path

from bot.models import Event
from bot.render import EMPTY_TEXT, STALE_NOTE, render_event, render_page

FIXTURE = Path(__file__).parent / "fixtures" / "events.json"
EVENTS = [Event.model_validate(e) for e in json.loads(FIXTURE.read_text("utf-8"))["events"]]


def test_card_for_timed_free_event():
    text = render_event(EVENTS[2])  # Воркшоп для родителей
    assert text.startswith("<b>Воркшоп для родителей</b>")
    assert "пт, 9 окт. 2026 г., 17:00 - 19:30" in text
    assert "💰 Бесплатно" in text
    assert '<a href="https://www.ashgabatevents.com/ru/events/333cf392' in text


def test_multi_day_event_hides_unknown_time():
    text = render_event(EVENTS[0])
    assert "Время не указано" not in text
    assert "чт, 1 окт. 2026 г. - сб, 31 окт. 2026 г." in text
    assert "💰 Платно" in text


def test_html_in_title_is_escaped():
    e = EVENTS[1].model_copy(update={"title": "<script>alert(1)</script> & Co"})
    text = render_event(e)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text and "&amp; Co" in text


def test_url_quote_is_escaped():
    # На собственном домене сайта (DEFAULT_SITE_ORIGIN) кавычка в пути должна остаться
    # и корректно экранироваться — это НЕ про подмену домена, а про HTML-экранирование.
    e = EVENTS[1].model_copy(update={"url": 'https://www.ashgabatevents.com/x"y'})
    assert 'href="https://www.ashgabatevents.com/x&quot;y"' in render_event(e)


def test_url_on_foreign_domain_is_replaced_with_site_origin():
    e = EVENTS[1].model_copy(update={"url": "https://evil.example/phish"})
    assert 'href="https://www.ashgabatevents.com"' in render_event(e)
    assert "evil.example" not in render_event(e)


def test_url_scheme_other_than_https_is_rejected():
    for bad in ("http://www.ashgabatevents.com/x", 'javascript:alert(1)', "tg://resolve?x=1", "data:text/html,x"):
        e = EVENTS[1].model_copy(update={"url": bad})
        assert render_event(e).count('href="https://www.ashgabatevents.com"') == 1, bad


def test_relative_url_is_resolved_against_site_origin():
    e = EVENTS[1].model_copy(update={"url": "/ru/events/abc"})
    assert 'href="https://www.ashgabatevents.com/ru/events/abc"' in render_event(e)


def test_custom_site_origin_is_respected():
    e = EVENTS[1].model_copy(update={"url": "https://staging.ashgabatevents.com/ru/events/abc"})
    default = render_event(e)
    custom = render_event(e, site_origin="https://staging.ashgabatevents.com")
    assert 'href="https://www.ashgabatevents.com"' in default  # другой хост -> по умолчанию отклонён
    assert 'href="https://staging.ashgabatevents.com/ru/events/abc"' in custom  # а с явным origin принят


def test_date_and_time_text_are_cleaned_and_bounded():
    e = EVENTS[1].model_copy(update={"date_text": "x" * 300, "time_text": "16:00"})
    text = render_event(e)
    assert "…" in text and ("x" * 300) not in text


def test_bidi_and_zero_width_chars_are_stripped_but_zwj_kept():
    # U+202E (RLO) и U+200B (zero-width space) — убираем; U+200D (ZWJ, склейка эмодзи) — оставляем
    e = EVENTS[1].model_copy(update={"title": "A‮B​C‍D"})
    assert "‮" not in render_event(e) and "​" not in render_event(e)
    assert "‍" in render_event(e)


def test_missing_price_and_venue():
    e = EVENTS[1].model_copy(update={"price": None, "venue": None})
    text = render_event(e)
    assert "Цена не указана" in text and "📍" not in text


def test_long_title_is_trimmed():
    long = "А" * 500
    text = render_event(EVENTS[1].model_copy(update={"title": long}))
    assert "…" in text and long not in text


def test_pagination_flags_and_clamping():
    p0 = render_page(EVENTS, title="Сегодня", per_page=2)
    assert (p0.page, p0.pages, p0.has_prev, p0.has_next) == (0, 3, False, True)
    assert "Найдено: 6 · стр. 1/3" in p0.text

    last = render_page(EVENTS, title="Сегодня", page=2, per_page=2)
    assert last.has_prev and not last.has_next

    assert render_page(EVENTS, title="Сегодня", page=99, per_page=2).page == 2  # номер из кнопки ограничен


def test_empty_and_stale():
    empty = render_page([], title="Сегодня")
    assert EMPTY_TEXT in empty.text and empty.pages == 1
    assert STALE_NOTE in render_page(EVENTS, title="Сегодня", stale=True).text


def test_full_page_fits_telegram_limit():
    base = EVENTS[3]
    big = base.model_copy(update={
        "title": "Т" * 300,
        "venue": base.venue.model_copy(update={"text": "М" * 300}),
    })
    assert len(render_page([big] * 5, title="Эта неделя").text) < 4096
