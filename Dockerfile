FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt \
  && playwright install --with-deps chromium webkit \
  && apt-get update \
  && apt-get install -y --no-install-recommends xauth \
  && rm -rf /var/lib/apt/lists/*

COPY pacific_shore_bot.py /app/pacific_shore_bot.py

RUN useradd --create-home --uid 10001 bot \
  && mkdir -p /data \
  && chown -R bot:bot /data /app /ms-playwright

USER bot

CMD ["python", "/app/pacific_shore_bot.py"]
