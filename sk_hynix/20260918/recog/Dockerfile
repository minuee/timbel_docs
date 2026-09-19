# syntax=docker/dockerfile:1.7
#
# recog-backend — Audio Sync Capture Platform backend service
#
# Two-stage build:
#   1. builder  — compiles Python bytecode (future-proof slot for pip deps)
#   2. runtime  — minimal python:3.11-slim image with ffmpeg + non-root user
#
# BuildKit cache mounts are used for apt and pip so repeated CI builds
# reuse previously-downloaded packages instead of hitting the network.

ARG PYTHON_VERSION=3.11

# =====================================================================
# Stage 1: builder
# =====================================================================
FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /build

# Copy source tree; keeps Dockerfile stable when we add pip deps later.
COPY src/ ./src/

# Pre-compile bytecode so the runtime image starts faster.
RUN python -m compileall -q ./src

# =====================================================================
# Stage 2: runtime
# =====================================================================
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

LABEL org.opencontainers.image.title="recog-backend" \
      org.opencontainers.image.description="Audio Sync Capture Platform backend (WSGI)" \
      org.opencontainers.image.source="https://gitlab.timbel.dev/apps/timblo/recog"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    RECOG_HOST=0.0.0.0 \
    RECOG_PORT=8080

# ffmpeg/ffprobe are the only runtime OS deps; curl is used for healthcheck.
# `rm -f docker-clean` lets the apt cache mount actually persist.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid ${APP_GID} recog && \
    useradd  --system --uid ${APP_UID} --gid recog \
             --home-dir /app --shell /usr/sbin/nologin recog

WORKDIR /app

COPY --from=builder --chown=recog:recog /build/src ./src

RUN mkdir -p /var/lib/recog/runtime && \
    chown -R recog:recog /var/lib/recog

USER recog
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${RECOG_PORT}/health" || exit 1

ENTRYPOINT ["python", "-m", "recog"]
CMD ["--data-root", "/var/lib/recog/runtime", "serve"]
