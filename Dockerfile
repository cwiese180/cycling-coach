FROM python:3.12-slim

WORKDIR /app

# System deps (tzdata for zoneinfo)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY scripts/ ./scripts/

# Persistent data dir for SQLite
RUN mkdir -p /app/data
VOLUME ["/app/data"]

CMD ["python", "-m", "app.bot"]
