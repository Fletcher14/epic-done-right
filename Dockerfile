FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge/ bridge/
COPY hospital/ hospital/
COPY epcr/ epcr/

# Runs as a non-root user. /app/state must exist AND be owned by that user in the
# image -- Docker seeds a fresh named volume from the image directory, so this is
# what makes the volume writable without resorting to root or chown-on-boot.
RUN useradd -r -u 10001 app \
 && mkdir -p /app/state \
 && chown -R app /app
USER app

EXPOSE 8001 8002
