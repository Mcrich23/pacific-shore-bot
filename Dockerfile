FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pacific_shore_bot.py /app/pacific_shore_bot.py

RUN useradd --create-home --uid 10001 bot \
  && mkdir -p /data \
  && chown -R bot:bot /data /app

USER bot

CMD ["python", "/app/pacific_shore_bot.py"]
