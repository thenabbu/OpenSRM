FROM python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.17@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# git: needed by uv to resolve the blobatar git dependency (not present in slim image)
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Playwright headless shell only. Cache-mounted so uv.lock bumps don't force a 278MB re-download.
ENV PATH="/app/.venv/bin:$PATH"
RUN --mount=type=cache,target=/root/.cache/ms-playwright,sharing=locked \
    PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright playwright install --only-shell chromium \
    && mkdir -p /ms-playwright \
    && cp -a /root/.cache/ms-playwright/. /ms-playwright/

# -- Stage 2: Runtime -- (same verified digest as builder)
FROM python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e

LABEL org.opencontainers.image.title="OpenSRM" \
      org.opencontainers.image.description="Self-hosted attendance dashboard for the SRM Student Portal" \
      org.opencontainers.image.url="https://github.com/thenabbu/OpenSRM" \
      org.opencontainers.image.source="https://github.com/thenabbu/OpenSRM" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="thenabbu"

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libatspi2.0-0 libx11-xcb1 fonts-liberation

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /ms-playwright /ms-playwright

RUN ln -sf $(find /ms-playwright -name chrome-headless-shell -type f | head -1) /usr/local/bin/chromium

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
