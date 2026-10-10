# syntax=docker/dockerfile:1
FROM python:3.13-slim

# Бот работает через polling (исходящие соединения), входящих портов не открывает.
WORKDIR /app

# Отдельный непривилегированный пользователь: если в коде когда-нибудь найдётся
# уязвимость, она не даст процессу прав root внутри контейнера.
RUN groupadd --system app && useradd --system --gid app --home /app app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY main.py ./main.py

# База лежит в /app/data — монтируйте этот путь как volume, иначе подписчики
# и прогресс рассылки теряются при каждом пересоздании контейнера.
RUN mkdir -p /app/data && chown -R app:app /app

USER app
ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/bot.sqlite3

ENTRYPOINT ["python", "-m", "bot.main"]
