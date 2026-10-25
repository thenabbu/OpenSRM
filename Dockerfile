FROM python:3.11-slim@sha256:b7a9e5f6a93d6d4a31f129bbd4bdee69efccb6ded0fb230d78aafaf37af98377 AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.17@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# git: needed by uv to resolve the blobatar git dependency (not present in slim image)
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
# WITH_PLAYWRIGHT=1 ships the archived browser fallback (playwright wheel +
# headless Chromium + its shared libs); the default 0 leaves all three out —
# see README "Playwright fallback (archived)". Declared before uv sync so the
# extra rides the same cache-mounted layer.
ARG WITH_PLAYWRIGHT=0
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$WITH_PLAYWRIGHT" = "1" ]; then \
        uv sync --frozen --no-dev --no-install-project --extra browser; \
    else \
        uv sync --frozen --no-dev --no-install-project; \
    fi

ENV PATH="/app/.venv/bin:$PATH"
# Headless shell only, cache-mounted so uv.lock bumps don't force a 278MB
# re-download. ffmpeg is dropped afterwards: Playwright only uses it for video
# recording, which OpenSRM never does. Empty /ms-playwright (off) still copies
# through so the runtime stage's COPY has a source either way.
RUN --mount=type=cache,target=/root/.cache/ms-playwright,sharing=locked \
    mkdir -p /ms-playwright \
    && if [ "$WITH_PLAYWRIGHT" = "1" ]; then \
        PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright playwright install --only-shell chromium \
        && cp -a /root/.cache/ms-playwright/. /ms-playwright/ \
        && rm -rf /ms-playwright/ffmpeg-*; \
    fi

# -- Stage 2: Runtime -- (same verified digest as builder)
FROM python:3.11-slim@sha256:b7a9e5f6a93d6d4a31f129bbd4bdee69efccb6ded0fb230d78aafaf37af98377

# Re-declared for the runtime stage: gates the Chromium shared-library stack
# and the chromium symlink below (0 = the shipped default).
ARG WITH_PLAYWRIGHT=0

LABEL org.opencontainers.image.title="OpenSRM" \
      org.opencontainers.image.description="Self-hosted attendance dashboard for the SRM Student Portal" \
      org.opencontainers.image.url="https://github.com/thenabbu/OpenSRM" \
      org.opencontainers.image.source="https://github.com/thenabbu/OpenSRM" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="thenabbu"

# Chromium's shared-library stack — only for WITH_PLAYWRIGHT=1; the pure-HTTP
# pipeline needs none of it (this layer was 250 MB uncompressed / 81 MB
# compressed on every pull).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    if [ "$WITH_PLAYWRIGHT" = "1" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
        libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
        libatspi2.0-0 libx11-xcb1 fonts-liberation; \
    fi

# Base image's system setuptools 79.0.1 vendors wheel 0.45.1 and
# jaraco.context 5.3.0 — both flagged HIGH by trivy (the app runs from
# /app/.venv and never touches setuptools, but it sits in the scanned
# layer). Bump setuptools+wheel to current. pip is deliberately NOT
# upgraded: base pip 24.0 has only MEDIUM CVEs, while pip 26.x ships a
# vendored bom.cdx.json SBOM (urllib3 2.7.0 / msgpack 1.1.2) that trivy
# parses as 4 new HIGH findings — trading 6 MEDIUM rows for 4 HIGH rows.
RUN pip install --no-cache-dir -U setuptools wheel

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /ms-playwright /ms-playwright

RUN if [ "$WITH_PLAYWRIGHT" = "1" ]; then \
        ln -sf "$(find /ms-playwright -name chrome-headless-shell -type f | head -1)" /usr/local/bin/chromium; \
    fi

ENV CHROMIUM_PATH=/usr/local/bin/chromium
ENV PATH="/app/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ENV LOG_LEVEL=INFO
# the process is dropped to opensrm, whose passwd entry has no home dir, so
# HOME would stay /root and gunicorn's arbiter logs
# "Control server error: Permission denied: '/root/.gunicorn'" on every boot.
# /tmp is the tmpfs the hardened compose mounts — writable in both phases.
ENV HOME=/tmp
WORKDIR /app

COPY . .

# Non-root runtime. The old comment here claimed Playwright needs root; it
# does not — app/app.py _get_browser() always passes --no-sandbox, so headless
# Chromium runs fine as an unprivileged user (proved in the built image).
#
# No USER directive: entrypoint.sh must start as ROOT to chown the data volume
# (every existing volume is root-owned from the root-era image), then it drops
# to opensrm with setpriv and execs CMD in place — so PID 1 ends up non-root
# with CapEff cleared, and nothing after that line ever runs as root.
# absolute paths: the runtime ENV PATH above drops /usr/sbin
RUN /usr/sbin/groupadd --gid 10001 opensrm \
    && /usr/sbin/useradd --uid 10001 --gid opensrm --no-create-home opensrm

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-w", "1", "--threads", "8", "-t", "120", "--worker-class", "gthread", "-b", "0.0.0.0:8080", "app.app:app"]
