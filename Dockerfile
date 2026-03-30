# === Builder stage ===
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# === Runtime stage ===
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    wireguard-tools \
    iproute2 \
    iptables \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

RUN useradd -m -r appuser

WORKDIR /app
COPY . .
RUN chown -R appuser:appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
