FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge/ bridge/
COPY hospital/ hospital/
COPY epcr/ epcr/

# Runs as a non-root user; the data volume is mounted at runtime.
RUN useradd -r -u 10001 app && chown -R app /app
USER app

EXPOSE 8001 8002
