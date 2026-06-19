# Schematix — production image
# Multi-stage build for a small final image.

FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build deps for numpy / matplotlib / shapely
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user -r requirements.txt

# ── Runtime stage ──────────────────────────────────────────────────────

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/root/.local/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000 \
    NO_BROWSER=1

WORKDIR /app

# Runtime libs only (no -dev variants, no compilers)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgeos-c1v5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
COPY server/         ./server/
COPY analyser-ui/    ./analyser-ui/
COPY analyze.py      ./

# Output dir lives on a volume in compose; create it for non-mounted runs.
RUN mkdir -p output/stl input

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["python", "-m", "server"]
