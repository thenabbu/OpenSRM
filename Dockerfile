FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
    && rm -f /app/.venv/lib/python3.11/site-packages/ddddocr/common_det.onnx \
             /app/.venv/lib/python3.11/site-packages/ddddocr/common_old.onnx \
    && rm -rf /app/.venv/lib/python3.11/site-packages/cv2 \
    && printf 'raise RuntimeError("cv2 stub: real OpenCV removed. Install opencv-python-headless if needed.")\n' \
       > /app/.venv/lib/python3.11/site-packages/cv2.py

# Playwright headless shell only. Cache-mounted so uv.lock bumps don't force a 278MB re-download.
ENV PATH="/app/.venv/bin:$PATH"
RUN --mount=type=cache,target=/root/.cache/ms-playwright,sharing=locked \
    PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright playwright install --only-shell chromium \
    && mkdir -p /ms-playwright \
    && cp -a /root/.cache/ms-playwright/. /ms-playwright/

# -- Stage 2: Runtime --
FROM python:3.11-slim

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
WORKDIR /app

COPY . .

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-w", "1", "--threads", "8", "-t", "120", "--worker-class", "gthread", "-b", "0.0.0.0:8080", "app.app:app"]
