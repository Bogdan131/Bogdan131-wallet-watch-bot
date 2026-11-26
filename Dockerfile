FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 wallet-watch \
    && useradd --uid 10001 --gid wallet-watch --no-create-home --shell /usr/sbin/nologin wallet-watch \
    && mkdir /app/data \
    && chown wallet-watch:wallet-watch /app/data

COPY --chown=wallet-watch:wallet-watch bot/ ./bot/
USER wallet-watch

CMD ["python", "-m", "bot.main"]
